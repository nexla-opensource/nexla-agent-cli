"""`nexla-cli context` — consolidated flows/sources/nexsets/credentials/connectors.

Mirrors the deployed ``/nexla/*`` API. Single ``get`` command.
"""

from __future__ import annotations

import typer

from .. import client, output

app = typer.Typer(name="context", help="Fetch consolidated Nexla context.", no_args_is_help=True)


@app.command("get")
def get(ctx: typer.Context) -> None:
    """Fetch flows/credentials/sources/nexsets/catalog for @-mentions."""
    output.emit(
        client.request("GET", "/nexla/context"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )
