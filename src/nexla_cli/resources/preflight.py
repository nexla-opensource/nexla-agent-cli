"""Pre-flight table-existence check for DB/warehouse sinks.

`sinks create` does not auto-provision a destination table the way sources
do, so a typo'd or missing table only surfaces as a silent runtime stall.
This module probes the connector before the create fires: it decides whether
the connector is a DB (from its ``kind`` metadata), drills the connector tree
hierarchically, and -- when the tree is blind to tables -- falls back to a
portable ``information_schema.tables`` catalog query. A confirmed miss
hard-fails; anything inconclusive warns and proceeds.

Extracted from ``sinks.py`` so the crawl bounds are injectable in tests and
the sink command module stays focused on the CLI surface. The probe helpers
catch :class:`CliError` (a failed probe -> inconclusive) rather than bare
``Exception``, so a genuine programming error surfaces instead of silently
degrading to "inconclusive".
"""

from __future__ import annotations

from typing import Any

import typer

from .. import client
from ..errors import EXIT, CliError

# DB/warehouse-family connectors: `sinks create` does NOT auto-provision
# the destination table (unlike sources). See AGENTS.md's "DB/JDBC sinks
# require the target table to pre-exist". This hand-list is now only a
# FALLBACK for when the authoritative signal -- the connector's `kind`
# from `nexla-cli connectors describe <connector>` (see `_connector_is_db`) --
# can't be fetched. Includes warehouses (bigquery/snowflake/redshift) so a
# BigQuery sink is no longer silently skipped by the pre-flight.
# Longer-term the name set should go away entirely in favour of the kind
# metadata; it's kept only to stay useful when the describe call fails.
_DB_KIND_CONNECTORS = {
    "postgres",
    "postgresql",
    "supabase",
    "redshift",
    "snowflake",
    "mysql",
    "mariadb",
    "sqlserver",
    "sql_server",
    "oracle",
    "db2",
    "cockroachdb",
    "teradata",
    "singlestore",
    "clickhouse",
    "bigquery",
    "gbq",
    "bq",
}

# Node `type` values (from `probe --action tree`) that denote an actual
# target object -- reaching a level made of these means an absence there is
# trustworthy (a confirmed miss), not just "haven't drilled deep enough".
_TABLE_NODE_TYPES = {"table", "view", "collection", "dataset_table"}

# Bound the hierarchical crawl so a huge catalog can't hang the pre-flight.
_TREE_MAX_NODES = 2000
_TREE_MAX_DEPTH = 6

def _connector_is_db(connector: str) -> bool:
    """True if this connector writes to a pre-existing table (kind ``db``).

    Prefers live metadata -- ``GET /nexla/connectors/describe/<connector>``
    reports ``kind`` (``db``/``api``/``file``/...) -- over the
    hand-maintained ``_DB_KIND_CONNECTORS`` set, so new warehouse
    connectors (e.g. bigquery, kind ``db``) are covered automatically while
    API-shaped ones that merely mention a warehouse (e.g. ``gbq_api``, kind
    ``api``) are correctly excluded. Falls back to the name set only if the
    describe call fails or omits ``kind``.
    """
    try:
        resp = client.request("GET", f"/nexla/connectors/describe/{connector}")
    except CliError:
        resp = None
    if isinstance(resp, dict):
        kind = resp.get("kind")
        if isinstance(kind, str):
            return kind.lower() == "db"
    return connector.lower() in _DB_KIND_CONNECTORS


def _tree_level(credential_id: int, path: str | None) -> list[dict[str, Any]] | None:
    """One `probe --action tree` call for ``path`` (root when ``None``).

    Returns the list of node dicts for that level, or ``None`` when the call
    failed or the response wasn't tree-shaped -- callers treat ``None`` as
    "could not enumerate this level" (inconclusive), never as "empty".
    """
    params: dict[str, object] = {} if path is None else {"path": path}
    try:
        resp = client.request(
            "POST",
            "/nexla/probe",
            json={"action": "tree", "credential_id": credential_id, "params": params},
        )
    except CliError:
        return None
    if not isinstance(resp, dict):
        return None
    nodes = resp.get("nodes")
    if not isinstance(nodes, list):
        return None
    return [n for n in nodes if isinstance(n, dict)]


