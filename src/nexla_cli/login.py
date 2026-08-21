"""`nexla-cli login` / `logout` -- session bearer lifecycle.

`login` gets a bearer from a service key or a browser approval (bare
``POST /login`` / ``POST /cli-auth/token``, no ``/nexla`` prefix -- matches
``routers/auth.py`` and ``routers/cli_auth.py``). By default it also stashes
the service key + bearer in the config file (see ``config.py``) so subsequent
commands authenticate with no ``export NEXLA_TOKEN=$(...)`` step, and so an
expired bearer can be transparently re-minted on a 401 (``client._reauth``).
`--no-store` keeps the old print-only behavior for ephemeral/CI use.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import secrets
import sys
import time
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import typer

from . import client, config, output
from .errors import EXIT, CliError
from .sanitize import sanitize

# How long to wait for the browser to redirect back to the loopback listener.
# Has to cover the full sign-in interaction if the user isn't already logged
# in to the web app -- an OAuth provider's account picker + consent screen can
# easily take a few minutes, not just "clicked a button." A passive listener
# costs nothing while it waits, so match the old device-flow design's 10
# minute budget rather than optimizing this down.
_CALLBACK_TIMEOUT_S = 600.0


def _web_base() -> str:
    """Base URL of the express web app, where the approval page lives.

    Separate from ``NEXLA_API_URL``: the approval page is served by the web
    app, the token exchange by the API, and the two are different origins in
    every deployment.
    """
    url = os.environ.get("NEXLA_WEB_URL")
    if not url:
        raise CliError(
            EXIT.CONFIG,
            "NEXLA_WEB_URL is not set -- browser login needs the web app's URL "
            "(or use `nexla-cli login --service-key <key>`)",
        )
    url = url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        # A schemeless value (e.g. "localhost:3000") makes webbrowser.open()
        # misbehave in confusing, platform-specific ways instead of just
        # failing here with a clear, actionable message.
        raise CliError(
            EXIT.CONFIG,
            f"NEXLA_WEB_URL must start with http:// or https://, got {url!r}",
        )
    return url


def _pkce_challenge(verifier: str) -> str:
    """RFC 7636 S256: base64url(sha256(verifier)), unpadded (exactly 43 chars)."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _browser_login(*, open_browser: bool) -> dict[str, Any]:
    """PKCE authorization-code flow over a loopback redirect.

    The CLI never talks to an identity provider: the express web app already
    signs users in (Google, Microsoft, email/password, service key) and
    already holds a Nexla bearer, so this borrows that instead of becoming an
    OAuth client itself. That means no IdP app registration, and it works for
    every identity type rather than just one.

    Mechanically: bind a local loopback port, send the user to an
    *authenticated* approval page carrying that port, a PKCE challenge, and a
    ``state`` value we made up. Approving mints a single-use, short-lived code
    bound to the exact approved bearer and redirects straight back here; we
    then exchange the code plus the verifier -- which never left this process
    -- for the session. A code observed in transit (browser history, a proxy
    log) is useless without the verifier.

    Same-machine only, on purpose: approval happens in a browser on the host
    running the CLI, so the redirect target can be 127.0.0.1. An earlier
    design polled instead, to also cover SSH/headless use -- but
    ``--service-key`` already covers that case, so this flow doesn't try to.
    """
    code_verifier = secrets.token_urlsafe(32)  # 43 chars, RFC 7636 minimum
    code_challenge = _pkce_challenge(code_verifier)
    state = secrets.token_urlsafe(16)

    # Port 0 -> the OS picks a free ephemeral port. Bind before opening the
    # browser: the port has to be in the URL we hand it.
    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    port = server.server_address[1]

    approve_url = f"{_web_base()}/cli-auth?port={port}&challenge={code_challenge}&state={state}"
    typer.echo(f"Approve this CLI at: {approve_url}", err=True)
    if open_browser and webbrowser.open(approve_url):
        typer.echo("Opened your browser. Waiting for approval...", err=True)
    else:
        typer.echo("Open that URL to continue. Waiting for approval...", err=True)

    deadline = time.monotonic() + _CALLBACK_TIMEOUT_S
    try:
        # Loop rather than a single handle_request(): anything else that hits
        # the ephemeral port first (a browser preflight, a port scan) gets
        # served and discarded without ending the wait.
        while getattr(server, "nexla_result", None) is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            server.timeout = remaining
            server.handle_request()
    finally:
        server.server_close()

    result: dict[str, str] | None = getattr(server, "nexla_result", None)
    if result is None:
        raise CliError(EXIT.ERROR, "timed out waiting for the browser to approve")
    if result.get("state") != state:
        # Check state before anything else in the callback is trusted.
        raise CliError(
            EXIT.ERROR, "callback state mismatch -- possible cross-site request, aborting"
        )
    if "error" in result:
        raise CliError(EXIT.AUTH, "the request was denied in the browser")
    code = result.get("code")
    if not code:
        raise CliError(EXIT.ERROR, "callback carried no authorization code")

    return _redeem(code=code, code_verifier=code_verifier)


def _redeem(*, code: str, code_verifier: str) -> dict[str, Any]:
    """Exchange the code + PKCE verifier for a session.

    ``/cli-auth/*`` is newer than some deployments; a bare 404 here would read
    as "not found" and send someone hunting for a missing flow rather than
    telling them the server simply doesn't offer browser login yet.
    """
    try:
        resp: dict[str, Any] = client.request(
            "POST",
            "/cli-auth/token",
            json={"code": code, "code_verifier": code_verifier},
            require_auth=False,
        )
    except CliError as e:
        if e.code == EXIT.NOT_FOUND:
            raise CliError(
                EXIT.CONFIG,
                "browser login isn't available on this deployment "
                "(no /cli-auth endpoint) -- use `nexla-cli login --service-key <key>`",
            ) from None
        raise
    return resp


class _CallbackHandler(BaseHTTPRequestHandler):
    """One-shot local listener for the loopback redirect.

    Stashes the parsed query params of a ``/callback`` request on the server
    instance, then hands back a small human-readable page. Anything else gets
    a 404 and is ignored, so a stray request can't be mistaken for the real
    callback. Never writes to stdout/stderr -- only ``login()``'s own messages
    do, so machine consumers of the CLI's stdout stay clean.
    """

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # silence BaseHTTPRequestHandler's default stderr access log

    def do_GET(self) -> None:  # noqa: N802 - name required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        query = parse_qs(parsed.query)
        self.server.nexla_result = {k: v[0] for k, v in query.items()}  # type: ignore[attr-defined]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><p>Signed in. You can close this tab and "
            b"return to your terminal.</p></body></html>"
        )


def _select_auth_method() -> bool:
    """gh-style menu: pick an auth method. Returns True for browser sign-in.

    Browser sign-in needs no client-side configuration -- it goes through the
    express web app's existing login -- so unlike the old IdP-based flow it is
    always offered. It does need a browser on this machine (the approval
    redirects to a loopback port); over SSH, use --service-key. All prompts go to stderr so stdout stays token-only for
    ``export NEXLA_TOKEN=$(nexla-cli login)``.
    """
    while True:
        typer.echo("How would you like to authenticate nexla-cli?", err=True)
        typer.echo("  1. Paste a service key", err=True)
        typer.echo("  2. Log in with a browser", err=True)
        choice = typer.prompt("Choose", default="1", err=True).strip().lower()
        if choice in ("1", "service key", "key", "paste"):
            return False
        if choice in ("2", "browser", "oauth", "sso"):
            return True
        typer.echo(f"invalid choice: {choice!r}", err=True)


def _stdout_is_tty() -> bool:
    """Whether stdout is a terminal (vs a pipe/redirect being captured)."""
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _tilde(path: Any) -> str:
    """Abbreviate the user's home directory, the way a shell prints it."""
    text = str(path)
    home = os.path.expanduser("~")
    return f"~{text[len(home):]}" if home != "/" and text.startswith(home) else text


def _expiry_phrase(expires_at: Any) -> str:
    """Render a unix expiry as an absolute UTC time plus a relative hint.

    A bare epoch integer tells a human nothing; `expires_at=1785419348` was
    the old output. Falls back to the raw value if it isn't a timestamp.
    """
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        return str(expires_at)
    when = datetime.fromtimestamp(expires_at, tz=UTC)
    remaining = int(expires_at - time.time())
    if remaining <= 0:
        rel = "expired"
    elif remaining < 3600:
        rel = f"in {remaining // 60}m"
    elif remaining < 86400:
        rel = f"in {remaining // 3600}h"
    else:
        rel = f"in {remaining // 86400}d"
    return f"{when:%Y-%m-%d %H:%M UTC} ({rel})"


