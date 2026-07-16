"""`nexla-cli login` — exchange a Nexla service key for a session bearer.

Not a ``resources/`` module: hits the bare API root (``POST /login``, no
``/nexla`` prefix) — matches ``routers/auth.py::LoginRequest``/``LoginResponse``.
Registered as a single top-level command, not a sub-typer group.
"""

from __future__ import annotations

import os

import typer

from . import client
from .sanitize import sanitize


def login(
    service_key: str = typer.Option(..., "--service-key", help="Nexla service key"),
    api_url: str | None = typer.Option(
        None, "--api-url", help="Override NEXLA_API_URL for this call"
    ),
) -> None:
    """Exchange a service key for a bearer token.

    Prints the access token to stdout only, so
    ``export NEXLA_TOKEN=$(nexla-cli login --service-key ...)`` works.
    Everything else (expiry, user, org) goes to stderr.
    """
    if api_url:
        os.environ["NEXLA_API_URL"] = api_url

    resp = client.request("POST", "/login", json={"service_key": service_key}, require_auth=False)
    # The token itself is never sanitized — it's a literal secret value
    # that must round-trip exactly for `export NEXLA_TOKEN=$(...)` to work.
    typer.echo(resp["access_token"])
    user = sanitize(resp["user"])
    org = sanitize(resp["org"])
    typer.echo(
        f"expires_at={resp['expires_at']} user={user['email']} org={org['name']}",
        err=True,
    )
