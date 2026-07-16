from __future__ import annotations

import json

import httpx
import respx
from typer.testing import CliRunner

from nexla_cli.errors import EXIT

from .conftest import BASE_URL


def test_list_page_all_is_rejected_not_silently_ignored(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # orgs list has no page/per_page and returns a bare array — --page-all
    # is rejected outright (the conservative choice) rather than silently
    # calling client.paginate() against a response with no next_page key.
    result = runner.invoke(cli_app, ["--page-all", "orgs", "list"])
    assert result.exit_code == EXIT.VALIDATION
    assert respx_mock.calls.call_count == 0


def test_list_output_json_and_fields_work_normally(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/nexla/orgs").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "Acme"}])
    )
    result = runner.invoke(cli_app, ["--output", "json", "--fields", "id", "orgs", "list"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"id": 1}]


def test_list_is_real_and_returns_bare_array(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # orgs list returns a bare array upstream, not a Page[T] envelope —
    # unlike every other list endpoint. output.emit must handle it directly.
    route = respx_mock.get(f"{BASE_URL}/nexla/orgs").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "Acme"}])
    )
    result = runner.invoke(cli_app, ["orgs", "list"])
    assert result.exit_code == 0
    assert route.calls.last.request.url.path == "/nexla/orgs"
    assert "Acme" in result.stdout


def test_get_fails_locally_not_implemented(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # `orgs get` is hidden and not implemented in v1 — it must fail locally
    # with a clear message and make NO network call (the route stays uncalled).
    route = respx_mock.get(f"{BASE_URL}/nexla/orgs/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(cli_app, ["orgs", "get", "1"])
    assert result.exit_code == 1  # EXIT.ERROR (local, not a 501 round-trip)
    assert "not available in this release" in result.stderr
    assert not route.called
