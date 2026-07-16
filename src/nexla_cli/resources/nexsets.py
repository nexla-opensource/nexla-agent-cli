"""`nexla-cli nexsets` — list / get / transform / activate.

No update/delete — nexsets are source-spawned or transform-derived only.
Mirrors the deployed ``/nexla/*`` API.
"""

from __future__ import annotations

import typer

from .. import client, dryrun, output, poll, validate
from ._common import DRY_RUN_OPT, JSON_OPT, PARAMS_OPT, emit_list

app = typer.Typer(name="nexsets", help="Manage Nexla nexsets.", no_args_is_help=True)

_COLUMNS = ["id", "name", "status", "flow_id", "parent_nexset_id"]



@app.command("list")
def list_(
    ctx: typer.Context,
    flow_id: int | None = typer.Option(None),
    parent_id: int | None = typer.Option(None),
    access_role: str = typer.Option("collaborator"),
    page: int = typer.Option(1),
    per_page: int = typer.Option(50),
) -> None:
    """List nexsets."""
    params: dict[str, object] = {"access_role": access_role, "page": page, "per_page": per_page}
    if flow_id is not None:
        params["flow_id"] = flow_id
    if parent_id is not None:
        params["parent_id"] = parent_id
    emit_list(ctx, "/nexla/nexsets", params, _COLUMNS, per_page)


@app.command("get")
def get(
    ctx: typer.Context,
    nexset_id: int,
    wait_until: str | None = poll.wait_until_option("samples, or output_schema"),
    wait_timeout: int = poll.WAIT_TIMEOUT_OPT,
    wait_interval: int = poll.WAIT_INTERVAL_OPT,
) -> None:
    """Get one nexset, including samples and schema. `--wait-until samples` polls until non-empty."""

    def fetch() -> object:
        return client.request("GET", f"/nexla/nexsets/{nexset_id}")

    body = poll.poll_until(fetch, wait_until, wait_timeout, wait_interval) if wait_until else fetch()
    output.emit(body, mode=output.ctx_mode(ctx), fields=output.ctx_fields(ctx))


@app.command("transform")
def transform(
    ctx: typer.Context,
    parent_id: int,
    name: str = typer.Option(...),
    language: str = typer.Option(..., help="'python' or 'sql'"),
    code: str = typer.Option(...),
    description: str | None = typer.Option(None),
    options: str | None = typer.Option(None, help="JSON object (SQL only)"),
    auto_activate: bool = typer.Option(True),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Derive a child nexset via a Python/SQL transform."""
    named: dict[str, object] = {
        "name": name,
        "description": description,
        "language": language,
        "code": code,
        "options": validate.parse_json_arg("options", options) if options is not None else None,
        "auto_activate": auto_activate,
    }
    body = validate.build_body(
        validate.commandline_named(ctx, named) if json_body is not None else named,
        json_body,
        params,
    )
    if dry_run:
        dryrun.run_dry_run(resource="nexsets", verb="transform", body=body)
    output.emit(
        client.request("POST", f"/nexla/nexsets/{parent_id}/transform", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("activate")
def activate(ctx: typer.Context, nexset_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Activate a nexset."""
    if dry_run:
        dryrun.run_dry_run(resource="nexsets", verb="activate", body={})
    output.emit(
        client.request("PUT", f"/nexla/nexsets/{nexset_id}/activate"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )
