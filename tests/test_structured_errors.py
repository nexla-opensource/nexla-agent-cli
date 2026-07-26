"""Structured error output: machine-parseable `error_type` + a `hint`.

Under `-o json`, every error carries an `error_type` (a stable slug derived
from the exit code) so an agent can branch without parsing message text, plus
an optional `hint` (the next step). Plain-text output gets a `hint:` line.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nexla_cli.errors import EXIT, CliError

from .conftest import BASE_URL


def test_error_type_from_code() -> None:
    assert CliError(EXIT.CONFIG, "x").error_type == "config"
    assert CliError(EXIT.AUTH, "x").error_type == "auth"
    assert CliError(EXIT.NOT_FOUND, "x").error_type == "not_found"
    assert CliError(EXIT.UPSTREAM, "x").error_type == "upstream"
    assert CliError(99, "x").error_type == "error"  # unknown code -> generic


def test_exit_slug() -> None:
    assert EXIT.UPSTREAM.slug == "upstream"
    assert EXIT.NOT_FOUND.slug == "not_found"


def _last_json(output: str) -> dict:
    return json.loads([ln for ln in output.splitlines() if ln.strip().startswith("{")][-1])


def test_json_error_carries_type_and_hint(cli_app) -> None:
    result = CliRunner().invoke(
        cli_app,
        ["--output", "json", "sources", "list"],
        env={"NEXLA_API_URL": BASE_URL, "NEXLA_TOKEN": ""},  # not authenticated
    )
    assert result.exit_code == EXIT.CONFIG
    env = _last_json(result.output)
    assert env["error_type"] == "config"
    assert "login" in env["hint"].lower()


def test_plain_error_has_hint_line(cli_app, monkeypatch: pytest.MonkeyPatch) -> None:
    # The error handler reads the output flag from sys.argv (it runs before ctx
    # exists), so set it there to force the plain-text branch.
    monkeypatch.setattr("sys.argv", ["nexla-cli", "--output", "table", "sources", "list"])
    result = CliRunner().invoke(
        cli_app,
        ["--output", "table", "sources", "list"],
        env={"NEXLA_API_URL": BASE_URL, "NEXLA_TOKEN": ""},
    )
    assert result.exit_code == EXIT.CONFIG
    assert "hint:" in result.output


def test_upstream_error_has_type_no_hint(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(500, json={"detail": "boom"})
    )
    result = runner.invoke(cli_app, ["--output", "json", "sources", "list"])
    assert result.exit_code == EXIT.UPSTREAM
    env = _last_json(result.output)
    assert env["error_type"] == "upstream"
    assert "hint" not in env  # no hint set for a generic upstream error
