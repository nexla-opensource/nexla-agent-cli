"""`nexla-cli schema [<command>]` — machine-readable command/API signatures.

Fetches the live deployed API's own ``/openapi.json`` (unauthenticated,
same call every other unauthenticated CLI call makes via
``client.request(..., require_auth=False)``) rather than importing a
Pydantic model — the standalone ``nexla-cli`` package cannot import
``express_api`` at all. Reflects whatever API version is
actually deployed at ``NEXLA_API_URL``.

**Exempt from ``--output``/``--fields``/``--page-all``**, same as
``login``: this command's whole purpose is a fixed, machine-readable JSON
document, so it always prints raw JSON via ``typer.echo(json.dumps(...))``
and never routes through ``output.emit()``.
"""

from __future__ import annotations

import json as jsonlib

import typer

from . import openapi_client
from .errors import EXIT, CliError
from .sanitize import sanitize

schema_app = typer.Typer(
    name="schema", help="Machine-readable command/API signatures.", no_args_is_help=False
)


@schema_app.callback(invoke_without_command=True)
def dump(
    command: str | None = typer.Argument(
        None, help="e.g. 'sources.create'; omit for the whole /nexla surface"
    ),
) -> None:
    """Print the live ``/nexla/*`` OpenAPI subset, or one command's signature."""
    spec = openapi_client.fetch_openapi()
    if command is None:
        paths = openapi_client.nexla_paths(spec)
        typer.echo(
            jsonlib.dumps(
                sanitize({"openapi": spec.get("openapi"), "paths": paths}), indent=2, default=str
            )
        )
        return

    resource, _, verb = command.partition(".")
    if not verb:
        raise CliError(EXIT.VALIDATION, "command must be 'resource.verb', e.g. 'sources.create'")

    match = openapi_client.resolve(spec, resource, verb)
    if match is None:
        raise CliError(EXIT.NOT_FOUND, f"no known route for '{command}'")

    body_schema = openapi_client.request_body_schema(spec, match["operation"])
    result = {
        "command": command,
        "method": match["method"],
        "path": match["path"],
        "parameters": match["operation"].get("parameters", []),
        "request_body": body_schema,
    }
    typer.echo(jsonlib.dumps(sanitize(result), indent=2, default=str))
