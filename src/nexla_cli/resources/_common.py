"""Shared building blocks for the resource command modules.

Every resource module (`sources`, `sinks`, `nexsets`, ...) exposes the same
mutating-body options and the same ``list`` output dance. Defining them once
here keeps that uniformity structural instead of copy-pasted, so a change to
the body-merge contract or the ``--page-all`` behavior lands everywhere at
once.
"""

from __future__ import annotations

from typing import Any, NoReturn

import typer

from .. import client, output
from ..errors import EXIT, CliError


def not_in_v1(feature: str) -> NoReturn:
    """Fail a not-yet-implemented command locally, without a network call.

    Some ``/nexla/*`` routes are registered upstream but always 501 in v1.
    Rather than round-trip to the server for a guaranteed 501, these
    commands are hidden from ``--help`` and raise this instead — a clear,
    offline "not in this release" signal with a stable exit code.
    """
    raise CliError(
        EXIT.ERROR,
        f"{feature} is not available in this release (planned; not implemented in v1)",
    )

# Body options shared by every create/update command. The precedence is
# named options > --params > --json (see validate.merge_body).
JSON_OPT = typer.Option(
    None,
    "--json",
    help="Raw JSON body; merged under named options, over --params. "
    "Accepts @path/to/body.json or @- to read STDIN",
)
PARAMS_OPT = typer.Option(
    [], "--params", help="key=value body overrides (repeatable); lowest precedence"
)
DRY_RUN_OPT = typer.Option(
    False,
    "--dry-run",
    help="Shallow structural lint (required fields + top-level types); fire no mutating call",
)
VERIFY_OPT = typer.Option(
    False,
    "--verify",
    help="After the write, re-GET the resource and emit that instead of the write response",
)


def emit_write(
    ctx: typer.Context,
    written: Any,
    base_path: str,
    *,
    verify: bool,
    resource_id: object = None,
) -> None:
    """Emit a create/update response — or, under ``--verify``, the read-back.

    A create/update response is whatever the mutating endpoint chose to
    echo, which is not necessarily the resource's settled server-side
    state (defaults filled in, values normalized, status still
    transitioning). ``--verify`` re-GETs the resource and emits *that*, so
    an agent gets authoritative post-write state from a single command
    instead of having to chain a second ``get`` call.

    The write has already succeeded by the time we get here, so a failing
    read-back must never turn a successful mutation into a non-zero exit:
    it warns on stderr and falls back to emitting the write response.
    ``resource_id`` is passed explicitly by ``update`` (which knows the
    id); ``create`` leaves it ``None`` and it is taken from the response.
    """
    if verify:
        rid = resource_id
        if rid is None and isinstance(written, dict):
            rid = written.get("id")
        if rid is None:
            typer.echo("warning: --verify skipped: no id in the write response", err=True)
        else:
            try:
                written = client.request("GET", f"{base_path}/{rid}")
            except Exception as e:  # noqa: BLE001 - the write succeeded; never fail on read-back
                typer.echo(f"warning: --verify read-back failed: {e}", err=True)
    output.emit(written, mode=output.ctx_mode(ctx), fields=output.ctx_fields(ctx))


def emit_list(
    ctx: typer.Context,
    path: str,
    params: dict[str, Any],
    columns: list[str],
    per_page: int,
) -> None:
    """Render a ``list`` command's output, honoring ``--page-all``.

    Under ``--page-all`` every page is streamed as NDJSON (the ``page``/
    ``per_page`` cursor keys are stripped so resource-specific filters still
    ride along); otherwise the single requested page is emitted in the
    caller's chosen mode with ``columns`` as the table header.
    """
    if output.ctx_page_all(ctx):
        filters = {k: v for k, v in params.items() if k not in ("page", "per_page")}
        for item in client.paginate(path, params=filters, per_page=per_page):
            output.emit(item, mode="ndjson", fields=output.ctx_fields(ctx))
        return
    output.emit(
        client.request("GET", path, params=params),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
        columns=columns,
    )