def _drain_tty() -> None:
    """Discard input still queued on the terminal, if we're on one.

    When a multi-line paste lands in a prompt, only the first line is read --
    the rest stays in the tty buffer and, once this process exits, the shell
    reads it as commands. That turns a mis-paste into arbitrary shell
    execution, so flush the queue before bailing out. No-op when stdin isn't a
    terminal (pipes have no such buffer) or on platforms without termios.
    """
    try:
        import termios

        if sys.stdin.isatty():
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except Exception:
        # Best-effort hardening: never let the cleanup path raise.
        pass


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
        raw = str(typer.prompt("Nexla service key", hide_input=True, err=True))
    except (typer.Abort, EOFError):
        if sys.stdin.isatty():
            # A real terminal: the user deliberately hit Ctrl-C/Ctrl-D. Let it
            # reach the top-level handler, which exits quietly (130). Telling
            # them to "run in an interactive terminal" here would be nonsense.
            # Drain first: an aborted paste leaves lines the shell would run.
            _drain_tty()
            raise
        # Non-interactive with nothing on stdin: this is a misconfiguration,
        # so say what to do about it.
        raise CliError(
            EXIT.CONFIG,
            "no service key provided; pass --service-key, pipe it on stdin, "
            "or run `nexla-cli login` in an interactive terminal",
        ) from None

    # A pasted key routinely carries a trailing newline or stray spaces.
    key = raw.strip()
    if not key:
        _drain_tty()
        raise CliError(EXIT.VALIDATION, "no service key entered")
    if any(c.isspace() for c in key):
        # `hide_input` shows nothing, so a mis-paste (wrong clipboard, a whole
        # block of text) is invisible until the server rejects it -- and the
        # unread remainder then spills into the shell as commands. Reject it
        # here, and drain what's still queued on the terminal.
        _drain_tty()
        raise CliError(
            EXIT.VALIDATION,
            "that doesn't look like a service key (it contains whitespace or "
            "multiple lines) -- nothing was sent. Check what you pasted, or "
            "use `nexla-cli login --service-key <key>`.",
        )
    return key


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
        help="Authenticate in the browser instead of with a service key",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="Open the approval page automatically; --no-open just prints the URL",
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

    if browser and service_key is not None:
        # Both given is ambiguous -- say so rather than silently ignoring one.
        # (Neither is fine: that's the interactive menu.)
        raise CliError(EXIT.VALIDATION, "pass either --service-key or --browser, not both")

    if service_key is None and not browser:
        service_key = _obtain_service_key()
        browser = service_key is None  # menu picked browser sign-in

    if browser:
        resp = _browser_login(open_browser=open_browser)
    else:
        resp = client.request(
            "POST", "/login", json={"service_key": service_key}, require_auth=False
        )
    user = sanitize(resp["user"])
    org = sanitize(resp["org"])

    # Print the raw bearer only when stdout is being captured (a pipe or
    # redirect), which is exactly the `export NEXLA_TOKEN=$(nexla-cli login
    # ...)` case -- command substitution gives us a pipe, never a tty. On a
    # real terminal, dumping a JWT just parks a live secret in the user's
    # scrollback for no benefit, since it was persisted anyway. `--no-store`
    # is the exception: nothing is saved, so the token IS the deliverable.
    show_token = no_store or not _stdout_is_tty()
    if show_token:
        # Never sanitized -- a literal secret that must round-trip exactly.
        typer.echo(resp["access_token"])
        typer.echo(
            f"expires_at={resp['expires_at']} user={user['email']} org={org['name']}",
            err=True,
        )
    else:
        typer.echo(f"Logged in as {user['email']} ({org['name']})", err=True)
        typer.echo(f"  expires  {_expiry_phrase(resp.get('expires_at'))}", err=True)

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
        if show_token:
            typer.echo(f"credentials stored at {saved} (use --no-store to skip)", err=True)
        else:
            typer.echo(f"  stored   {_tilde(saved)}", err=True)
            typer.echo(
                "  token    kept in the config file; `nexla-cli whoami` shows the session",
                err=True,
            )


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
