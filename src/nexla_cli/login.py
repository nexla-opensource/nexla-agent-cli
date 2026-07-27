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
from typing import Any

import typer

from . import client, config, oauth, output
from .errors import EXIT, CliError
from .sanitize import sanitize


def _oauth_client_id() -> str | None:
    """The CLI's public OAuth client_id, or None if none is configured.

    Not a secret (PKCE is the proof), but not guessable either, so it has to be
    supplied until a native app is registered and a default can ship.
    """
    return os.environ.get("NEXLA_OAUTH_CLIENT_ID") or None


def _browser_login() -> dict[str, Any]:
    """Loopback PKCE against the IdP, then exchange the id-token for a bearer.

    Express's ``/auth/microsoft/login`` accepts a bare ``microsoft_id_token``
    and returns the same ``LoginResponse`` as ``/login``, so the whole
    persistence path downstream is unchanged.
    """
    client_id = _oauth_client_id()
    if client_id is None:
        raise CliError(
            EXIT.CONFIG,
            "browser sign-in needs an OAuth client id: set NEXLA_OAUTH_CLIENT_ID "
            "(a registered public/native app), or authenticate with --service-key",
        )
    authority = os.environ.get("NEXLA_OAUTH_AUTHORITY") or oauth.DEFAULT_AUTHORITY
    id_token = oauth.obtain_id_token(client_id, authority=authority)
    resp = client.request(
        "POST",
        "/auth/microsoft/login",
        json={"microsoft_id_token": id_token},
        require_auth=False,
    )
    if not isinstance(resp, dict) or not resp.get("access_token"):
        raise CliError(EXIT.AUTH, "sign-in succeeded but no access token was returned")
    return resp


def _select_auth_method() -> bool:
    """gh-style menu: pick an auth method. Returns True for browser sign-in.

    Browser sign-in is only offered when a public ``client_id`` is configured
    (``NEXLA_OAUTH_CLIENT_ID``); until a native app is registered there is
    nothing to authorize against, so the option is shown as unavailable rather
    than failing after the fact. All prompts go to stderr so stdout stays
    token-only for ``export NEXLA_TOKEN=$(nexla-cli login)``.
    """
    browser_ready = _oauth_client_id() is not None
    while True:
        typer.echo("How would you like to authenticate nexla-cli?", err=True)
        typer.echo("  1. Paste a service key", err=True)
        typer.echo(
            "  2. Log in with a browser"
            + ("" if browser_ready else " [unavailable: NEXLA_OAUTH_CLIENT_ID not set]"),
            err=True,
        )
        choice = typer.prompt("Choose", default="1", err=True).strip().lower()
        if choice in ("1", "service key", "key", "paste"):
            return False
        if choice in ("2", "browser", "oauth", "sso"):
            if browser_ready:
                return True
            typer.echo(
                "Browser sign-in needs a registered OAuth client: set "
                "NEXLA_OAUTH_CLIENT_ID (or use a service key).",
                err=True,
            )
            continue
        typer.echo(f"invalid choice: {choice!r}", err=True)


def _obtain_service_key() -> str | None:
    """Interactive credential entry. Returns the key, or None for browser SSO.

    On a TTY the gh-style method menu runs first; picking browser sign-in
    returns None so the caller runs the OAuth flow instead. Non-TTY (piped/CI)
    skips the menu and reads the key from stdin, so
    `echo $KEY | nexla-cli login` still works.
    """
    if sys.stdin.isatty() and _select_auth_method():
        return None
    try:
        return str(typer.prompt("Nexla service key", hide_input=True, err=True))
    except (typer.Abort, EOFError):
        if sys.stdin.isatty():
            # A real terminal: the user deliberately hit Ctrl-C/Ctrl-D. Let it
            # reach the top-level handler, which exits quietly (130). Telling
            # them to "run in an interactive terminal" here would be nonsense.
            raise
        # Non-interactive with nothing on stdin: this is a misconfiguration,
        # so say what to do about it.
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
    browser: bool = typer.Option(
        False,
        "--browser",
        help="Sign in through the browser (OAuth loopback PKCE) instead of a service key",
    ),
    no_store: bool = typer.Option(
        False,
        "--no-store",
        help="Don't persist credentials to the config file (print token only)",
    ),
) -> None:
    """Exchange a service key -- or a browser sign-in -- for a bearer token.

    Prints the access token to stdout (so ``export NEXLA_TOKEN=$(nexla-cli
    login --service-key ...)`` still works); everything else (expiry, user,
    org, where credentials were stored) goes to stderr. Unless ``--no-store``,
    the bearer is saved to the config file so future commands need no env var.
    """
    if api_url:
        os.environ["NEXLA_API_URL"] = api_url

    if service_key is None and not browser:
        service_key = _obtain_service_key()
        browser = service_key is None  # menu picked browser sign-in

    if browser:
        resp = _browser_login()
    else:
        resp = client.request(
            "POST", "/login", json={"service_key": service_key}, require_auth=False
        )
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
