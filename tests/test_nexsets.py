from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_list(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/nexsets").mock(
        return_value=httpx.Response(
            200, json={"items": [{"id": 1, "name": "n1", "status": "ACTIVE"}], "page": 1, "per_page": 50}
        )
    )
    result = runner.invoke(cli_app, ["nexsets", "list"])
    assert result.exit_code == 0
    assert route.calls.last.request.url.path == "/nexla/nexsets"
    assert "n1" in result.stdout


def test_get(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/nexsets/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "n1"})
    )
    result = runner.invoke(cli_app, ["nexsets", "get", "1"])
    assert result.exit_code == 0
    assert route.called


def test_get_wait_until_polls_until_samples_appear(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setattr("nexla_cli.poll.time.sleep", lambda s: None)
    route = respx_mock.get(f"{BASE_URL}/nexla/nexsets/1").mock(
        side_effect=[
            httpx.Response(200, json={"id": 1, "samples": []}),
            httpx.Response(200, json={"id": 1, "samples": [{"x": 1}]}),
        ]
    )
    result = runner.invoke(
        cli_app, ["nexsets", "get", "1", "--wait-until", "samples", "--wait-interval", "0"]
    )
    assert result.exit_code == 0
    assert route.call_count == 2


def test_transform(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/nexsets/1/transform").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "derived"})
    )
    result = runner.invoke(
        cli_app,
        [
            "nexsets",
            "transform",
            "1",
            "--name",
            "derived",
            "--language",
            "python",
            "--code",
            "def transform(record, *args): return record",
        ],
    )
    assert result.exit_code == 0
    assert route.called
    assert route.calls.last.request.url.path == "/nexla/nexsets/1/transform"


def test_transform_json_and_params_passthrough(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{BASE_URL}/nexla/nexsets/1/transform").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "derived"})
    )
    result = runner.invoke(
        cli_app,
        [
            "nexsets",
            "transform",
            "1",
            "--name",
            "derived",
            "--language",
            "python",
            "--code",
            "def transform(record, *args): return record",
            "--json",
            '{"extra_field": "from-json"}',
            "--params",
            "params_field=from-params",
        ],
    )
    assert result.exit_code == 0
    body = respx_mock.calls.last.request.content
    assert b"from-json" in body
    assert b"from-params" in body


def test_transform_accepts_multiline_code(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """A real multi-statement transform body (with newlines/indentation)
    must not be flattened into one semicolon-joined line to pass
    validation -- scan_body allows newlines/tabs through."""
    route = respx_mock.post(f"{BASE_URL}/nexla/nexsets/1/transform").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "derived"})
    )
    code = "def transform(record, sourceMetadata, *args):\n    x = record['a'] + 1\n    return {'a': x}\n"
    result = runner.invoke(
        cli_app,
        [
            "nexsets",
            "transform",
            "1",
            "--name",
            "derived",
            "--language",
            "python",
            "--code",
            code,
        ],
    )
    assert result.exit_code == 0
    assert route.called


def test_transform_rejects_ansi_escape_in_code(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/nexsets/1/transform")
    result = runner.invoke(
        cli_app,
        [
            "nexsets",
            "transform",
            "1",
            "--name",
            "derived",
            "--language",
            "python",
            "--code",
            "def transform(record, *args): return record\x1b[31m",
        ],
    )
    assert result.exit_code == 2
    assert not route.called


def test_activate(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.put(f"{BASE_URL}/nexla/nexsets/1/activate").mock(
        return_value=httpx.Response(200, json={"id": 1, "status": "ACTIVE"})
    )
    result = runner.invoke(cli_app, ["nexsets", "activate", "1"])
    assert result.exit_code == 0
    assert route.called


def test_no_update_or_delete_commands(cli_app) -> None:
    runner = CliRunner()
    result = runner.invoke(cli_app, ["nexsets", "update", "1"])
    assert result.exit_code != 0
    result = runner.invoke(cli_app, ["nexsets", "delete", "1"])
    assert result.exit_code != 0
