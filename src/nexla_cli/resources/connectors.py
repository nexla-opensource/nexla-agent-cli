"""`nexla-cli connectors` — search + hierarchical describe.

No plain list/get — this is a describe/search-only surface. Mirrors
the deployed ``/nexla/*`` API.
"""

from __future__ import annotations

import typer

from .. import client, output, validate

app = typer.Typer(name="connectors", help="Search and describe Nexla connectors.", no_args_is_help=True)


@app.command("search")
def search(
    ctx: typer.Context,
    query: str | None = typer.Argument(None, help="Search term, e.g. 's3'"),
    kind: str | None = typer.Option(None),
    supports: str | None = typer.Option(None, help="'credential', 'source', or 'sink'"),
    include_unsupported: bool = typer.Option(False),
    limit: int = typer.Option(25),
) -> None:
    """Search the connector catalog."""
    params: dict[str, object] = {"include_unsupported": include_unsupported, "limit": limit}
    if query is not None:
        params["q"] = query
    if kind is not None:
        params["kind"] = kind
    if supports is not None:
        params["supports"] = supports
    output.emit(
        client.request("GET", "/nexla/connectors/search", params=params),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
        columns=["name", "display_name", "kind", "supported", "score"],
    )


@app.command("describe")
def describe(
    ctx: typer.Context,
    name: str,
    include: str | None = typer.Option(None, help="Comma-separated subset of credential,source,sink"),
) -> None:
    """Describe a connector's capabilities."""
    name = validate.resource_id(name)
    params: dict[str, object] = {}
    if include is not None:
        params["include"] = include
    output.emit(
        client.request("GET", f"/nexla/connectors/describe/{name}", params=params),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("describe-credential")
def describe_credential(ctx: typer.Context, name: str) -> None:
    """List a connector's auth modes."""
    name = validate.resource_id(name)
    output.emit(
        client.request("GET", f"/nexla/connectors/describe/{name}/credential"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("describe-credential-mode")
def describe_credential_mode(ctx: typer.Context, name: str, auth_mode: str) -> None:
    """Describe a specific auth mode's required fields."""
    name = validate.resource_id(name)
    auth_mode = validate.resource_id(auth_mode)
    output.emit(
        client.request("GET", f"/nexla/connectors/describe/{name}/credential/{auth_mode}"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("describe-source")
def describe_source(ctx: typer.Context, name: str) -> None:
    """Describe how to create a source for this connector."""
    name = validate.resource_id(name)
    output.emit(
        client.request("GET", f"/nexla/connectors/describe/{name}/source"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("describe-source-endpoint")
def describe_source_endpoint(ctx: typer.Context, name: str, endpoint: str) -> None:
    """Describe a specific API-connector source endpoint."""
    name = validate.resource_id(name)
    endpoint = validate.resource_id(endpoint)
    output.emit(
        client.request("GET", f"/nexla/connectors/describe/{name}/source/{endpoint}"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("describe-sink")
def describe_sink(ctx: typer.Context, name: str) -> None:
    """Describe how to create a sink for this connector."""
    name = validate.resource_id(name)
    output.emit(
        client.request("GET", f"/nexla/connectors/describe/{name}/sink"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("describe-sink-endpoint")
def describe_sink_endpoint(ctx: typer.Context, name: str, endpoint: str) -> None:
    """Describe a specific API-connector sink endpoint."""
    name = validate.resource_id(name)
    endpoint = validate.resource_id(endpoint)
    output.emit(
        client.request("GET", f"/nexla/connectors/describe/{name}/sink/{endpoint}"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )
