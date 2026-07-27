"""Human-readable table/kv rendering plus agent-facing json/ndjson output.

Deliberately kept to stdlib string formatting — no table library (plain
formatting is enough here).
"""

from __future__ import annotations

import json as jsonlib
import os
import sys
from typing import Any

import typer

from .errors import EXIT, CliError
from .sanitize import sanitize

_DEFAULT_MAX_COL_WIDTH = 40
_VALID_MODES = ("table", "json", "ndjson")


def resolve_mode(flag: str | None) -> str:
    """Resolve the active output mode: explicit flag > env > TTY autodetect.

    A user-supplied mode (via ``--output``/``-o`` or the
    ``NEXLA_OUTPUT``/``OUTPUT_FORMAT`` env vars) is validated against the
    allowed set and rejected with exit 2 rather than silently falling back
    to a table — a bogus ``-o xml`` should fail loudly, not pretend to work.
    """
    if flag:
        return _validated(flag.lower())
    env = os.environ.get("NEXLA_OUTPUT") or os.environ.get("OUTPUT_FORMAT")
    if env:
        return _validated(env.lower())
    # the whole human/agent split hinges on this one line.
    return "table" if sys.stdout.isatty() else "json"


def _validated(mode: str) -> str:
    if mode not in _VALID_MODES:
        raise CliError(
            EXIT.VALIDATION,
            f"invalid output mode {mode!r}; expected one of {', '.join(_VALID_MODES)}",
        )
    return mode


def ctx_mode(ctx: typer.Context) -> str:
    """Resolve the active output mode from the global callback's ``ctx.obj``."""
    obj = ctx.obj or {}
    return resolve_mode(obj.get("mode"))


def ctx_fields(ctx: typer.Context) -> list[str] | None:
    """Read the ``--fields`` mask stashed on ``ctx.obj`` by the global callback."""
    obj = ctx.obj or {}
    fields: list[str] | None = obj.get("fields")
    return fields


def ctx_page_all(ctx: typer.Context) -> bool:
    """Read the ``--page-all`` flag stashed on ``ctx.obj`` by the global callback."""
    obj = ctx.obj or {}
    return bool(obj.get("page_all"))


def emit_delete(
    ctx: typer.Context, resp: Any, resource_id: int, *, in_use_hint: str | None = None
) -> None:
    """Emit a ``delete`` result honoring the active output mode.

    Delete endpoints vary: some echo the resulting object (e.g. a tool the
    backend soft-paused instead of removing), others return an empty ``204``.
    Show the real body when there is one; otherwise a ``{id, deleted}``
    confirmation — never a hardcoded plain-text line that ignores ``-o json``.

    Some delete endpoints return HTTP 200 with an *error envelope* instead of
    a non-2xx when the delete is refused (e.g. a credential still in use). A
    truthy ``error`` on the body means it did NOT delete, so raise (non-zero
    exit) instead of printing the error as if it were a success. ``in_use_hint``
    lets a caller append a resource-specific next step (e.g. how to see
    what's still using it).
    """
    if isinstance(resp, dict) and resp.get("error"):
        err = resp["error"]
        detail = (err.get("detail") or err.get("error")) if isinstance(err, dict) else str(err)
        msg = f"could not delete {resource_id}: {detail or 'resource still in use'}"
        if in_use_hint:
            msg = f"{msg}. {in_use_hint}"
        raise CliError(EXIT.ERROR, msg, envelope=err if isinstance(err, dict) else None)
    emit(
        resp if isinstance(resp, dict) else {"id": resource_id, "deleted": True},
        mode=ctx_mode(ctx),
        fields=ctx_fields(ctx),
    )


def _mask(data: Any, fields: list[str]) -> Any:
    # Only keep keys that actually exist on the object. A requested field
    # that isn't present is omitted entirely rather than emitted as `null`,
    # which would mislead a caller into thinking the field exists but is
    # empty (common when the field name itself is wrong, e.g. `connector_type`
    # for the real `connector`).
    def keep(d: dict[str, Any]) -> dict[str, Any]:
        return {k: d[k] for k in fields if k in d}

    if isinstance(data, list):
        return [keep(d) if isinstance(d, dict) else d for d in data]
    if isinstance(data, dict):
        return keep(data)
    return data


def emit(
    data: Any,
    *,
    mode: str = "table",
    columns: list[str] | None = None,
    fields: list[str] | None = None,
) -> None:
    """Render ``data`` as a table/kv block (human), or json/ndjson (agent).

    List endpoints return the ``Page[T]`` envelope
    (``{items, page, per_page, next_page, truncated}``), never a bare
    array — unwrap ``items`` before branching on type or masking,
    otherwise every ``list`` command would render/mask the envelope dict
    as a single row. In ``json`` mode the envelope (with masked items
    spliced back in) is preserved so an agent can still see pagination
    metadata.

    Every value is run through :func:`nexla_cli.sanitize.sanitize` before
    rendering, in every mode — API responses are untrusted data, and an
    agent parsing JSON is exactly as exposed to a hidden zero-width
    character or an embedded ANSI escape as a human reading a table.
    """
    if data is None:
        return
    data = sanitize(data)
    envelope: dict[str, Any] | None = None
    if isinstance(data, dict) and "items" in data:
        envelope = data
        data = data["items"]
    if fields:
        data = _mask(data, fields)
        # In table mode, honor the mask as the column set too — otherwise the
        # fixed per-resource `columns` render in full with blank cells for the
        # keys the mask dropped, defeating the point of `--fields`.
        columns = fields
    if mode == "ndjson":
        for row in data if isinstance(data, list) else [data]:
            typer.echo(jsonlib.dumps(row, default=str))
    elif mode == "json":
        payload: Any = {**envelope, "items": data} if envelope is not None else data
        typer.echo(jsonlib.dumps(payload, indent=2, default=str))
    elif isinstance(data, list):
        _table(data, columns)
    else:
        _kv(data)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: width - 1] + "…"


def _table(rows: list[Any], columns: list[str] | None) -> None:
    if not rows:
        typer.echo("(no results)")
        return
    dict_rows = [r for r in rows if isinstance(r, dict)]
    if not dict_rows:
        for r in rows:
            typer.echo(_stringify(r))
        return
    cols = columns or list(dict_rows[0].keys())
    str_rows = [[_truncate(_stringify(r.get(c)), _DEFAULT_MAX_COL_WIDTH) for c in cols] for r in dict_rows]
    widths = [max(len(c), *(len(row[i]) for row in str_rows)) for i, c in enumerate(cols)]
    header = "  ".join(c.upper().ljust(widths[i]) for i, c in enumerate(cols))
    typer.echo(header)
    for row in str_rows:
        typer.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def _kv(data: Any) -> None:
    if not isinstance(data, dict):
        typer.echo(_stringify(data))
        return
    if not data:
        typer.echo("(empty)")
        return
    width = max(len(str(k)) for k in data)
    for k, v in data.items():
        typer.echo(f"{str(k).ljust(width)} : {_stringify(v)}")