def _probe_tree_names(credential_id: int, target: str) -> tuple[list[str], bool]:
    """Hierarchically walk `probe --action tree`, collecting node names.

    The root call only ever returns the top database node, so the old flat
    single-level probe never saw real tables. This follows
    ``has_children`` and drills with an accumulated dot-joined ``path``
    (``postgres`` -> ``postgres.public`` -> ...) down through
    database -> schema/dataset -> table levels.

    Returns ``(names, complete)``. ``complete`` is ``True`` only when every
    level we needed was enumerated without error AND we actually reached a
    leaf/table level -- i.e. an *absence* of ``target`` is trustworthy. Any
    probe failure, or a branch that advertises children but returns none,
    leaves ``complete`` ``False`` (inconclusive) so callers WARN-and-proceed
    instead of hard-failing on a partial view of the tree.
    """
    names: list[str] = []
    errored = False
    bounded = False
    reached_leaf_level = False
    found = False

    # (path, depth); root is None. DFS, bounded by node count and depth.
    stack: list[tuple[str | None, int]] = [(None, 0)]
    visited = 0

    while stack and not found:
        if visited >= _TREE_MAX_NODES:
            bounded = True
            break
        path, depth = stack.pop()
        nodes = _tree_level(credential_id, path)
        if nodes is None:
            errored = True
            continue
        level_has_leaf = False
        for node in nodes:
            if visited >= _TREE_MAX_NODES:
                bounded = True
                break
            visited += 1
            segment = node.get("path") or node.get("id") or node.get("name")
            name = node.get("name") or node.get("id")
            node_type = node.get("type")
            has_children = bool(node.get("has_children"))
            if isinstance(name, str):
                names.append(name)
                if name.lower() == target.lower() and (
                    not has_children or (isinstance(node_type, str) and node_type.lower() in _TABLE_NODE_TYPES)
                ):
                    found = True
                    break
            is_leaf = (not has_children) or (
                isinstance(node_type, str) and node_type.lower() in _TABLE_NODE_TYPES
            )
            if is_leaf:
                level_has_leaf = True
            elif isinstance(segment, str):
                if depth >= _TREE_MAX_DEPTH:
                    bounded = True
                else:
                    child_path = segment if path is None else f"{path}.{segment}"
                    stack.append((child_path, depth + 1))
        if level_has_leaf:
            reached_leaf_level = True

    complete = found or (reached_leaf_level and not errored and not bounded)
    return names, complete


def _sql_ident_ok(value: str) -> bool:
    """Reject identifiers we can't safely inline into a probe SQL literal.

    The probe `sample` action takes a raw query string with no bind-param
    support, so schema/table names are string-interpolated. A name carrying a
    quote/backslash/NUL could break out of the literal; rather than escape it
    we bail (the caller degrades to the inconclusive warn), so a weird name can
    never produce a malformed query that we'd misread as a confirmed miss.
    """
    return bool(value) and not any(c in value for c in "'\"\\;\x00\n\r")


def _catalog_count(samples: object) -> int | None:
    """Pull the single ``count(*)`` integer out of a `sample` response's rows.

    The count query aliases the column ``n``, but warehouses fold unquoted
    identifiers to different cases: Postgres returns the key ``n``, Snowflake
    returns ``N``. So the key is matched case-insensitively. A clean count is a
    list of exactly one row carrying one integer under an ``n``-ish key;
    anything else (error envelope, unexpected shape) yields ``None``.
    """
    if not isinstance(samples, list) or len(samples) != 1 or not isinstance(samples[0], dict):
        return None
    for key, val in samples[0].items():
        if isinstance(key, str) and key.lower() == "n" and isinstance(val, int):
            return val
    return None


