from __future__ import annotations

import json as jsonlib

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def jsonlib_loads(content: bytes) -> object:
    return jsonlib.loads(content)


def test_list(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": 1, "name": "sink1", "status": "ACTIVE"}], "page": 1, "per_page": 50},
        )
    )
    result = runner.invoke(cli_app, ["sinks", "list"])
    assert result.exit_code == 0
    assert route.calls.last.request.url.path == "/nexla/sinks"
    assert "sink1" in result.stdout


def test_get(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/sinks/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "sink1"})
    )
    result = runner.invoke(cli_app, ["sinks", "get", "1"])
    assert result.exit_code == 0
    assert route.called


def test_get_wait_until_exact_match(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setattr("nexla_cli.poll.time.sleep", lambda s: None)
    route = respx_mock.get(f"{BASE_URL}/nexla/sinks/1").mock(
        side_effect=[
            httpx.Response(200, json={"id": 1, "runtime_status": "IDLE"}),
            httpx.Response(200, json={"id": 1, "runtime_status": "ACTIVE"}),
        ]
    )
    result = runner.invoke(
        cli_app,
        ["sinks", "get", "1", "--wait-until", "runtime_status=ACTIVE", "--wait-interval", "0"],
    )
    assert result.exit_code == 0
    assert route.call_count == 2


def test_create(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    # `create` always runs the table pre-flight, which first asks the connector
    # describe endpoint for the kind — mock it (s3 is a file connector, not a
    # DB, so the pre-flight then skips the tree probe entirely).
    _mock_describe_kind(respx_mock, "s3", "file")
    route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(
        cli_app,
        [
            "sinks",
            "create",
            "--name",
            "new-sink",
            "--nexset-id",
            "10",
            "--credential-id",
            "20",
            "--connector",
            "s3",
        ],
    )
    assert result.exit_code == 0
    assert route.called


def test_update(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.patch(f"{BASE_URL}/nexla/sinks/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "renamed"})
    )
    result = runner.invoke(cli_app, ["sinks", "update", "1", "--name", "renamed"])
    assert result.exit_code == 0
    assert route.called


def test_activate(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/sinks/1/activate").mock(
        return_value=httpx.Response(200, json={"id": 1, "status": "ACTIVE"})
    )
    result = runner.invoke(cli_app, ["sinks", "activate", "1"])
    assert result.exit_code == 0
    assert route.called


def test_pause(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/sinks/1/pause").mock(
        return_value=httpx.Response(200, json={"id": 1, "status": "PAUSED"})
    )
    result = runner.invoke(cli_app, ["sinks", "pause", "1"])
    assert result.exit_code == 0
    assert route.called


def test_delete(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.delete(f"{BASE_URL}/nexla/sinks/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["sinks", "delete", "1"])
    assert result.exit_code == 0
    assert route.called
    assert "deleted" in result.stdout and "true" in result.stdout


def test_delete_force_pauses_first(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # --force pauses before deleting (the API refuses to delete an active sink).
    pause = respx_mock.post(f"{BASE_URL}/nexla/sinks/1/pause").mock(
        return_value=httpx.Response(200, json={"id": 1, "status": "PAUSED"})
    )
    delete = respx_mock.delete(f"{BASE_URL}/nexla/sinks/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["sinks", "delete", "1", "--force"])
    assert result.exit_code == 0
    assert pause.called and delete.called
    assert "deleted" in result.stdout


def test_delete_without_force_does_not_pause(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    pause = respx_mock.post(f"{BASE_URL}/nexla/sinks/1/pause").mock(
        return_value=httpx.Response(200, json={})
    )
    respx_mock.delete(f"{BASE_URL}/nexla/sinks/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["sinks", "delete", "1"])
    assert result.exit_code == 0
    assert not pause.called


def test_delete_force_dry_run_fires_nothing(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    """--dry-run -> no DELETE, and no pause either."""
    monkeypatch.setattr("nexla_cli.dryrun.openapi_client.fetch_openapi", lambda: {"paths": {}})
    monkeypatch.setattr(
        "nexla_cli.dryrun.openapi_client.resolve",
        lambda spec, resource, verb: {"operation": {}},
    )
    monkeypatch.setattr(
        "nexla_cli.dryrun.openapi_client.request_body_schema", lambda spec, op: None
    )
    pause = respx_mock.post(f"{BASE_URL}/nexla/sinks/1/pause").mock(
        return_value=httpx.Response(200, json={})
    )
    delete = respx_mock.delete(f"{BASE_URL}/nexla/sinks/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["sinks", "delete", "1", "--force", "--dry-run"])
    assert result.exit_code == 0
    assert not pause.called
    assert not delete.called


def test_upstream_500_maps_to_exit_6(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/nexla/sinks/1").mock(return_value=httpx.Response(500, text="boom"))
    result = runner.invoke(cli_app, ["sinks", "get", "1"])
    assert result.exit_code == 6


def _create_db_sink_args(
    connector: str = "postgres", table: str = "orders", extra: list[str] | None = None
) -> list[str]:
    return [
        "sinks",
        "create",
        "--name",
        "new-sink",
        "--nexset-id",
        "10",
        "--credential-id",
        "20",
        "--connector",
        connector,
        "--config",
        jsonlib.dumps({"table": table}),
        *(extra or []),
    ]


def _mock_describe_kind(respx_mock: respx.MockRouter, connector: str, kind: str) -> None:
    """Mock the `connectors describe` metadata call `_connector_is_db` makes."""
    respx_mock.get(f"{BASE_URL}/nexla/connectors/describe/{connector}").mock(
        return_value=httpx.Response(200, json={"name": connector, "kind": kind})
    )


def _probe_tree_side_effect(tree_by_path: dict[str, object]):
    """Build a respx side_effect that serves a realistic *hierarchical* tree.

    ``tree_by_path`` maps a requested ``params.path`` (or ``"__root__"`` for
    the initial ``params={}`` call) to the node list for that level. Any
    path not present resolves to an empty level -- mirroring the live probe,
    which returns one node list per drilled path, not a flat single call.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib_loads(request.content)
        assert isinstance(body, dict)
        path = body.get("params", {}).get("path")
        key = "__root__" if path is None else path
        nodes = tree_by_path.get(key, [])
        return httpx.Response(200, json={"ok": True, "kind": "tree", "nodes": nodes})

    return handler


# A realistic 3-level postgres tree: database -> schema -> tables. The root
# call returns only the `postgres` database node; tables only appear after
# drilling `postgres` -> `postgres.public`.
_PG_TREE_FOUND = {
    "__root__": [{"id": "postgres", "path": "postgres", "name": "postgres", "type": "database", "has_children": True}],
    "postgres": [
        {"id": "public", "path": "public", "name": "public", "type": "schema", "parent_id": "postgres", "has_children": True}
    ],
    "postgres.public": [
        {"id": "orders", "path": "orders", "name": "orders", "type": "table", "has_children": False},
        {"id": "users", "path": "users", "name": "users", "type": "table", "has_children": False},
    ],
}


def test_create_db_sink_table_confirmed_proceeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_describe_kind(respx_mock, "postgres", "db")
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_tree_side_effect(_PG_TREE_FOUND)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args())
    assert result.exit_code == 0
    assert probe_route.called
    # Hierarchical: the root probe alone can't see `orders`; it had to drill.
    drilled = {jsonlib_loads(c.request.content)["params"].get("path") for c in probe_route.calls}
    assert drilled == {None, "postgres", "postgres.public"}
    assert create_route.called


def test_create_db_sink_table_missing_hard_fails(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_describe_kind(respx_mock, "postgres", "db")
    # Fully enumerated down to the real table level -- `orders` genuinely absent.
    tree = dict(_PG_TREE_FOUND)
    tree["postgres.public"] = [
        {"id": "products", "path": "products", "name": "products", "type": "table", "has_children": False},
        {"id": "users", "path": "users", "name": "users", "type": "table", "has_children": False},
    ]
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(side_effect=_probe_tree_side_effect(tree))
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args())
    assert result.exit_code == 2
    assert not create_route.called
    assert "table 'orders' not found" in result.output


def test_create_db_sink_probe_error_warns_and_proceeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_describe_kind(respx_mock, "postgres", "db")
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(return_value=httpx.Response(500, text="boom"))
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args())
    assert result.exit_code == 0
    assert "WARNING" in result.output
    assert create_route.called


def test_create_db_sink_ambiguous_tree_warns_and_proceeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # Schema advertises children but the table level comes back empty (the
    # live supabase case): incomplete/ambiguous -> WARN + proceed, never fail.
    tree = dict(_PG_TREE_FOUND)
    tree["postgres.public"] = []
    _mock_describe_kind(respx_mock, "postgres", "db")
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(side_effect=_probe_tree_side_effect(tree))
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args())
    assert result.exit_code == 0
    assert "WARNING" in result.output
    assert create_route.called


def test_create_db_sink_node_bounded_tree_warns_and_proceeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setattr("nexla_cli.resources.preflight._TREE_MAX_NODES", 3)
    tree = dict(_PG_TREE_FOUND)
    tree["postgres.public"] = [
        {"id": "products", "path": "products", "name": "products", "type": "table", "has_children": False},
        {"id": "users", "path": "users", "name": "users", "type": "table", "has_children": False},
    ]
    _mock_describe_kind(respx_mock, "postgres", "db")
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(side_effect=_probe_tree_side_effect(tree))
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args())
    assert result.exit_code == 0
    assert "WARNING" in result.output
    assert create_route.called


def test_create_db_sink_depth_bounded_tree_warns_and_proceeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setattr("nexla_cli.resources.preflight._TREE_MAX_DEPTH", 1)
    tree = dict(_PG_TREE_FOUND)
    tree["postgres"] = [
        {"id": "public", "path": "public", "name": "public", "type": "schema", "has_children": True},
        {"id": "products", "path": "products", "name": "products", "type": "table", "has_children": False},
    ]
    _mock_describe_kind(respx_mock, "postgres", "db")
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(side_effect=_probe_tree_side_effect(tree))
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args())
    assert result.exit_code == 0
    assert "WARNING" in result.output
    assert create_route.called


def test_create_bigquery_sink_enters_check_and_proceeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # BigQuery (kind `db`) was previously absent from the name set and so
    # skipped the pre-flight entirely; kind-metadata detection now enrolls
    # it. Warehouse tree: dataset -> tables.
    bq_tree = {
        "__root__": [
            {"id": "analytics", "path": "analytics", "name": "analytics", "type": "dataset", "has_children": True}
        ],
        "analytics": [{"id": "events", "path": "events", "name": "events", "type": "table", "has_children": False}],
    }
    _mock_describe_kind(respx_mock, "bigquery", "db")
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_tree_side_effect(bq_tree)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="bigquery", table="events"))
    assert result.exit_code == 0
    assert probe_route.called
    assert create_route.called


def test_create_bigquery_sink_missing_table_hard_fails(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    bq_tree = {
        "__root__": [
            {"id": "analytics", "path": "analytics", "name": "analytics", "type": "dataset", "has_children": True}
        ],
        "analytics": [{"id": "sessions", "path": "sessions", "name": "sessions", "type": "table", "has_children": False}],
    }
    _mock_describe_kind(respx_mock, "bigquery", "db")
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(side_effect=_probe_tree_side_effect(bq_tree))
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="bigquery", table="events"))
    assert result.exit_code == 2
    assert not create_route.called
    assert "table 'events' not found" in result.output


def test_create_db_sink_skip_table_check_skips_probe(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe")
    describe_route = respx_mock.get(f"{BASE_URL}/nexla/connectors/describe/postgres")
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(extra=["--skip-table-check"]))
    assert result.exit_code == 0
    assert not probe_route.called
    assert not describe_route.called
    assert create_route.called


def test_create_non_db_connector_skips_table_check(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # s3 reports kind `file` -> not a table sink -> pre-flight is a no-op.
    _mock_describe_kind(respx_mock, "s3", "file")
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe")
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="s3"))
    assert result.exit_code == 0
    assert not probe_route.called
    assert create_route.called


def test_create_non_db_connector_falls_back_to_name_set_when_describe_fails(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # describe unavailable -> fall back to the hand-list; s3 isn't in it.
    respx_mock.get(f"{BASE_URL}/nexla/connectors/describe/s3").mock(
        return_value=httpx.Response(500, text="boom")
    )
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe")
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="s3"))
    assert result.exit_code == 0
    assert not probe_route.called
    assert create_route.called


# --- Portable information_schema catalog fallback ------------------------
# When the connector's `tree` probe is blind to tables (drills
# database->schema then returns nodes:[] -- the live Snowflake and Supabase
# behaviour), the pre-flight falls back to a portable, ANSI-standard
# `information_schema.tables` count query via `probe --action sample`. That
# fallback is now CONCLUSIVE, not advisory: a clean present result proceeds
# silently, a clean absent result HARD-FAILS (exit 2, same path as a
# conclusive tree-miss), and only an errored/unqueryable catalog degrades to a
# warn-and-proceed. The comparison is upper()-folded on both sides so a
# lowercase user table matches a warehouse's uppercase-folded catalog entry.

# A blind supabase-shaped tree: schema advertises children but the table level
# is empty, so the walk is inconclusive (complete=False) and the sample
# fallback kicks in -- mirroring the real limitation.
_PG_TREE_BLIND = {
    "__root__": [{"id": "postgres", "path": "postgres", "name": "postgres", "type": "database", "has_children": True}],
    "postgres": [{"id": "public", "path": "public", "name": "public", "type": "schema", "has_children": True}],
    "postgres.public": [],
}

# Postgres/Supabase fold the unquoted `as n` alias to lowercase `n`.
_SAMPLE_PRESENT = {"ok": True, "kind": "sample", "samples": [{"n": 1}], "sample_format": "records"}
_SAMPLE_ABSENT = {"ok": True, "kind": "sample", "samples": [{"n": 0}], "sample_format": "records"}
# Snowflake folds the same alias to UPPERCASE `N` (observed live)
# -- the count extraction must match the key case-insensitively.
_SAMPLE_PRESENT_SF = {"ok": True, "kind": "sample", "samples": [{"N": 1}], "sample_format": "records"}
_SAMPLE_ABSENT_SF = {"ok": True, "kind": "sample", "samples": [{"N": 0}], "sample_format": "records"}
# Error/permission/syntax shape: HTTP 200 envelope, sample_format unknown, the
# real error buried in raw_response_excerpt -- no clean {"n": ...} row.
_SAMPLE_ERROR = {
    "ok": True,
    "kind": "sample",
    "sample_format": "unknown",
    "raw_response_excerpt": '{"output": {"errorMessage": "ERROR: permission denied for table pg_tables", "statusCode": 500}}',
}


def _probe_dispatch(tree_by_path: dict[str, object], sample_response: object):
    """respx side_effect serving `tree` calls from ``tree_by_path`` and any
    `sample` call with ``sample_response`` (dispatched on the body's action)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib_loads(request.content)
        assert isinstance(body, dict)
        if body.get("action") == "sample":
            return httpx.Response(200, json=sample_response)
        path = body.get("params", {}).get("path")
        key = "__root__" if path is None else path
        return httpx.Response(200, json={"ok": True, "kind": "tree", "nodes": tree_by_path.get(key, [])})

    return handler


def _probe_actions(route: respx.Route) -> list[object]:
    return [jsonlib_loads(c.request.content).get("action") for c in route.calls]


def test_create_pg_sink_sample_present_suppresses_warning(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # tree blind -> sample count returns {"n": 1} -> table present -> proceed
    # silently (no warning).
    _mock_describe_kind(respx_mock, "supabase", "db")
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_dispatch(_PG_TREE_BLIND, _SAMPLE_PRESENT)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="supabase", table="orders"))
    assert result.exit_code == 0
    assert "WARNING" not in result.output
    assert create_route.called
    # The fallback sample probe was a portable information_schema count with a
    # case-folded comparison for `orders`.
    sample_calls = [c for c in probe_route.calls if jsonlib_loads(c.request.content).get("action") == "sample"]
    assert len(sample_calls) == 1
    query = jsonlib_loads(sample_calls[0].request.content)["params"]["query"]
    assert "information_schema.tables" in query
    assert "upper(table_name) = upper('orders')" in query


def test_create_pg_sink_catalog_absent_hard_fails(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # tree blind -> information_schema count returns {"n": 0} -> catalog was
    # queried cleanly and the table is genuinely absent -> HARD-FAIL (exit 2),
    # create never fires. This is the new conclusive catch.
    _mock_describe_kind(respx_mock, "supabase", "db")
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_dispatch(_PG_TREE_BLIND, _SAMPLE_ABSENT)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="supabase", table="orders"))
    assert result.exit_code == 2
    assert not create_route.called
    assert "table 'orders' not found" in result.output
    assert "information_schema.tables reports no such table" in result.output


def test_create_pg_sink_sample_error_warns_and_proceeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # tree blind -> sample errors (permission/syntax: unknown format, no clean
    # count row) -> inconclusive -> generic WARN and proceed.
    _mock_describe_kind(respx_mock, "supabase", "db")
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_dispatch(_PG_TREE_BLIND, _SAMPLE_ERROR)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="supabase", table="orders"))
    assert result.exit_code == 0
    assert create_route.called
    assert "WARNING" in result.output
    assert "could not conclusively verify" in result.output


def test_create_bigquery_conclusive_tree_resolves_without_sample(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # BigQuery's tree DOES enumerate (dataset -> table), so a found table is
    # resolved by the tree walk alone. The sample fallback only exists for
    # tree-blind connectors, so it must never fire when the tree is conclusive:
    # here `events` is present at a real table level -> proceed, zero `sample`
    # probes. (There is no dialect allow-list any more; the guarantee is
    # "conclusive tree needs no sample", not "bigquery is excluded".)
    bq_tree = {
        "__root__": [{"id": "analytics", "path": "analytics", "name": "analytics", "type": "dataset", "has_children": True}],
        "analytics": [{"id": "events", "path": "analytics.events", "name": "events", "type": "table", "has_children": False}],
    }
    _mock_describe_kind(respx_mock, "bigquery", "db")
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_dispatch(bq_tree, _SAMPLE_ABSENT)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="bigquery", table="events"))
    assert result.exit_code == 0
    assert create_route.called
    assert "WARNING" not in result.output
    assert "sample" not in _probe_actions(probe_route)
    assert "sample" not in _probe_actions(probe_route)


def test_create_non_pg_db_connector_sample_errors_and_warns(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # MySQL is kind `db`. There's no dialect allow-list: the portable
    # information_schema sample IS attempted; here it errors (modelled by
    # _SAMPLE_ERROR -> inconclusive/None), so the create proceeds with the
    # generic "could not conclusively verify" WARN. An errored catalog can
    # never hard-fail, so this stays a safe warn-and-proceed.
    _mock_describe_kind(respx_mock, "mysql", "db")
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_dispatch(_PG_TREE_BLIND, _SAMPLE_ERROR)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="mysql", table="orders"))
    assert result.exit_code == 0
    assert create_route.called
    assert "WARNING" in result.output
    # The sample WAS attempted (no allow-list gate); it just came back inconclusive.
    assert "sample" in _probe_actions(probe_route)


# The REAL Snowflake tree, captured live against a Snowflake credential
# (database NEXLA_CLI_TEST, schema PUBLIC):
#   root                     -> [{name: NEXLA_CLI_TEST, type: database, has_children: true}]
#   NEXLA_CLI_TEST           -> [{name: PUBLIC,         type: schema,   has_children: true}]
#   NEXLA_CLI_TEST.PUBLIC    -> nodes: []   (BLIND)
# The schema advertises has_children but drilling it returns an empty node
# list -- even though a real table (BIRD_CLASSIFICATION) demonstrably exists
# in it. So Snowflake's tree is BLIND: it never enumerates down to tables,
# identical in shape to the supabase case, and the walk is inconclusive
# (complete=False). The pre-flight then falls back to a portable
# information_schema.tables count query, which DOES list the table on
# Snowflake (observed live). Verified live:
#   _check_table_exists(<cred>, "snowflake", {"table": "BIRD_CLASSIFICATION",
#       "schema": "PUBLIC"}) -> proceed (present)
#   ...with "bird_classification" (lowercase) -> proceed (case-folded match)
#   ...with "no_such_table_zzz" -> hard-fail exit 2 (conclusive absent)
_SNOWFLAKE_TREE_BLIND = {
    "__root__": [
        {"id": "NEXLA_CLI_TEST", "path": "NEXLA_CLI_TEST", "name": "NEXLA_CLI_TEST", "type": "database", "has_children": True}
    ],
    "NEXLA_CLI_TEST": [
        {"id": "PUBLIC", "path": "PUBLIC", "name": "PUBLIC", "type": "schema", "parent_id": "NEXLA_CLI_TEST", "has_children": True}
    ],
    "NEXLA_CLI_TEST.PUBLIC": [],
}


def test_create_snowflake_sink_catalog_present_case_insensitive_proceeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # Snowflake (kind `db`) with its live-observed BLIND tree: database ->
    # schema -> nodes:[]. The walk never reaches a table level, so it's
    # inconclusive and the information_schema fallback fires. The user passes a
    # LOWERCASE table name; Snowflake's catalog holds the UPPERCASE
    # BIRD_CLASSIFICATION and returns the count under the uppercase key `N`
    # (_SAMPLE_PRESENT_SF). The upper()-folded compare + case-insensitive count
    # extraction resolve it to present -> proceed silently, create fires.
    _mock_describe_kind(respx_mock, "snowflake", "db")
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_dispatch(_SNOWFLAKE_TREE_BLIND, _SAMPLE_PRESENT_SF)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(
        cli_app, _create_db_sink_args(connector="snowflake", table="bird_classification")
    )
    assert result.exit_code == 0
    assert create_route.called
    assert "WARNING" not in result.output
    # The tree walk drilled all the way down to the (empty) table level first.
    tree_paths = {
        jsonlib_loads(c.request.content)["params"].get("path")
        for c in probe_route.calls
        if jsonlib_loads(c.request.content).get("action") == "tree"
    }
    assert tree_paths == {None, "NEXLA_CLI_TEST", "NEXLA_CLI_TEST.PUBLIC"}
    # The fallback fired a portable, case-folded information_schema count.
    sample_calls = [c for c in probe_route.calls if jsonlib_loads(c.request.content).get("action") == "sample"]
    assert len(sample_calls) == 1
    query = jsonlib_loads(sample_calls[0].request.content)["params"]["query"]
    assert "information_schema.tables" in query
    assert "upper(table_name) = upper('bird_classification')" in query


def test_create_snowflake_sink_catalog_absent_hard_fails(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # Blind tree -> information_schema fallback returns {"N": 0} (uppercase key,
    # real Snowflake shape) -> catalog queried cleanly, table genuinely absent
    # -> HARD-FAIL exit 2, create never fires. This is the new catch that turns
    # a typo'd Snowflake table from a warn-and-stall into a pre-flight failure.
    _mock_describe_kind(respx_mock, "snowflake", "db")
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_dispatch(_SNOWFLAKE_TREE_BLIND, _SAMPLE_ABSENT_SF)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(
        cli_app, _create_db_sink_args(connector="snowflake", table="no_such_table_zzz")
    )
    assert result.exit_code == 2
    assert not create_route.called
    assert "table 'no_such_table_zzz' not found" in result.output
    assert "information_schema.tables reports no such table" in result.output


def test_create_snowflake_sink_catalog_unqueryable_warns_and_proceeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # Blind tree -> information_schema query errors (permission/syntax: unknown
    # format, no clean count row -> inconclusive) -> generic WARN + proceed,
    # never a hard fail. This is the safety path for a connector or role where
    # the catalog isn't queryable, so the conclusive catch can't false-positive.
    _mock_describe_kind(respx_mock, "snowflake", "db")
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_dispatch(_SNOWFLAKE_TREE_BLIND, _SAMPLE_ERROR)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(
        cli_app, _create_db_sink_args(connector="snowflake", table="BIRD_CLASSIFICATION")
    )
    assert result.exit_code == 0
    assert create_route.called
    assert "WARNING" in result.output
    assert "could not conclusively verify" in result.output
    assert "sample" in _probe_actions(probe_route)


def test_create_pg_sink_unsafe_table_name_skips_sample_fallback(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # A table name carrying a quote can't be safely inlined into the probe SQL
    # literal -> the fallback bails (no sample probe) -> generic WARN, never a
    # malformed query we'd misread as a confirmed miss.
    _mock_describe_kind(respx_mock, "supabase", "db")
    probe_route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        side_effect=_probe_dispatch(_PG_TREE_BLIND, _SAMPLE_ABSENT)
    )
    create_route = respx_mock.post(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-sink"})
    )
    result = runner.invoke(cli_app, _create_db_sink_args(connector="supabase", table="ta'ble"))
    assert result.exit_code == 0
    assert create_route.called
    assert "WARNING" in result.output
    assert "sample" not in _probe_actions(probe_route)
