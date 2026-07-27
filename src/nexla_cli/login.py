"""`nexla-cli login` / `logout` -- session bearer lifecycle.

`login` exchanges a Nexla service key for a bearer (bare ``POST /login``, no
``/nexla`` prefix -- matches ``routers/auth.py``). By default it also stashes
the service key + bearer in the config file (see ``config.py``) so subsequent
commands authenticate with no ``export NEXLA_TOKEN=$(...)`` step, and so an
expired bearer can be transparently re-minted on a 401 (``client._reauth``).
`--no-store` keeps the old print-only behavior for ephemeral/CI use.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time

import typer

from . import client, config, output
from .errors import EXIT, CliError
from .sanitize import sanitize


def _select_auth_method() -> None:
    """gh-style menu: pick an auth method (numbered, stdlib-only, on stderr).

    Loops until the user picks an available method. Browser/OAuth is listed
    but not yet selectable -- the Nexla auth server has no device-grant
    endpoint yet (see TODO A). All prompts go to stderr so stdout stays
    token-only for ``export NEXLA_TOKEN=$(nexla-cli login)``.
    """
    while True:
        typer.echo("How would you like to authenticate nexla-cli?", err=True)
        typer.echo("  1. Paste a service key", err=True)
        typer.echo("  2. Log in with a browser (OAuth) [not yet available]", err=True)
        choice = typer.prompt("Choose", default="1", err=True).strip().lower()
        if choice in ("1", "service key", "key", "paste"):
            return
        if choice == "2":
            typer.echo(
                "Browser OAuth isn't available yet (needs server-side device "
                "grant); use a service key for now.",
                err=True,
            )
            continue
        typer.echo(f"invalid choice: {choice!r}", err=True)


def _obtain_service_key() -> str:
    """Interactive service-key entry: gh-style method menu on a TTY, then a
    hidden prompt. Non-TTY (piped/CI) skips the menu and reads the key from
    stdin, so `echo $KEY | nexla-cli login` still works."""
    if sys.stdin.isatty():
        _select_auth_method()
    try:
        return str(typer.prompt("Nexla service key", hide_input=True, err=True))
    except (typer.Abort, EOFError):
        # No TTY and nothing on stdin (or the user hit Ctrl-D/Ctrl-C): turn the
        # abort into a clean, actionable error instead of a raw traceback.
        raise CliError(
            EXIT.CONFIG,
            "no service key provided; pass --service-key, pipe it on stdin, "
            "or run `nexla-cli login` in an interactive terminal",
        ) from None


def login(
    service_key: str | None = typer.Option(
        None,
        "--service-key",
        help="Nexla service key (omit for an interactive prompt)",
    ),
    api_url: str | None = typer.Option(
        None, "--api-url", help="Override NEXLA_API_URL for this call"
    ),
    monitoring_url: str | None = typer.Option(
        None,
        "--monitoring-url",
        help="Persist the monitoring MCP URL (for `triage`) so it needs no env var",
    ),
    store_service_key: bool = typer.Option(
        False,
        "--store-service-key",
        help=(
            "Also persist the service key, so an expired session can be re-minted "
            "without re-running login. Off by default: the key is a durable secret, "
            "and the stored bearer already auto-refreshes before it expires."
        ),
    ),
    no_store: bool = typer.Option(
        False,
        "--no-store",
        help="Don't persist credentials to the config file (print token only)",
    ),
) -> None:
    """Exchange a service key for a bearer token.

    Prints the access token to stdout (so ``export NEXLA_TOKEN=$(nexla-cli
    login --service-key ...)`` still works); everything else (expiry, user,
    org, where credentials were stored) goes to stderr. Unless ``--no-store``,
    the service key + bearer are saved to the config file so future commands
    need no env var.
    """
    if api_url:
        os.environ["NEXLA_API_URL"] = api_url

    if service_key is None:
        service_key = _obtain_service_key()

    resp = client.request("POST", "/login", json={"service_key": service_key}, require_auth=False)
    # The token itself is never sanitized -- it's a literal secret value that
    # must round-trip exactly for `export NEXLA_TOKEN=$(...)` to work.
    typer.echo(resp["access_token"])
    user = sanitize(resp["user"])
    org = sanitize(resp["org"])
    typer.echo(
        f"expires_at={resp['expires_at']} user={user['email']} org={org['name']}",
        err=True,
    )

    if not no_store:
        # Store the *effective* base URL (flag > env) alongside the secret so a
        # bare `nexla-cli sources list` works afterward with no env at all.
        saved = config.save(
            api_url=client._base(),
            monitoring_url=monitoring_url,  # None -> left untouched
            # Opt-in only: a durable secret at rest is a bigger blast radius than
            # a short-lived bearer, and proactive refresh covers the normal case.
            service_key=service_key if store_service_key else None,
            access_token=resp["access_token"],
            expires_at=resp.get("expires_at"),
            user_email=user.get("email"),  # for `whoami`
            org_name=org.get("name"),
        )
        typer.echo(f"credentials stored at {saved} (use --no-store to skip)", err=True)


def logout() -> None:
    """Forget stored credentials (and invalidate the bearer server-side)."""
    # Best-effort server-side invalidation while we still hold a valid bearer;
    # never block local logout on it.
    if config.load().get("access_token") or os.environ.get("NEXLA_TOKEN"):
        # logout must always clear locally, even if the server call fails.
        with contextlib.suppress(Exception):
            client.request("POST", "/logout")
    removed = config.clear()
    typer.echo(
        "logged out; stored credentials removed"
        if removed
        else "no stored credentials to remove",
        err=True,
    )


def whoami(ctx: typer.Context) -> None:
    """Show the current authenticated identity (from env / stored config).

    Offline: reports who ``login`` last stored and where the CLI is pointed,
    without a network round-trip. ``-o json`` emits the same fields as an object.
    """
    cfg = config.load()
    token = os.environ.get("NEXLA_TOKEN") or cfg.get("access_token")
    if not token:
        raise CliError(EXIT.AUTH, "not authenticated: run `nexla-cli login` or set NEXLA_TOKEN")

    expires_at = cfg.get("expires_at")
    expired = isinstance(expires_at, (int, float)) and expires_at < time.time()
    info = {
        "authenticated": True,
        "user": cfg.get("user_email"),
        "org": cfg.get("org_name"),
        "api_url": os.environ.get("NEXLA_API_URL") or cfg.get("api_url"),
        "monitoring_url": os.environ.get("NEXLA_MONITORING_URL") or cfg.get("monitoring_url"),
        "token_source": "env" if os.environ.get("NEXLA_TOKEN") else "config",
        "expires_at": expires_at,
        "expired": expired,
    }
    output.emit(info, mode=output.ctx_mode(ctx), fields=output.ctx_fields(ctx))
