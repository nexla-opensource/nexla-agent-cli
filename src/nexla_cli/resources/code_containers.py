"""`nexla-cli code-containers` — planned, not implemented in v1.

Hidden from help; commands fail locally via `not_in_v1`.
"""

from __future__ import annotations

import typer

from ._common import not_in_v1

app = typer.Typer(name="code-containers", help="Manage Nexla code containers (not implemented in v1).", no_args_is_help=True)


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List code containers. (Not implemented in v1.)"""
    not_in_v1("code-containers list")
