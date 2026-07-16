"""`nexla-cli tools` — list / get / set-runtime-config / clear-runtime-config / delete.

Mirrors the deployed ``/nexla/*`` API.
"""

from __future__ import annotations

import json as jsonlib

import typer

from .. import client, dryrun, output, validate
from ..errors import EXIT
from ._common import DRY_RUN_OPT, JSON_OPT, PARAMS_OPT, emit_list

app = typer.Typer(name="tools", help="Manage Nexla tools.", no_args_is_help=True)

_COLUMNS = ["id", "name", "kind", "status", "nexset_id"]



@app.command("list")
def list_(
    ctx: typer.Context, page: int = typer.Option(1), per_page: int = typer.Option(50)
) -> None:
    """List tools."""
    emit_list(ctx, "/nexla/tools", {"page": page, "per_page": per_page}, _COLUMNS, per_page)


@app.command("get")
def get(ctx: typer.Context, tool_id: int) -> None:
    """Get one tool by id."""
    output.emit(
        client.request("GET", f"/nexla/tools/{tool_id}"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("set-runtime-config")
def set_runtime_config(
    ctx: typer.Context,
    tool_id: int,
    strategy: str = typer.Option(..., help="'auto' or 'mapped'"),
    connector_name: str = typer.Option(...),
    connector_type: str = typer.Option(...),
    credential_mappings: str | None = typer.Option(
        None, help="JSON array of {user_id, credential_id}; required when strategy=mapped"
    ),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Set a tool's credential strategy."""
    named: dict[str, object] = {
        "strategy": strategy,
        "connector_name": connector_name,
        "connector_type": connector_type,
        "credential_mappings": (
            validate.parse_json_arg("credential-mappings", credential_mappings)
            if credential_mappings
            else None
        ),
    }
    body = validate.build_body(
        validate.commandline_named(ctx, named) if json_body is not None else named,
        json_body,
        params,
    )
    if dry_run:
        # Cross-field conditional the generic shallow validator can't express:
        # `credential_mappings` is only required when `strategy == "mapped"`,
        # not unconditionally -- so it can't be in the schema's flat
        # `required` list. Checked against the fully-merged body (not just
        # the named `--credential-mappings` flag) so a mapping supplied via
        # `--json`/`--params` still counts.
        if body.get("strategy") == "mapped" and body.get("credential_mappings") is None:
            typer.echo(
                jsonlib.dumps(
                    {
                        "valid": False,
                        "errors": ["credential_mappings is required when strategy=mapped"],
                    },
                    indent=2,
                ),
                err=True,
            )
            raise typer.Exit(EXIT.VALIDATION)
        dryrun.run_dry_run(resource="tools", verb="set-runtime-config", body=body)
    output.emit(
        client.request("PATCH", f"/nexla/tools/{tool_id}/runtime-config", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("clear-runtime-config")
def clear_runtime_config(ctx: typer.Context, tool_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Clear a tool's runtime config."""
    if dry_run:
        dryrun.run_dry_run(resource="tools", verb="clear-runtime-config", body={})
    output.emit(
        client.request("DELETE", f"/nexla/tools/{tool_id}/runtime-config"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("delete")
def delete(ctx: typer.Context, tool_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Delete a tool.

    The backend may not hard-delete the resource (e.g. a nexset-derived tool
    is left in a ``paused`` state instead of removed); the response body is
    emitted as-is so the caller sees the actual resulting state rather than
    an assumed "deleted" outcome.
    """
    if dry_run:
        dryrun.run_dry_run(resource="tools", verb="delete", body={})
    output.emit_delete(ctx, client.request("DELETE", f"/nexla/tools/{tool_id}"), tool_id)
