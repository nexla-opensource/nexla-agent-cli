"""`nexla-cli users` — planned, not implemented in v1.

Hidden from help; commands fail locally via `not_in_v1`.
"""

from __future__ import annotations

import typer

from ._common import not_in_v1

app = typer.Typer(name="users", help="Manage org users (not implemented in v1).", no_args_is_help=True)


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List org users. (Not implemented in v1.)"""
    not_in_v1("users list")


@app.command("get")
def get(ctx: typer.Context, user_id: int) -> None:
    """Get one user by id. (Not implemented in v1.)"""
    not_in_v1("users get")
