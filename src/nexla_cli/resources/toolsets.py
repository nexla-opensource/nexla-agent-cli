"""`nexla-cli toolsets` — list / get / create / update / delete / add-nexsets.

Mirrors the deployed ``/nexla/*`` API.
"""

from __future__ import annotations

import typer

from .. import client, dryrun, output, validate
from ._common import DRY_RUN_OPT, JSON_OPT, PARAMS_OPT, emit_list

app = typer.Typer(name="toolsets", help="Manage Nexla toolsets.", no_args_is_help=True)

_COLUMNS = ["id", "name", "status", "mcp_gateway_enabled", "tool_count"]



@app.command("list")
def list_(
    ctx: typer.Context, page: int = typer.Option(1), per_page: int = typer.Option(50)
) -> None:
    """List toolsets."""
    emit_list(ctx, "/nexla/toolsets", {"page": page, "per_page": per_page}, _COLUMNS, per_page)


@app.command("get")
def get(ctx: typer.Context, toolset_id: int) -> None:
    """Get one toolset by id."""
    output.emit(
        client.request("GET", f"/nexla/toolsets/{toolset_id}"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("create")
def create(
    ctx: typer.Context,
    name: str = typer.Option(...),
    nexset_id: list[int] = typer.Option(..., help="Repeatable; at least one nexset id"),
    description: str | None = typer.Option(None),
    mcp_gateway_enabled: bool = typer.Option(False),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Create a toolset."""
    named: dict[str, object] = {
        "name": name,
        "description": description,
        "nexset_ids": list(nexset_id),
        "mcp_gateway_enabled": mcp_gateway_enabled,
    }
    body = validate.build_body(
        (
            validate.commandline_named(ctx, named, aliases={"nexset_ids": "nexset_id"})
            if json_body is not None
            else named
        ),
        json_body,
        params,
    )
    if dry_run:
        dryrun.run_dry_run(resource="toolsets", verb="create", body=body)
    output.emit(
        client.request("POST", "/nexla/toolsets", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("update")
def update(
    ctx: typer.Context,
    toolset_id: int,
    name: str | None = typer.Option(None),
    description: str | None = typer.Option(None),
    mcp_gateway_enabled: bool | None = typer.Option(None),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Update a toolset."""
    named: dict[str, object] = {
        "name": name,
        "description": description,
        "mcp_gateway_enabled": mcp_gateway_enabled,
    }
    body = validate.build_body(
        validate.commandline_named(ctx, named) if json_body is not None else named,
        json_body,
        params,
    )
    if dry_run:
        dryrun.run_dry_run(resource="toolsets", verb="update", body=body)
    output.emit(
        client.request("PATCH", f"/nexla/toolsets/{toolset_id}", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("delete")
def delete(ctx: typer.Context, toolset_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Delete a toolset."""
    if dry_run:
        dryrun.run_dry_run(resource="toolsets", verb="delete", body={})
    output.emit_delete(ctx, client.request("DELETE", f"/nexla/toolsets/{toolset_id}"), toolset_id)


@app.command("add-nexsets")
def add_nexsets(
    ctx: typer.Context,
    toolset_id: int,
    nexset_id: list[int] = typer.Option(..., help="Repeatable; at least one nexset id"),
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Add nexsets to an existing toolset."""
    body = {"nexset_ids": list(nexset_id)}
    if dry_run:
        dryrun.run_dry_run(resource="toolsets", verb="add-nexsets", body=body)
    output.emit(
        client.request("POST", f"/nexla/toolsets/{toolset_id}/nexsets", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )
