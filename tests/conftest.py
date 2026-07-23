"""Shared fixtures for `nexla` CLI tests.

Every test in this package runs through respx-mocked httpx transports —
no real network call, no real Nexla account, ever.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nexla_cli import app

BASE_URL = "https://api.test"
MONITORING_URL = "https://monitoring.test"


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Point the credential store at a throwaway dir so no test ever reads or
    writes the developer's real ``~/.config/nexla/config.json``."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def mock_openapi(respx_mock: respx.MockRouter, spec: dict[str, Any]) -> respx.Route:
    """Stub ``GET /openapi.json`` with ``spec``.

    The schema-introspection and dry-run tests each need their own tailored
    spec, but the stub wiring (the URL + 200 JSON response) is identical --
    centralize just that here so the path lives in one place.
    """
    return respx_mock.get(f"{BASE_URL}/openapi.json").mock(
        return_value=httpx.Response(200, json=spec)
    )


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "test-token")
    monkeypatch.setenv("NEXLA_MONITORING_URL", MONITORING_URL)
    return CliRunner()


@pytest.fixture
def cli_app():
    return app
