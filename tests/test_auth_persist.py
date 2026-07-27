"""Credential persistence + reactive re-login.

`login` stashes the service key + bearer in the config file so later commands
need no env var, and `client.request` re-mints a bearer from that stored
service key on a 401 and retries once. All hermetic (respx), config isolated
to a tmp XDG dir by the autouse `_isolate_config` fixture in conftest.
"""

from __future__ import annotations

import json as jsonlib
import stat

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nexla_cli import config
from nexla_cli.errors import EXIT

from .conftest import BASE_URL

_LOGIN_BODY = {
    "access_token": "fresh-tok",
    "expires_at": 1234567890,
    "user": {"email": "a@nexla.com"},
    "org": {"name": "Acme"},
}


def _no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXLA_API_URL", raising=False)
    monkeypatch.delenv("NEXLA_TOKEN", raising=False)


def test_login_persists_credentials(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    _no_env(monkeypatch)
    respx_mock.post(f"{BASE_URL}/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
    result = CliRunner().invoke(
        cli_app, ["login", "--service-key", "svc-key-123", "--api-url", BASE_URL]
    )
    assert result.exit_code == 0
    stored = config.load()
    # The service key is NOT stored by default -- opt in with --store-service-key.
    assert "service_key" not in stored
    assert stored["access_token"] == "fresh-tok"
    assert stored["api_url"] == BASE_URL
    # secret at rest must be owner-only.
    assert stat.S_IMODE(config.path().stat().st_mode) == 0o600


def test_no_store_skips_persistence(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    _no_env(monkeypatch)
    respx_mock.post(f"{BASE_URL}/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
    result = CliRunner().invoke(
        cli_app, ["login", "--service-key", "k", "--api-url", BASE_URL, "--no-store"]
    )
    assert result.exit_code == 0
    assert config.load() == {}


def test_config_only_auth(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    _no_env(monkeypatch)
    config.save(api_url=BASE_URL, access_token="cfg-tok")
    route = respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(200, json={"items": [], "next_page": None})
    )
    result = CliRunner().invoke(cli_app, ["sources", "list"])
    assert result.exit_code == 0, result.output
    assert route.calls.last.request.headers["authorization"] == "Bearer cfg-tok"


def test_reactive_relogin_on_401(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    _no_env(monkeypatch)
    config.save(api_url=BASE_URL, service_key="svc-key-123", access_token="stale-tok")
    sources = respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        side_effect=[
            httpx.Response(401, json={"detail": {"error": "token expired"}}),
            httpx.Response(200, json={"items": [{"id": 1, "name": "s"}], "next_page": None}),
        ]
    )
    login = respx_mock.post(f"{BASE_URL}/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))

    result = CliRunner().invoke(cli_app, ["sources", "list"])

    assert result.exit_code == 0, result.output
    assert sources.call_count == 2  # original 401 + retry
    assert login.call_count == 1  # re-minted exactly once
    # retry used the fresh token, and it was written back to the store.
    assert sources.calls.last.request.headers["authorization"] == "Bearer fresh-tok"
    assert config.load()["access_token"] == "fresh-tok"


def test_401_without_service_key_maps_to_auth(
    cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "env-tok")  # env auth, no stored service key
    route = respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(401, json={"detail": "unauthorized"})
    )
    login = respx_mock.post(f"{BASE_URL}/login")
    result = CliRunner().invoke(cli_app, ["sources", "list"])
    assert result.exit_code == EXIT.AUTH  # 4, unchanged
    assert not login.called  # no re-login attempted
    assert route.call_count == 1  # no retry


def test_env_beats_config(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "env-tok")
    # config points elsewhere with a different token; env must win on both.
    config.save(api_url="https://other.test", service_key="k", access_token="cfg-tok")
    route = respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(200, json={"items": [], "next_page": None})
    )
    result = CliRunner().invoke(cli_app, ["sources", "list"])
    assert result.exit_code == 0, result.output  # hit BASE_URL (env), not other.test
    assert route.calls.last.request.headers["authorization"] == "Bearer env-tok"


def test_logout_clears_config(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    _no_env(monkeypatch)
    config.save(api_url=BASE_URL, service_key="k", access_token="tok")
    respx_mock.post(f"{BASE_URL}/logout").mock(return_value=httpx.Response(204))
    result = CliRunner().invoke(cli_app, ["logout"])
    assert result.exit_code == 0
    assert config.load() == {}
    assert not config.path().exists()


def test_logout_without_config_is_safe(cli_app, monkeypatch) -> None:
    _no_env(monkeypatch)
    result = CliRunner().invoke(cli_app, ["logout"])
    assert result.exit_code == 0


def test_login_persists_monitoring_url(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    # `login --monitoring-url` stores it so `triage` needs no NEXLA_MONITORING_URL.
    _no_env(monkeypatch)
    monkeypatch.delenv("NEXLA_MONITORING_URL", raising=False)
    respx_mock.post(f"{BASE_URL}/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
    result = CliRunner().invoke(
        cli_app,
        [
            "login",
            "--service-key",
            "svc-key-123",
            "--api-url",
            BASE_URL,
            "--monitoring-url",
            "https://mon.example.com/",
        ],
    )
    assert result.exit_code == 0
    assert config.load().get("monitoring_url") == "https://mon.example.com/"


def test_mcp_base_falls_back_to_stored_monitoring_url(monkeypatch) -> None:
    from nexla_cli import mcp_client

    monkeypatch.delenv("NEXLA_MONITORING_URL", raising=False)
    config.save(monitoring_url="https://stored-mon.example.com/")
    assert mcp_client._base() == "https://stored-mon.example.com/"


def test_mcp_base_env_beats_stored_monitoring_url(monkeypatch) -> None:
    from nexla_cli import mcp_client

    config.save(monitoring_url="https://stored-mon.example.com/")
    monkeypatch.setenv("NEXLA_MONITORING_URL", "https://env-mon.example.com/")
    assert mcp_client._base() == "https://env-mon.example.com/"


def test_mcp_base_errors_when_neither_set(monkeypatch) -> None:
    from nexla_cli import mcp_client
    from nexla_cli.errors import CliError

    monkeypatch.delenv("NEXLA_MONITORING_URL", raising=False)
    config.clear()
    with pytest.raises(CliError) as exc:
        mcp_client._base()
    assert exc.value.code == EXIT.CONFIG


def test_login_prompts_for_service_key_when_omitted(
    cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    # No --service-key on the command line -> hidden prompt (secret stays out
    # of argv / shell history). CliRunner feeds it via stdin.
    _no_env(monkeypatch)
    route = respx_mock.post(f"{BASE_URL}/login").mock(
        return_value=httpx.Response(200, json=_LOGIN_BODY)
    )
    result = CliRunner().invoke(
        cli_app, ["login", "--api-url", BASE_URL], input="svc-from-prompt\n"
    )
    assert result.exit_code == 0
    assert route.called
    body = jsonlib.loads(route.calls.last.request.content)
    assert body["service_key"] == "svc-from-prompt"


def test_whoami_reports_stored_identity(cli_app, monkeypatch) -> None:
    _no_env(monkeypatch)
    config.save(
        api_url=BASE_URL,
        access_token="tok",
        user_email="a@nexla.com",
        org_name="Acme",
        expires_at=9999999999,
    )
    result = CliRunner().invoke(cli_app, ["-o", "json", "whoami"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    assert data["user"] == "a@nexla.com"
    assert data["org"] == "Acme"
    assert data["token_source"] == "config"
    assert data["expired"] is False


def test_whoami_flags_expired_token(cli_app, monkeypatch) -> None:
    _no_env(monkeypatch)
    config.save(api_url=BASE_URL, access_token="tok", user_email="a@nexla.com", expires_at=1)
    result = CliRunner().invoke(cli_app, ["-o", "json", "whoami"])
    assert result.exit_code == 0
    assert jsonlib.loads(result.stdout)["expired"] is True


def test_whoami_unauthenticated_exits_auth(cli_app, monkeypatch) -> None:
    _no_env(monkeypatch)
    monkeypatch.delenv("NEXLA_TOKEN", raising=False)
    config.clear()
    result = CliRunner().invoke(cli_app, ["whoami"])
    assert result.exit_code == EXIT.AUTH


def test_select_auth_method_paste_returns(monkeypatch) -> None:
    # Choosing "1" (paste a service key) returns cleanly.
    from nexla_cli import login as login_module

    monkeypatch.setattr(login_module.typer, "prompt", lambda *a, **k: "1")
    # False = "use a service key" (True would mean browser sign-in).
    assert login_module._select_auth_method() is False


def test_select_auth_method_browser_loops_until_available(monkeypatch, capsys) -> None:
    # "2" (browser) is not available yet -> message + re-prompt until "1".
    from nexla_cli import login as login_module

    choices = iter(["2", "1"])
    monkeypatch.setattr(login_module.typer, "prompt", lambda *a, **k: next(choices))
    login_module._select_auth_method()  # must not raise; loops past "2"
    assert "available" in capsys.readouterr().err.lower()


def test_obtain_service_key_tty_shows_menu(monkeypatch) -> None:
    # On a TTY the menu shows, then the hidden key prompt is read.
    from nexla_cli import login as login_module

    monkeypatch.setattr(login_module.sys.stdin, "isatty", lambda: True)
    prompts = iter(["1", "the-service-key"])  # menu choice, then the key
    monkeypatch.setattr(login_module.typer, "prompt", lambda *a, **k: next(prompts))
    assert login_module._obtain_service_key() == "the-service-key"


def test_obtain_service_key_abort_is_clean_error(monkeypatch) -> None:
    # A non-TTY with no stdin (or Ctrl-D) makes the prompt abort -> must map to
    # a clean CliError(CONFIG), never a raw traceback.
    from nexla_cli import login as login_module
    from nexla_cli.errors import CliError

    monkeypatch.setattr(login_module.sys.stdin, "isatty", lambda: False)

    def _abort(*a, **k):
        raise login_module.typer.Abort()

    monkeypatch.setattr(login_module.typer, "prompt", _abort)
    with pytest.raises(CliError) as exc:
        login_module._obtain_service_key()
    assert exc.value.code == EXIT.CONFIG
    assert "service key" in exc.value.message.lower()


def test_store_service_key_flag_opts_in(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    _no_env(monkeypatch)
    respx_mock.post(f"{BASE_URL}/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
    result = CliRunner().invoke(
        cli_app,
        ["login", "--service-key", "svc-key-123", "--api-url", BASE_URL, "--store-service-key"],
    )
    assert result.exit_code == 0
    assert config.load()["service_key"] == "svc-key-123"


def test_proactive_refresh_before_expiry(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    # A config bearer about to expire is rotated via /auth/token/refresh BEFORE
    # the request, so the call never 401s and no service key is needed.
    _no_env(monkeypatch)
    import time as _time

    config.save(api_url=BASE_URL, access_token="old-tok", expires_at=int(_time.time()) + 10)
    refresh = respx_mock.post(f"{BASE_URL}/auth/token/refresh").mock(
        return_value=httpx.Response(
            200, json={"access_token": "rotated-tok", "expires_at": int(_time.time()) + 3600}
        )
    )
    sources = respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(200, json={"items": [], "next_page": None})
    )
    result = CliRunner().invoke(cli_app, ["sources", "list"])
    assert result.exit_code == 0, result.output
    assert refresh.called
    # request used the rotated token, and it was written back
    assert sources.calls.last.request.headers["authorization"] == "Bearer rotated-tok"
    assert config.load()["access_token"] == "rotated-tok"


def test_no_refresh_when_token_is_fresh(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    _no_env(monkeypatch)
    import time as _time

    config.save(api_url=BASE_URL, access_token="good-tok", expires_at=int(_time.time()) + 7200)
    refresh = respx_mock.post(f"{BASE_URL}/auth/token/refresh")
    respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(200, json={"items": [], "next_page": None})
    )
    result = CliRunner().invoke(cli_app, ["sources", "list"])
    assert result.exit_code == 0
    assert not refresh.called  # far from expiry -> no round trip


def test_no_refresh_for_env_token(cli_app, respx_mock: respx.MockRouter, monkeypatch) -> None:
    # An env-supplied token is not ours to rotate, even if the stored config
    # says it's expiring.
    import time as _time

    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "env-tok")
    config.save(api_url=BASE_URL, access_token="cfg-tok", expires_at=int(_time.time()) + 5)
    refresh = respx_mock.post(f"{BASE_URL}/auth/token/refresh")
    sources = respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(200, json={"items": [], "next_page": None})
    )
    result = CliRunner().invoke(cli_app, ["sources", "list"])
    assert result.exit_code == 0
    assert not refresh.called
    assert sources.calls.last.request.headers["authorization"] == "Bearer env-tok"


def test_env_token_401_never_rewrites_stored_config(
    cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    # Regression: with NEXLA_TOKEN set AND a stored service key, a 401 must NOT
    # re-mint and overwrite the stored bearer -- env auth isn't ours to rotate.
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "env-tok")
    config.save(api_url=BASE_URL, service_key="svc-key-123", access_token="cfg-tok")
    respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(401, json={"detail": "unauthorized"})
    )
    login = respx_mock.post(f"{BASE_URL}/login")
    result = CliRunner().invoke(cli_app, ["sources", "list"])
    assert result.exit_code == EXIT.AUTH
    assert not login.called  # no re-mint from the env session
    assert config.load()["access_token"] == "cfg-tok"  # store untouched
