"""`nexla-cli credentials` — list / get / create / update / delete.

Mirrors the deployed ``/nexla/*`` API.
"""

from __future__ import annotations

import typer

from .. import client, dryrun, output, validate
from ._common import DRY_RUN_OPT, JSON_OPT, PARAMS_OPT, emit_list

app = typer.Typer(name="credentials", help="Manage Nexla credentials.", no_args_is_help=True)

_COLUMNS = ["id", "name", "connector", "kind", "auth_mode"]



@app.command("list")
def list_(
    ctx: typer.Context,
    connector: str | None = typer.Option(None),
    kind: str | None = typer.Option(None),
    access_role: str = typer.Option("collaborator"),
    page: int = typer.Option(1),
    per_page: int = typer.Option(50),
) -> None:
    """List credentials."""
    params: dict[str, object] = {"access_role": access_role, "page": page, "per_page": per_page}
    if connector is not None:
        params["connector"] = connector
    if kind is not None:
        params["kind"] = kind
    emit_list(ctx, "/nexla/credentials", params, _COLUMNS, per_page)


@app.command("get")
def get(ctx: typer.Context, credential_id: int) -> None:
    """Get one credential by id."""
    output.emit(
        client.request("GET", f"/nexla/credentials/{credential_id}"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("create")
def create(
    ctx: typer.Context,
    name: str = typer.Option(...),
    connector: str = typer.Option(...),
    description: str | None = typer.Option(None),
    auth_mode: str | None = typer.Option(None),
    config: str = typer.Option("{}", help="JSON object of connector-specific fields"),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Create a credential."""
    named: dict[str, object] = {
        "name": name,
        "connector": connector,
        "description": description,
        "auth_mode": auth_mode,
        "config": validate.parse_json_arg("config", config) if config != "{}" else None,
    }
    body = validate.build_body(
        validate.commandline_named(ctx, named) if json_body is not None else named,
        json_body,
        params,
    )
    if dry_run:
        dryrun.run_dry_run(resource="credentials", verb="create", body=body)
    output.emit(
        client.request("POST", "/nexla/credentials", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("update")
def update(
    ctx: typer.Context,
    credential_id: int,
    name: str | None = typer.Option(None),
    description: str | None = typer.Option(None),
    config: str | None = typer.Option(None, help="JSON object"),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Update a credential."""
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
        dryrun.run_dry_run(resource="credentials", verb="update", body=body)
    output.emit(
        client.request("PATCH", f"/nexla/credentials/{credential_id}", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("delete")
def delete(ctx: typer.Context, credential_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Delete a credential."""
    if dry_run:
        dryrun.run_dry_run(resource="credentials", verb="delete", body={})
    output.emit_delete(
        ctx, client.request("DELETE", f"/nexla/credentials/{credential_id}"), credential_id
    )
