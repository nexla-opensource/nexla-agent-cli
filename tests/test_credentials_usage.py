"""`credentials usage` + delete-in-use handling.

The list views omit `credential_id`, so `usage` scans each source/sink detail
to find what references a credential. A delete refused with a 200-and-error
envelope ("Data credentials in use") must fail non-zero with a hint, not
print the error as a success.
"""

from __future__ import annotations

import json

import httpx
import respx
from typer.testing import CliRunner

from nexla_cli.errors import EXIT

from .conftest import BASE_URL


def test_usage_lists_referencing_sources_and_sinks(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/nexla/credentials/99").mock(
        return_value=httpx.Response(200, json={"id": 99, "connector": "snowflake"})
    )
    respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 1}, {"id": 2}], "next_page": None})
    )
    respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "src1", "credential_id": 99})
    )
    respx_mock.get(f"{BASE_URL}/nexla/sources/2").mock(
        return_value=httpx.Response(200, json={"id": 2, "name": "src2", "credential_id": 50})
    )
    respx_mock.get(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 3}], "next_page": None})
    )
    respx_mock.get(f"{BASE_URL}/nexla/sinks/3").mock(
        return_value=httpx.Response(200, json={"id": 3, "name": "sink3", "credential_id": 99})
    )

    result = runner.invoke(cli_app, ["--output", "json", "credentials", "usage", "99"])

    assert result.exit_code == 0, result.output
    found = {(d["type"], d["id"]) for d in json.loads(result.stdout)}
    assert found == {("source", 1), ("sink", 3)}  # cred 50's source excluded


def test_usage_empty_when_nothing_references(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"{BASE_URL}/nexla/credentials/99").mock(
        return_value=httpx.Response(200, json={"id": 99, "connector": "snowflake"})
    )
    respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 1}], "next_page": None})
    )
    respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "credential_id": 7})
    )
    respx_mock.get(f"{BASE_URL}/nexla/sinks").mock(
        return_value=httpx.Response(200, json={"items": [], "next_page": None})
    )
    result = runner.invoke(cli_app, ["--output", "json", "credentials", "usage", "99"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_delete_in_use_fails_nonzero_with_hint(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # API returns HTTP 200 with an error envelope when the delete is refused.
    respx_mock.delete(f"{BASE_URL}/nexla/credentials/99").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": {
                    "error": "nexla.delete_credential_failed",
                    "detail": "Data credentials in use",
                    "nexla_request_id": "abc",
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["credentials", "delete", "99"])
    assert result.exit_code == EXIT.ERROR  # non-zero (was silently 0)
    assert "Data credentials in use" in result.output
    assert "credentials usage 99" in result.output


def test_delete_success_exits_zero(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.delete(f"{BASE_URL}/nexla/credentials/99").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["credentials", "delete", "99"])
    assert result.exit_code == 0


def test_delete_body_without_error_still_succeeds(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # A soft-delete that echoes the object (no error key) is still success.
    respx_mock.delete(f"{BASE_URL}/nexla/credentials/99").mock(
        return_value=httpx.Response(200, json={"id": 99, "status": "PAUSED"})
    )
    result = runner.invoke(cli_app, ["--output", "json", "credentials", "delete", "99"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["id"] == 99