def _catalog_table_present(credential_id: int, table: str, config: dict[str, Any]) -> bool | None:
    """Conclusive catalog existence check via `probe --action sample`.

    Returns ``True`` (table present), ``False`` (confirmed absent), or ``None``
    (inconclusive).

    The signal is a ``select count(*) as n from information_schema.tables``
    probe. ``information_schema`` is ANSI-standard and portable -- it works on
    Snowflake, Postgres/Supabase, Redshift, MySQL, and other SQL warehouses --
    unlike a dialect-specific catalog like ``pg_tables``. The comparison is
    ``upper(...) = upper(...)`` folded on BOTH sides so a caller's lowercase
    ``bird_classification`` matches Snowflake's uppercase-folded catalog entry
    ``BIRD_CLASSIFICATION`` (and vice-versa on lower-folding dialects).

    A ``count(*)`` always returns exactly one row when it executes: ``n >= 1``
    (present) or ``n == 0`` (absent). Anything that isn't that clean single-int
    row -- a permission/syntax/connection error (which comes back as
    ``sample_format: "unknown"`` + ``raw_response_excerpt``/``errorMessage``),
    an exception, ``ok`` not true, or an unexpected shape -- yields ``None``.
    A ``None`` (inconclusive) result is treated as advisory-only by the caller
    (warn + proceed); only a cleanly executed catalog query can produce the
    ``False`` that the caller escalates to a hard-fail.
    """
    # DB/warehouse sink config carries `table` (+ optional `schema`); honour a
    # schema-qualified `schema.table` too. If no schema is known we search all
    # schemas the role can see (still conclusive: absent everywhere -> absent).
    schema: str | None = None
    tbl = table
    if "." in table:
        schema, _, tbl = table.partition(".")
    cfg_schema = config.get("schema")
    if isinstance(cfg_schema, str) and cfg_schema:
        schema = cfg_schema
    if not _sql_ident_ok(tbl):
        return None
    where = f"upper(table_name) = upper('{tbl}')"
    if schema:
        if not _sql_ident_ok(schema):
            return None
        where += f" and upper(table_schema) = upper('{schema}')"
    query = f"select count(*) as n from information_schema.tables where {where}"
    try:
        resp = client.request(
            "POST",
            "/nexla/probe",
            json={
                "action": "sample",
                "credential_id": credential_id,
                "params": {"db_query_mode": "Query", "query": query},
            },
        )
    except CliError:
        return None
    if not isinstance(resp, dict) or resp.get("ok") is not True:
        return None
    n = _catalog_count(resp.get("samples"))
    if n is None:
        return None
    return n >= 1


def check_table_exists(credential_id: int, connector: str, config: object) -> None:
    """Pre-flight for DB/warehouse sinks: warn or hard-fail if the target table is missing.

    Probes the credential's tree hierarchically (same surface as
    `nexla-cli probe run --action tree`) and looks for the configured ``table``
    name among the returned nodes. Only a *confirmed* miss -- the tree was
    fully enumerated down to a real table level without error and the table
    genuinely isn't there -- raises before the real `sinks create` call
    fires. Any failure or ambiguity (probe unsupported, incomplete/empty
    tree, non-DB connector, no ``table`` config key) degrades to a no-op or
    a stderr warning; it never blocks on an inconclusive probe.
    """
    if not _connector_is_db(connector) or not isinstance(config, dict):
        return
    table = config.get("table")
    if not isinstance(table, str) or not table:
        return

    names, complete = _probe_tree_names(credential_id, table)
    lowered = {n.lower() for n in names}
    if table.lower() in lowered:
        return
    if not complete:
        # Tree walk was inconclusive (the connector's tree is blind to tables,
        # as on Snowflake/Supabase). Consult the portable, ANSI-standard
        # `information_schema.tables` catalog via a `sample` count query. This
        # is now CONCLUSIVE, not merely advisory:
        #   True  -> table present  -> proceed silently.
        #   False -> catalog queried cleanly and the table is genuinely absent
        #            -> hard-fail, the same exit-2 path as a conclusive
        #            tree-miss (BigQuery). This is the new catch that turns a
        #            typo'd Snowflake table from a warn-and-stall into a
        #            pre-flight failure.
        #   None  -> the catalog query errored / was unqueryable / the role
        #            lacks catalog visibility -> inconclusive -> generic WARN +
        #            proceed. Only a cleanly executed count can hard-fail, so a
        #            connector where information_schema isn't reachable can
        #            never be falsely blocked.
        verdict = _catalog_table_present(credential_id, table, config)
        if verdict is True:
            return
        if verdict is False:
            raise CliError(
                EXIT.VALIDATION,
                f"table '{table}' not found via `nexla-cli probe run --action sample "
                f"--credential-id {credential_id}` (information_schema.tables reports "
                "no such table). DB/warehouse sinks do not auto-create the "
                "destination table -- create it first (matching the nexset's "
                "output_schema columns) or pass --skip-table-check if this "
                "connector's catalog is unreliable.",
            )
        typer.echo(
            f"WARNING: could not conclusively verify table '{table}' exists "
            f"(tried `nexla-cli probe run --action tree --credential-id {credential_id}` "
            "then an information_schema.tables catalog query; the probes errored or "
            "returned an incomplete/ambiguous view). DB/warehouse sinks do not "
            "auto-create the destination table -- confirm it exists before this sink "
            "runs, or it will activate fine and then stall in runtime_status: "
            "PROCESSING with no visible error.",
            err=True,
        )
        return
    raise CliError(
        EXIT.VALIDATION,
        f"table '{table}' not found via `nexla-cli probe run --action tree "
        f"--credential-id {credential_id}`. Create it first (matching the "
        "nexset's output_schema columns) or pass --skip-table-check if this "
        "connector's tree probe is unreliable.",
    )
