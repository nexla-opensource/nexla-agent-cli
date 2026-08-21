"""`login --browser` -- the express CLI-auth handoff (PKCE + loopback).

Hermetic: `/cli-auth/token` is respx-mocked and the browser launch is stubbed
with a fake that drives the CLI's own loopback listener the way the approval
page's redirect would. The fake "browser" talks `urllib`, not `httpx`, so
respx (which only patches httpx) never intercepts that local traffic.
"""

from __future__ import annotations

import json as jsonlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nexla_cli import config
from nexla_cli.errors import EXIT

from .conftest import BASE_URL

WEB_URL = "https://web.test"

_LOGIN_BODY = {
    "access_token": "tok-browser",
    "expires_at": 1234567890,
    "token_type": "Bearer",
    "user": {"id": 1, "email": "a@nexla.com"},
    "org": {"id": 2, "name": "Acme"},
}


@pytest.fixture(autouse=True)
def _headless_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexla_cli import login as login_module

    # Default: a browser that never calls back. Tests that need an approval
    # override this. The timeout is cut right down so a test that genuinely
    # never gets a callback fails in a fraction of a second, not 10 minutes.
    monkeypatch.setattr(login_module.webbrowser, "open", lambda _u: False)
    monkeypatch.setattr(login_module, "_CALLBACK_TIMEOUT_S", 5.0)
    monkeypatch.delenv("NEXLA_TOKEN", raising=False)
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_WEB_URL", WEB_URL)


