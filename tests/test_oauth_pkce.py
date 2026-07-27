"""Loopback PKCE browser sign-in (`login --browser`).

Hermetic: the IdP's *token* endpoint is stubbed, and the browser step is
simulated by hitting the CLI's own loopback server with a crafted redirect --
no network, no real browser, no registered OAuth app needed.
"""

from __future__ import annotations

import base64
import hashlib
import threading
import urllib.parse
import urllib.request

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nexla_cli import config, oauth
from nexla_cli.errors import EXIT, CliError

from .conftest import BASE_URL

_MS_LOGIN_BODY = {
    "access_token": "sso-tok",
    "expires_at": 1234567890,
    "user": {"email": "a@nexla.com"},
    "org": {"name": "Acme"},
}


def test_pkce_pair_is_valid_s256() -> None:
    verifier, challenge = oauth._pkce_pair()
    assert len(verifier) >= 43  # RFC 7636 minimum entropy
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert "=" not in challenge  # base64url, unpadded


def test_pkce_pair_is_random() -> None:
    assert oauth._pkce_pair()[0] != oauth._pkce_pair()[0]


def test_authorize_url_carries_pkce_and_state() -> None:
    url = oauth._authorize_url("https://idp.test", "cid", "http://127.0.0.1:1", "chal", "st", "nc")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"] == ["chal"]
    assert q["state"] == ["st"]
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["cid"]


def test_loopback_binds_localhost_only() -> None:
    server, port = oauth._serve_one_redirect()
    try:
        # Never 0.0.0.0: the port briefly accepts an authorization code.
        assert server.server_address[0] == "127.0.0.1"
        assert port > 0
    finally:
        server.server_close()


def _drive_flow(monkeypatch: pytest.MonkeyPatch, *, tamper_state: bool = False) -> str:
    """Run obtain_id_token while a thread plays the browser's redirect back."""
    captured: dict[str, str] = {}

    def fake_open(url: str) -> bool:
        # Stand in for the browser: parse the authorize URL and hit the loopback
        # redirect_uri with a code (and the echoed state, unless tampering).
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        captured.update({k: v[0] for k, v in q.items()})
        redirect = q["redirect_uri"][0]
        state = "wrong-state" if tamper_state else q["state"][0]

        def hit() -> None:
            with urllib.request.urlopen(f"{redirect}/?code=the-code&state={state}", timeout=5):
                pass

        threading.Thread(target=hit, daemon=True).start()
        return True

    monkeypatch.setattr(oauth.webbrowser, "open", fake_open)
    monkeypatch.setattr(
        oauth, "_post_form", lambda url, fields: {"id_token": f"idtok-for-{fields['code']}"}
    )
    token = oauth.obtain_id_token("cid", authority="https://idp.test")
    assert captured["code_challenge_method"] == "S256"
    return token


def test_loopback_flow_returns_id_token(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _drive_flow(monkeypatch) == "idtok-for-the-code"


def test_state_mismatch_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    # A redirect echoing the wrong state must never reach the code exchange.
    with pytest.raises(CliError) as exc:
        _drive_flow(monkeypatch, tamper_state=True)
    assert exc.value.code == EXIT.ERROR
    assert "state mismatch" in exc.value.message


def test_idp_error_redirect_is_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_open(url: str) -> bool:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        redirect = q["redirect_uri"][0]

        def hit() -> None:
            try:
                with urllib.request.urlopen(
                    f"{redirect}/?error=access_denied&error_description=nope", timeout=5
                ):
                    pass
            except urllib.error.HTTPError:
                pass  # handler answers 400 for the error case

        threading.Thread(target=hit, daemon=True).start()
        return True

    monkeypatch.setattr(oauth.webbrowser, "open", fake_open)
    with pytest.raises(CliError) as exc:
        oauth.obtain_id_token("cid", authority="https://idp.test")
    assert exc.value.code == EXIT.AUTH
    assert "nope" in exc.value.message


def test_browser_login_without_client_id_is_config_error(cli_app, monkeypatch) -> None:
    monkeypatch.delenv("NEXLA_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == EXIT.CONFIG
    assert "NEXLA_OAUTH_CLIENT_ID" in result.output


def test_browser_login_exchanges_id_token_and_persists(
    cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    # id-token -> POST /auth/microsoft/login -> bearer, persisted like any login.
    monkeypatch.setenv("NEXLA_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.delenv("NEXLA_TOKEN", raising=False)
    monkeypatch.setattr(oauth, "obtain_id_token", lambda cid, authority=None: "ms-id-token")
    route = respx_mock.post(f"{BASE_URL}/auth/microsoft/login").mock(
        return_value=httpx.Response(200, json=_MS_LOGIN_BODY)
    )
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == 0, result.output
    import json as jsonlib

    assert jsonlib.loads(route.calls.last.request.content) == {"microsoft_id_token": "ms-id-token"}
    stored = config.load()
    assert stored["access_token"] == "sso-tok"
    # SSO has no service key to store, by construction.
    assert "service_key" not in stored


def test_menu_offers_browser_only_when_client_id_set(monkeypatch) -> None:
    from nexla_cli import login as login_module

    monkeypatch.delenv("NEXLA_OAUTH_CLIENT_ID", raising=False)
    # Picking "2" with no client_id re-prompts; then "1" falls back to the key.
    choices = iter(["2", "1"])
    monkeypatch.setattr(login_module.typer, "prompt", lambda *a, **k: next(choices))
    assert login_module._select_auth_method() is False

    monkeypatch.setenv("NEXLA_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(login_module.typer, "prompt", lambda *a, **k: "2")
    assert login_module._select_auth_method() is True


def test_ctrl_c_at_menu_exits_quietly_not_traceback(cli_app, monkeypatch) -> None:
    # Ctrl-C at the auth-method menu is a deliberate user action: exit 130
    # (shell SIGINT convention) with a one-word notice, never a traceback.
    from nexla_cli import login as login_module

    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)

    def _abort(*a, **k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(login_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(login_module.typer, "prompt", _abort)
    result = CliRunner().invoke(cli_app, ["login"])
    assert result.exit_code == 130
    assert "Traceback" not in result.output
    assert "aborted" in result.output


def test_ctrl_c_at_key_prompt_exits_quietly(cli_app, monkeypatch) -> None:
    # Same for the hidden key prompt -- and it must NOT be reported as the
    # "no service key provided" misconfiguration error. (CliRunner swaps
    # sys.stdin, so stub the menu directly rather than faking isatty.)
    from nexla_cli import login as login_module

    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setattr(login_module, "_select_auth_method", lambda: False)
    monkeypatch.setattr(login_module.sys.stdin, "isatty", lambda: True)

    def _abort(*a, **k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(login_module.typer, "prompt", _abort)
    result = CliRunner().invoke(cli_app, ["login"])
    assert result.exit_code == 130
    assert "Traceback" not in result.output
    assert "no service key provided" not in result.output


def test_non_tty_no_input_still_reports_misconfiguration(cli_app, monkeypatch) -> None:
    # The non-interactive path keeps its actionable config error (exit 3).
    from nexla_cli import login as login_module

    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setattr(login_module.sys.stdin, "isatty", lambda: False)

    def _abort(*a, **k):
        raise login_module.typer.Abort()

    monkeypatch.setattr(login_module.typer, "prompt", _abort)
    result = CliRunner().invoke(cli_app, ["login"])
    assert result.exit_code == EXIT.CONFIG
    assert "no service key provided" in result.output
