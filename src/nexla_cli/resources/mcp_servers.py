"""`nexla-cli mcp-servers` — external MCP servers nested under a toolset.

Mirrors the deployed ``/nexla/*`` API
(``/nexla/toolsets/{toolset_id}/mcp-servers/*``). No update — attach again
with a new name or detach + reattach.
"""

from __future__ import annotations

import typer

from .. import client, dryrun, output, validate
from ._common import DRY_RUN_OPT, JSON_OPT, PARAMS_OPT

app = typer.Typer(
    name="mcp-servers", help="Manage external MCP servers on a toolset's gateway.", no_args_is_help=True
)

_COLUMNS = ["id", "toolset_id", "server_name", "server_url", "status", "tool_count"]



@app.command("list")
def list_(ctx: typer.Context, toolset_id: int) -> None:
    """List MCP servers on a toolset."""
    # No page/per_page on this endpoint — always a single response, not a
    # Page[T] envelope, so --page-all does not apply here.
    output.emit(
        client.request("GET", f"/nexla/toolsets/{toolset_id}/mcp-servers"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
        columns=_COLUMNS,
    )


@app.command("attach")
def attach(
    ctx: typer.Context,
    toolset_id: int,
    server_name: str = typer.Option(...),
    server_url: str = typer.Option(...),
    server_description: str | None = typer.Option(None),
    auth_type: str | None = typer.Option(None, help="'bearer' | 'basic' | 'headers' | 'none'"),
    auth_value: str | None = typer.Option(
        None, help="Bearer/basic token string, or JSON object for 'headers'"
    ),
    tool_filter: str | None = typer.Option(None, help="JSON object {mode, tool_names, patterns}"),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Attach an external MCP server to a toolset."""
    named: dict[str, object] = {
        "server_name": server_name,
        "server_description": server_description,
        "server_url": server_url,
    }
    if auth_type is not None:
        value: object = auth_value
        if auth_type == "headers" and auth_value is not None:
            value = validate.parse_json_arg("auth-value", auth_value)
        named["auth"] = {"type": auth_type, "value": value}
    if tool_filter is not None:
        named["tool_filter"] = validate.parse_json_arg("tool-filter", tool_filter)
    body = validate.build_body(
        validate.commandline_named(ctx, named) if json_body is not None else named,
        json_body,
        params,
    )
    if dry_run:
        dryrun.run_dry_run(resource="mcp-servers", verb="attach", body=body)
    output.emit(
        client.request("POST", f"/nexla/toolsets/{toolset_id}/mcp-servers", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("sync")
def sync(ctx: typer.Context, toolset_id: int, server_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Trigger discovery/indexing on an attached MCP server."""
    if dry_run:
        dryrun.run_dry_run(resource="mcp-servers", verb="sync", body={})
    output.emit(
        client.request("POST", f"/nexla/toolsets/{toolset_id}/mcp-servers/{server_id}/sync"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("detach")
def detach(toolset_id: int, server_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Detach an MCP server from a toolset."""
    if dry_run:
        dryrun.run_dry_run(resource="mcp-servers", verb="detach", body={})
    client.request("DELETE", f"/nexla/toolsets/{toolset_id}/mcp-servers/{server_id}")
    typer.echo(f"detached mcp server {server_id} from toolset {toolset_id}")
