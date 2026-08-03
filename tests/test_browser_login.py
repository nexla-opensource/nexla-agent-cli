"""`login --browser` -- the express CLI-auth handoff.

Hermetic: `/cli-auth/pair` and `/cli-auth/poll` are respx-mocked, the browser
launch is stubbed, and sleeps are patched out so the poll loop runs instantly.
"""

from __future__ import annotations

import json as jsonlib

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nexla_cli import config
from nexla_cli.errors import EXIT

from .conftest import BASE_URL

_PAIR = {
    "user_code": "WDJB-MJHT",
    "verification_uri": "https://web.test/cli-auth",
    "verification_uri_complete": "https://web.test/cli-auth?user_code=WDJB-MJHT",
    "poll_token": "poll-abc",
    "expires_in": 600,
    "interval": 5,
}
_LOGIN_BODY = {
    "access_token": "tok-browser",
    "expires_at": 1234567890,
    "user": {"email": "a@nexla.com"},
    "org": {"name": "Acme"},
}


@pytest.fixture(autouse=True)
def _fast_and_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexla_cli import login as login_module

    monkeypatch.setattr(login_module.time, "sleep", lambda _s: None)
    monkeypatch.setattr(login_module.webbrowser, "open", lambda _u: False)
    monkeypatch.delenv("NEXLA_TOKEN", raising=False)
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)


def test_polls_until_approved_and_persists(
    cli_app, respx_mock: respx.MockRouter
) -> None:
    # 202 pending -> 429 slow_down -> 200 approved. All three must be handled
    # in one loop: only the last is terminal.
    respx_mock.post(f"{BASE_URL}/cli-auth/pair").mock(
        return_value=httpx.Response(201, json=_PAIR)
    )
    poll = respx_mock.post(f"{BASE_URL}/cli-auth/poll").mock(
        side_effect=[
            httpx.Response(202, json={"status": "authorization_pending"}),
            httpx.Response(429, json={"status": "slow_down"}),
            httpx.Response(200, json=_LOGIN_BODY),
        ]
    )
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == 0, result.output
    assert poll.call_count == 3
    assert jsonlib.loads(poll.calls.last.request.content)["poll_token"] == "poll-abc"
    # Goes through the same persistence path as a service-key login.
    assert config.load()["access_token"] == "tok-browser"


def test_prints_the_code_and_does_not_prefill_the_url(
    cli_app, respx_mock: respx.MockRouter
) -> None:
    # The bare verification_uri is opened on purpose: a pre-filled link is a
    # one-click approval of whatever pairing it carries.
    opened: list[str] = []
    respx_mock.post(f"{BASE_URL}/cli-auth/pair").mock(
        return_value=httpx.Response(201, json=_PAIR)
    )
    respx_mock.post(f"{BASE_URL}/cli-auth/poll").mock(
        return_value=httpx.Response(200, json=_LOGIN_BODY)
    )
    from nexla_cli import login as login_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(login_module.webbrowser, "open", lambda u: opened.append(u) or True)
        result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == 0, result.output
    assert "WDJB-MJHT" in result.output  # code shown so the user can type it
    assert opened == ["https://web.test/cli-auth"]
    assert "user_code=" not in opened[0]


def test_no_open_skips_the_browser(cli_app, respx_mock: respx.MockRouter) -> None:
    opened: list[str] = []
    respx_mock.post(f"{BASE_URL}/cli-auth/pair").mock(
        return_value=httpx.Response(201, json=_PAIR)
    )
    respx_mock.post(f"{BASE_URL}/cli-auth/poll").mock(
        return_value=httpx.Response(200, json=_LOGIN_BODY)
    )
    from nexla_cli import login as login_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(login_module.webbrowser, "open", lambda u: opened.append(u) or True)
        result = CliRunner().invoke(cli_app, ["login", "--browser", "--no-open"])
    assert result.exit_code == 0
    assert opened == []


def test_denial_is_reported_plainly(cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{BASE_URL}/cli-auth/pair").mock(
        return_value=httpx.Response(201, json=_PAIR)
    )
    respx_mock.post(f"{BASE_URL}/cli-auth/poll").mock(
        return_value=httpx.Response(403, json={"status": "access_denied"})
    )
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == EXIT.AUTH
    assert "denied in the browser" in result.output


def test_expired_pairing_is_reported(cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{BASE_URL}/cli-auth/pair").mock(
        return_value=httpx.Response(201, json=_PAIR)
    )
    respx_mock.post(f"{BASE_URL}/cli-auth/poll").mock(
        return_value=httpx.Response(410, json={"status": "expired_token"})
    )
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code != 0
    assert "expired" in result.output


def test_deployment_without_cli_auth_says_so(cli_app, respx_mock: respx.MockRouter) -> None:
    # A bare 404 would read as "not found" and send someone hunting; say that
    # the deployment simply doesn't offer browser login.
    respx_mock.post(f"{BASE_URL}/cli-auth/pair").mock(
        return_value=httpx.Response(404, json={"detail": "Not Found"})
    )
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code == EXIT.CONFIG
    assert "isn't available on this deployment" in result.output
    assert "--service-key" in result.output


def test_gives_up_when_the_pairing_window_closes(
    cli_app, respx_mock: respx.MockRouter
) -> None:
    # Never approved: bounded by expires_in, not an infinite loop.
    respx_mock.post(f"{BASE_URL}/cli-auth/pair").mock(
        return_value=httpx.Response(201, json={**_PAIR, "expires_in": 0, "interval": 1})
    )
    respx_mock.post(f"{BASE_URL}/cli-auth/poll").mock(
        return_value=httpx.Response(202, json={"status": "authorization_pending"})
    )
    result = CliRunner().invoke(cli_app, ["login", "--browser"])
    assert result.exit_code != 0
    assert "expired before it was approved" in result.output


def test_browser_and_service_key_are_mutually_exclusive(cli_app) -> None:
    # Ambiguous: rejected locally with VALIDATION, before any network call --
    # not merely failing later because one flag was silently ignored.
    result = CliRunner().invoke(
        cli_app, ["login", "--browser", "--service-key", "k", "--api-url", BASE_URL]
    )
    assert result.exit_code == EXIT.VALIDATION
    assert "not both" in result.output
