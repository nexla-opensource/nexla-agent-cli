"""Browser SSO for `nexla-cli login --browser`: loopback PKCE (RFC 8252/7636).

The CLI runs the OAuth dance against the *identity provider* (Microsoft), then
hands the resulting id-token to Express's ``POST /auth/microsoft/login``, which
already accepts a bare ``microsoft_id_token`` -- so no server change is needed
for this flow.

Loopback (not device code) because a laptop has a browser: fewer round trips
and nothing to type. ``--device`` can be added later reusing
:func:`exchange_id_token`; the only part that differs is how the id-token is
obtained.

Public client: no secret ships in the package. PKCE is the proof, so the
``client_id`` is not sensitive -- but it also isn't guessable, so it must be
supplied (``NEXLA_OAUTH_CLIENT_ID`` / ``--client-id``) until a native app is
registered and a default can be baked in.

Stdlib only -- ``http.server``, ``secrets``, ``hashlib``, ``base64``,
``webbrowser``, ``urllib``. No new dependency.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from typing import Any

import typer

from .errors import EXIT, CliError

# Public Microsoft endpoints (the multi-tenant "common" authority). Overridable
# for single-tenant orgs via NEXLA_OAUTH_AUTHORITY.
DEFAULT_AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = "openid profile email"
# A browser round trip is human-paced; give up rather than hang a terminal.
LOOPBACK_TIMEOUT_SECONDS = 300


def _pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Serves exactly the one redirect the IdP sends back."""

    # Set by the server instance.
    result: dict[str, str]

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        # Stash only what we need; never echo the code back to the browser.
        for key in ("code", "state", "error", "error_description"):
            val = params.get(key, [""])[0]
            if val:
                self.server.result[key] = val  # type: ignore[attr-defined]
        ok = "code" in self.server.result  # type: ignore[attr-defined]
        body = (
            b"<html><body><h3>Signed in.</h3>You can close this tab and return "
            b"to the terminal.</body></html>"
            if ok
            else b"<html><body><h3>Sign-in failed.</h3>Return to the terminal for "
            b"details.</body></html>"
        )
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log -- it would pollute output."""


def _serve_one_redirect() -> tuple[http.server.HTTPServer, int]:
    """Bind an ephemeral loopback port and return ``(server, port)``.

    ``127.0.0.1`` explicitly, never ``0.0.0.0``: this port briefly accepts an
    authorization code and must not be reachable off-host.
    """
    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.result = {}  # type: ignore[attr-defined]
    return server, server.server_port


def _authorize_url(authority: str, client_id: str, redirect_uri: str, challenge: str, state: str, nonce: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{authority}/oauth2/v2.0/authorize?{query}"


def _post_form(url: str, fields: dict[str, str]) -> dict[str, Any]:
    """POST a form-encoded body and decode the JSON response (stdlib only)."""
    data = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(  # noqa: S310 - fixed https IdP endpoint
        url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            import json as jsonlib

            body = jsonlib.load(resp)
    except Exception as e:  # urllib raises a zoo of errors; all are fatal here
        raise CliError(EXIT.UPSTREAM, f"token exchange failed: {e}") from e
    if not isinstance(body, dict):
        raise CliError(EXIT.UPSTREAM, "token exchange returned an unexpected body")
    return body


def obtain_id_token(client_id: str, authority: str = DEFAULT_AUTHORITY) -> str:
    """Run the loopback PKCE flow in a browser and return the IdP id-token.

    Raises :class:`CliError` on every failure path -- never a raw socket or
    urllib exception.
    """
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)

    server, port = _serve_one_redirect()
    redirect_uri = f"http://127.0.0.1:{port}"
    url = _authorize_url(authority, client_id, redirect_uri, challenge, state, nonce)

    # Serve exactly one request, then stop -- with a hard timeout so a user who
    # never completes the browser step doesn't hang the terminal forever.
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    typer.echo("Opening your browser to sign in...", err=True)
    typer.echo(f"If it doesn't open, visit:\n{url}", err=True)
    with_browser = webbrowser.open(url)
    if not with_browser:
        typer.echo("(could not launch a browser automatically)", err=True)
    thread.join(timeout=LOOPBACK_TIMEOUT_SECONDS)
    result: dict[str, str] = server.result  # type: ignore[attr-defined]
    server.server_close()

    if thread.is_alive() or not result:
        raise CliError(
            EXIT.ERROR,
            "timed out waiting for the browser sign-in; re-run "
            "`nexla-cli login --browser`, or use a service key",
        )
    if result.get("error"):
        detail = result.get("error_description") or result["error"]
        raise CliError(EXIT.AUTH, f"sign-in failed: {detail}")
    # Verify state BEFORE touching the code (CSRF / mix-up protection).
    if not secrets.compare_digest(result.get("state", ""), state):
        raise CliError(EXIT.ERROR, "sign-in state mismatch; aborting")
    code = result.get("code")
    if not code:
        raise CliError(EXIT.AUTH, "sign-in returned no authorization code")

    body = _post_form(
        f"{authority}/oauth2/v2.0/token",
        {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "scope": SCOPES,
        },
    )
    id_token = body.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise CliError(EXIT.AUTH, "identity provider returned no id_token")
    return id_token
