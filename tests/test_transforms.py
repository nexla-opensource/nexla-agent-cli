from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_test(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/transforms/test").mock(
        return_value=httpx.Response(200, json={"output": [{"a": 1}], "schema": None, "errors": []})
    )
    result = runner.invoke(
        cli_app,
        [
            "transforms",
            "test",
            "--language",
            "python",
            "--code",
            "def transform(record, *args): return record",
            "--input",
            '[{"a": 1}]',
        ],
    )
    assert result.exit_code == 0
    assert route.calls.last.request.method == "POST"
    assert route.calls.last.request.url.path == "/nexla/transforms/test"


def test_test_accepts_multiline_code(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/transforms/test").mock(
        return_value=httpx.Response(200, json={"output": [{"a": 1}], "schema": None, "errors": []})
    )
    result = runner.invoke(
        cli_app,
        [
            "transforms",
            "test",
            "--language",
            "python",
            "--code",
            "def transform(record, sourceMetadata, *args):\n    return record\n",
            "--input",
            '[{"a": 1}]',
        ],
    )
    assert result.exit_code == 0
    assert route.called


def test_test_rejects_ansi_escape_in_code(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/transforms/test")
    result = runner.invoke(
        cli_app,
        [
            "transforms",
            "test",
            "--language",
            "python",
            "--code",
            "def transform(record, *args): return record\x1b[31m",
            "--input",
            "[]",
        ],
    )
    assert result.exit_code == 2
    assert not route.called


def test_no_crud_commands(cli_app) -> None:
    runner = CliRunner()
    for cmd in ("list", "get", "create", "delete"):
        result = runner.invoke(cli_app, ["transforms", cmd])
        assert result.exit_code != 0