def _fake_browser(*, code: str | None, error: str | None) -> Callable[[str], bool]:
    """Monkeypatch target for ``webbrowser.open``.

    Parses the port/state the CLI put in the approval URL, then -- from a
    background thread, so the main thread's blocking ``handle_request()`` has
    something to receive -- hits the CLI's own loopback callback with either a
    ``code`` (approved) or an ``error`` (denied).
    """

    def _open(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        port, state = query["port"][0], query["state"][0]

        def _hit_callback() -> None:
            params = {"state": state}
            if code is not None:
                params["code"] = code
            if error is not None:
                params["error"] = error
            urllib.request.urlopen(  # noqa: S310 - loopback only, test fixture
                f"http://127.0.0.1:{port}/callback?{urllib.parse.urlencode(params)}", timeout=5
            )

        threading.Thread(target=_hit_callback, daemon=True).start()
        return True

    return _open


def test_redeems_the_loopback_callback_and_persists(
    cli_app, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexla_cli import login as login_module

    monkeypatch.setattr(
        login_module.webbrowser, "open", _fake_browser(code="fake-code-123", error=None)
    )
    route = respx_mock.post(f"{BASE_URL}/cli-auth/token").mock(
        return_value=httpx.Response(200, json=_LOGIN_BODY)
    )

    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == 0, result.output

    sent = route.calls.last.request
    assert sent.headers.get("authorization") is None  # unauthenticated by necessity
    body = jsonlib.loads(sent.content)
    assert body["code"] == "fake-code-123"
    assert len(body["code_verifier"]) >= 43  # RFC 7636 minimum
    # Goes through the same persistence path as a service-key login.
    assert config.load()["access_token"] == "tok-browser"


def test_approval_url_carries_port_challenge_and_state(
    cli_app, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The URL is the whole contract with the approval page -- and the
    challenge must be the S256 hash of the verifier that gets redeemed, not
    just any 43 characters."""
    from nexla_cli import login as login_module

    opened: list[str] = []

    def _open(url: str) -> bool:
        opened.append(url)
        return _fake_browser(code="fake-code-123", error=None)(url)

    monkeypatch.setattr(login_module.webbrowser, "open", _open)
    route = respx_mock.post(f"{BASE_URL}/cli-auth/token").mock(
        return_value=httpx.Response(200, json=_LOGIN_BODY)
    )

    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == 0, result.output
    assert f"Approve this CLI at: {WEB_URL}/cli-auth?port=" in result.output

    query = urllib.parse.parse_qs(urllib.parse.urlparse(opened[0]).query)
    assert 1024 <= int(query["port"][0]) <= 65535
    assert len(query["state"][0]) >= 8
    verifier = jsonlib.loads(route.calls.last.request.content)["code_verifier"]
    assert query["challenge"][0] == login_module._pkce_challenge(verifier)
    assert len(query["challenge"][0]) == 43  # S256, unpadded base64url


def test_no_open_skips_the_browser(cli_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexla_cli import login as login_module

    opened: list[str] = []
    monkeypatch.setattr(login_module.webbrowser, "open", lambda u: opened.append(u) or True)
    monkeypatch.setattr(login_module, "_CALLBACK_TIMEOUT_S", 0.2)

    result = CliRunner().invoke(cli_app, ["login", "--browser", "--no-open"])
    assert result.exit_code != 0  # nothing ever approved it
    assert opened == []
    assert "Approve this CLI at:" in result.output  # the URL is still printed


def test_denial_is_reported_plainly(cli_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexla_cli import login as login_module

    monkeypatch.setattr(
        login_module.webbrowser, "open", _fake_browser(code=None, error="access_denied")
    )
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == EXIT.AUTH
    assert "denied in the browser" in result.output


def test_state_mismatch_is_rejected(cli_app, monkeypatch: pytest.MonkeyPatch) -> None:
    """A callback whose state doesn't match must not be trusted, even carrying
    a plausible-looking code."""
    from nexla_cli import login as login_module

    def _open(url: str) -> bool:
        port = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["port"][0]

        def _hit() -> None:
            urllib.request.urlopen(  # noqa: S310 - loopback only, test fixture
                f"http://127.0.0.1:{port}/callback?code=x&state=not-the-real-state", timeout=5
            )

        threading.Thread(target=_hit, daemon=True).start()
        return True

    monkeypatch.setattr(login_module.webbrowser, "open", _open)
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code != 0
    assert "state mismatch" in result.output


def test_a_stray_request_does_not_end_the_wait(
    cli_app, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anything hitting the ephemeral port that isn't /callback (a browser
    preflight, a port probe) gets served and discarded, not mistaken for the
    approval."""
    from nexla_cli import login as login_module

    def _open(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        port, state = query["port"][0], query["state"][0]

        def _hit() -> None:
            with suppress(urllib.error.HTTPError):
                urllib.request.urlopen(f"http://127.0.0.1:{port}/favicon.ico", timeout=5)  # noqa: S310
            time.sleep(0.05)
            urllib.request.urlopen(  # noqa: S310 - loopback only, test fixture
                f"http://127.0.0.1:{port}/callback?"
                f"{urllib.parse.urlencode({'code': 'real-code', 'state': state})}",
                timeout=5,
            )

        threading.Thread(target=_hit, daemon=True).start()
        return True

    monkeypatch.setattr(login_module.webbrowser, "open", _open)
    route = respx_mock.post(f"{BASE_URL}/cli-auth/token").mock(
        return_value=httpx.Response(200, json=_LOGIN_BODY)
    )

    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == 0, result.output
    assert jsonlib.loads(route.calls.last.request.content)["code"] == "real-code"


def test_gives_up_when_nothing_calls_back(cli_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexla_cli import login as login_module

    monkeypatch.setattr(login_module.webbrowser, "open", lambda _u: True)  # never calls back
    monkeypatch.setattr(login_module, "_CALLBACK_TIMEOUT_S", 0.2)

    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code != 0
    assert "timed out" in result.output


def test_deployment_without_cli_auth_says_so(
    cli_app, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A bare 404 would read as "not found" and send someone hunting; say that
    # the deployment simply doesn't offer browser login.
    from nexla_cli import login as login_module

    monkeypatch.setattr(
        login_module.webbrowser, "open", _fake_browser(code="fake-code-123", error=None)
    )
    respx_mock.post(f"{BASE_URL}/cli-auth/token").mock(
        return_value=httpx.Response(404, json={"detail": "Not Found"})
    )
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == EXIT.CONFIG
    assert "isn't available on this deployment" in result.output
    assert "--service-key" in result.output


def test_requires_a_web_url(cli_app, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXLA_WEB_URL", raising=False)
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == EXIT.CONFIG
    assert "NEXLA_WEB_URL" in result.output


def test_requires_a_scheme_on_the_web_url(cli_app, monkeypatch: pytest.MonkeyPatch) -> None:
    # A schemeless value makes webbrowser.open() misbehave in confusing,
    # platform-specific ways -- catch it here with a clear message instead.
    monkeypatch.setenv("NEXLA_WEB_URL", "localhost:3000")
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == EXIT.CONFIG
    assert "http://" in result.output


def test_browser_and_service_key_are_mutually_exclusive(cli_app) -> None:
    # Ambiguous: rejected locally with VALIDATION, before any network call --
    # not merely failing later because one flag was silently ignored.
    result = CliRunner().invoke(
        cli_app, ["login", "--browser", "--service-key", "k", "--api-url", BASE_URL]
    )
    assert result.exit_code == EXIT.VALIDATION
    assert "not both" in result.output
