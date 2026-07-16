from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_login_success_prints_token_only_on_stdout(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(f"{BASE_URL}/login").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "tok-abc",
                "expires_at": 1234567890,
                "token_type": "Bearer",
                "user": {"id": 1, "email": "a@nexla.com"},
                "org": {"id": 2, "name": "Acme"},
            },
        )
    )
    result = runner.invoke(cli_app, ["login", "--service-key", "svc-key-12345"])
    assert result.exit_code == 0
    assert route.called
    assert route.calls.last.request.method == "POST"
    assert route.calls.last.request.url.path == "/login"
    assert route.calls.last.request.headers.get("authorization") is None
    assert result.stdout.strip() == "tok-abc"


def test_login_sanitizes_user_and_org_metadata_but_not_the_token(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # A real token would never contain a zero-width char; used here purely
    # to prove sanitize() was never applied to it. (Not using an ANSI
    # sequence for this: Click's own echo() strips ANSI on a non-tty stream
    # regardless of our code, which would make the assertion pass for the
    # wrong reason -- zero-width Unicode isn't touched by Click, only by
    # our sanitize(), so it actually isolates what we're testing.)
    dirty_token = "tok-abc" + chr(0x200B)
    respx_mock.post(f"{BASE_URL}/login").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": dirty_token,
                "expires_at": 1234567890,
                "token_type": "Bearer",
                "user": {"id": 1, "email": "a\x1b[31m@nexla.com"},
                "org": {"id": 2, "name": "Acme" + chr(0x200B) + "Corp"},
            },
        )
    )
    result = runner.invoke(cli_app, ["login", "--service-key", "svc-key-12345"])
    assert result.exit_code == 0
    assert result.stdout.strip() == dirty_token  # token is never sanitized
    assert "\x1b[31m" not in result.stderr
    assert "user=a@nexla.com" in result.stderr
    assert "org=AcmeCorp" in result.stderr


def test_login_401_no_token_on_stdout(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{BASE_URL}/login").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid Nexla service key"})
    )
    result = runner.invoke(cli_app, ["login", "--service-key", "bad-key"])
    assert result.exit_code == 4  # EXIT.AUTH
    assert "tok-abc" not in result.stdout
    assert result.stdout.strip() == ""
