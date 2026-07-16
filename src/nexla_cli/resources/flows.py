"""`nexla-cli flows` — list / get / activate / pause / delete.

Mirrors the deployed ``/nexla/*`` API. No create/update — flows are
assembled implicitly from source/nexset/sink creation.
"""

from __future__ import annotations

import typer

from .. import client, dryrun, output
from ._common import DRY_RUN_OPT, emit_list

app = typer.Typer(name="flows", help="Manage Nexla flows.", no_args_is_help=True)

_COLUMNS = ["id", "name", "status", "source_connector"]



@app.command("list")
def list_(
    ctx: typer.Context,
    status_: str | None = typer.Option(None, "--status"),
    q: str | None = typer.Option(None),
    access_role: str = typer.Option("collaborator"),
    page: int = typer.Option(1),
    per_page: int = typer.Option(50),
) -> None:
    """List flows."""
    params: dict[str, object] = {"access_role": access_role, "page": page, "per_page": per_page}
    if status_ is not None:
        params["status"] = status_
    if q is not None:
        params["q"] = q
    emit_list(ctx, "/nexla/flows", params, _COLUMNS, per_page)


@app.command("get")
def get(ctx: typer.Context, flow_id: int) -> None:
    """Get one flow, including its full DAG."""
    output.emit(
        client.request("GET", f"/nexla/flows/{flow_id}"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("activate")
def activate(ctx: typer.Context, flow_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Activate a flow."""
    if dry_run:
        dryrun.run_dry_run(resource="flows", verb="activate", body={})
    output.emit(
        client.request("PUT", f"/nexla/flows/{flow_id}/activate"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("pause")
def pause(ctx: typer.Context, flow_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Pause a flow."""
    if dry_run:
        dryrun.run_dry_run(resource="flows", verb="pause", body={})
    output.emit(
        client.request("PUT", f"/nexla/flows/{flow_id}/pause"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("delete")
def delete(ctx: typer.Context, flow_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Delete a flow."""
    if dry_run:
        dryrun.run_dry_run(resource="flows", verb="delete", body={})
    output.emit_delete(ctx, client.request("DELETE", f"/nexla/flows/{flow_id}"), flow_id)
