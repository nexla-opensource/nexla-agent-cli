"""`nexla-cli sinks` — list / get / create / update / activate / pause / delete.

Mirrors the deployed ``/nexla/*`` API. ``update`` maps to the
router's pause→apply→reactivate ``PATCH`` cycle — the CLI just calls it,
the API hides the mechanics.
"""

from __future__ import annotations

import typer

from .. import client, dryrun, output, poll, validate
from . import preflight
from ._common import DRY_RUN_OPT, JSON_OPT, PARAMS_OPT, VERIFY_OPT, emit_list, emit_write

app = typer.Typer(name="sinks", help="Manage Nexla data sinks.", no_args_is_help=True)

_COLUMNS = ["id", "name", "status", "connector", "kind", "nexset_id", "flow_id"]

_SKIP_TABLE_CHECK_OPT = typer.Option(
    False,
    "--skip-table-check",
    help="Skip the pre-flight DB/JDBC target-table existence check",
)



@app.command("list")
def list_(
    ctx: typer.Context,
    connector: str | None = typer.Option(None),
    nexset_id: int | None = typer.Option(
        None,
        help="NOTE: accepted by the live endpoint but silently ignored (no filtering "
        "effect); server-side, don't rely on it to narrow results",
    ),
    flow_id: int | None = typer.Option(
        None,
        help="NOTE: declared in the API's OpenAPI schema but rejected by the live "
        "endpoint (exit 1, 'additional properties'); server-side mismatch, not usable today",
    ),
    access_role: str = typer.Option("collaborator"),
    page: int = typer.Option(1),
    per_page: int = typer.Option(50),
) -> None:
    """List sinks."""
    params: dict[str, object] = {"access_role": access_role, "page": page, "per_page": per_page}
    if connector is not None:
        params["connector"] = connector
    if nexset_id is not None:
        params["nexset_id"] = nexset_id
    if flow_id is not None:
        params["flow_id"] = flow_id
    emit_list(ctx, "/nexla/sinks", params, _COLUMNS, per_page)


@app.command("get")
def get(
    ctx: typer.Context,
    sink_id: int,
    wait_until: str | None = poll.wait_until_option("runtime_status=ACTIVE"),
    wait_timeout: int = poll.WAIT_TIMEOUT_OPT,
    wait_interval: int = poll.WAIT_INTERVAL_OPT,
) -> None:
    """Get one sink by id. `--wait-until runtime_status=ACTIVE` polls for a status change."""

    def fetch() -> object:
        return client.request("GET", f"/nexla/sinks/{sink_id}")

    body = poll.poll_until(fetch, wait_until, wait_timeout, wait_interval) if wait_until else fetch()
    output.emit(body, mode=output.ctx_mode(ctx), fields=output.ctx_fields(ctx))


@app.command("create")
def create(
    ctx: typer.Context,
    name: str = typer.Option(...),
    nexset_id: int = typer.Option(...),
    credential_id: int = typer.Option(...),
    connector: str = typer.Option(...),
    endpoint: str | None = typer.Option(None),
    config: str = typer.Option(
        "{}", help="JSON object of connector-specific fields; accepts @file.json or @-"
    ),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
    verify: bool = VERIFY_OPT,
    skip_table_check: bool = _SKIP_TABLE_CHECK_OPT,
) -> None:
    """Create and activate a sink."""
    named: dict[str, object] = {
        "name": name,
        "nexset_id": nexset_id,
        "credential_id": credential_id,
        "connector": connector,
        "endpoint": endpoint,
        "config": validate.parse_json_arg("config", config) if config != "{}" else None,
    }
    body = validate.build_body(
        validate.commandline_named(ctx, named) if json_body is not None else named,
        json_body,
        params,
    )
    if dry_run:
        dryrun.run_dry_run(resource="sinks", verb="create", body=body)
    if not skip_table_check:
        preflight.check_table_exists(credential_id, connector, body.get("config"))
    emit_write(
        ctx,
        client.request("POST", "/nexla/sinks", json=body),
        "/nexla/sinks",
        verify=verify,
    )


@app.command("update")
def update(
    ctx: typer.Context,
    sink_id: int,
    name: str | None = typer.Option(None),
    description: str | None = typer.Option(None),
    config: str | None = typer.Option(None, help="JSON object; accepts @file.json or @-"),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
    verify: bool = VERIFY_OPT,
) -> None:
    """Update a sink's name/description/config."""
    named: dict[str, object] = {
        "name": name,
        "description": description,
        "config": validate.parse_json_arg("config", config) if config is not None else None,
    }
    body = validate.build_body(
        validate.commandline_named(ctx, named) if json_body is not None else named,
        json_body,
        params,
    )
    if dry_run:
        dryrun.run_dry_run(resource="sinks", verb="update", body=body)
    emit_write(
        ctx,
        client.request("PATCH", f"/nexla/sinks/{sink_id}", json=body),
        "/nexla/sinks",
        verify=verify,
        resource_id=sink_id,
    )


@app.command("activate")
def activate(ctx: typer.Context, sink_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Activate a paused sink."""
    if dry_run:
        dryrun.run_dry_run(resource="sinks", verb="activate", body={})
    output.emit(
        client.request("POST", f"/nexla/sinks/{sink_id}/activate"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("pause")
def pause(ctx: typer.Context, sink_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Pause an active sink."""
    if dry_run:
        dryrun.run_dry_run(resource="sinks", verb="pause", body={})
    output.emit(
        client.request("POST", f"/nexla/sinks/{sink_id}/pause"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("delete")
def delete(ctx: typer.Context, sink_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Delete a sink."""
    if dry_run:
        dryrun.run_dry_run(resource="sinks", verb="delete", body={})
    output.emit_delete(ctx, client.request("DELETE", f"/nexla/sinks/{sink_id}"), sink_id)
