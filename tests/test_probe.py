from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_probe_with_credential_id(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        return_value=httpx.Response(200, json={"ok": True, "kind": "validate"})
    )
    result = runner.invoke(cli_app, ["probe", "run", "--action", "validate", "--credential-id", "1"])
    assert result.exit_code == 0
    assert route.called
    body = route.calls.last.request.content
    assert b"credential_id" in body


def test_probe_with_inline_connector(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        return_value=httpx.Response(200, json={"ok": True, "kind": "sample", "samples": []})
    )
    result = runner.invoke(
        cli_app,
        ["probe", "run", "--action", "sample", "--connector", "s3", "--config", '{"bucket": "x"}'],
    )
    assert result.exit_code == 0
    assert route.called


def test_probe_requires_exactly_one_credential_source(cli_app) -> None:
    runner = CliRunner()
    result = runner.invoke(cli_app, ["probe", "run", "--action", "validate"])
    assert result.exit_code != 0


def test_probe_mutually_exclusive_error_emits_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supplying both --credential-id and --connector is a local validation
    failure -- under `-o json` it must flow through `_wrap_cli_error` and be
    emitted as the JSON error envelope every other validation failure uses,
    not Click's plain usage text. Exit code stays 2 (EXIT.VALIDATION)."""
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    monkeypatch.setenv("NEXLA_OUTPUT", "json")
    from nexla_cli import app

    result = CliRunner().invoke(
        app,
        ["probe", "run", "--action", "validate", "--credential-id", "1", "--connector", "s3"],
    )
    assert result.exit_code == 2  # EXIT.VALIDATION
    payload = json.loads(result.stderr)
    assert payload["error"] is None
    assert "exactly one of --credential-id or --connector" in payload["detail"]


def test_probe_sample_npe_error_gets_hint(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    """A kind/params shape mismatch surfaces upstream as a Java NPE-style 500
    (`Cannot read field "template" because "varInfo" is null`) with no other
    indication of the cause -- `probe run` should append a hint pointing back
    at `--help` rather than passing the opaque message through untouched."""
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        return_value=httpx.Response(
            500,
            json={
                "detail": {
                    "errorMessage": 'Cannot read field "template" because "varInfo" is null',
                    "statusCode": 500,
                }
            },
        )
    )
    result = runner.invoke(
        cli_app,
        ["probe", "run", "--action", "sample", "--credential-id", "1", "--params", '{"path": "/x"}'],
    )
    assert result.exit_code == 6
    assert "hint:" in result.stderr
    assert "--help" in result.stderr


def test_probe_validate_npe_error_gets_no_hint(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    """The hint is scoped to `sample`/`tree` -- `validate` doesn't take a
    kind-discriminated `params` shape, so the same NPE signature there isn't
    a shape-mismatch hint candidate."""
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        return_value=httpx.Response(
            500,
            json={"detail": {"errorMessage": "Cannot read field \"x\" because \"y\" is null", "statusCode": 500}},
        )
    )
    result = runner.invoke(cli_app, ["probe", "run", "--action", "validate", "--credential-id", "1"])
    assert result.exit_code == 6
    assert "hint:" not in result.stderr


def test_probe_unrelated_500_gets_no_hint(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    """A 500 that doesn't match the NPE signature (e.g. a plain gateway
    timeout) should pass through unchanged -- the hint is only for the
    specific known-bad signature, not every upstream failure."""
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        return_value=httpx.Response(500, json={"detail": {"error": "gateway timeout"}})
    )
    result = runner.invoke(
        cli_app, ["probe", "run", "--action", "sample", "--credential-id", "1"]
    )
    assert result.exit_code == 6
    assert "hint:" not in result.stderr


def test_probe_sample_npe_in_200_ok_body_gets_hint(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Live bug: a `kind`/`params` shape mismatch against an api-kind
    credential doesn't always come back as a non-2xx -- the upstream probe
    service can instead return HTTP 200 with `{"ok": true, "sample_format":
    "unknown", "raw_response_excerpt": "...the NPE message nested inside a
    stringified excerpt..."}`. `probe run` must detect the NPE signature in
    that successful envelope too, not just in the exception path, and still
    surface it as exit 6 with the same hint."""
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "sample_format": "unknown",
                "raw_response_excerpt": (
                    '{"errorMessage": "Cannot read field \\"template\\" because '
                    '\\"varInfo\\" is null", "statusCode": 500}'
                ),
            },
        )
    )
    result = runner.invoke(
        cli_app,
        ["probe", "run", "--action", "sample", "--credential-id", "1", "--params", '{"endpoint": "x.y"}'],
    )
    assert result.exit_code == 6
    assert "hint:" in result.stderr
    assert "--help" in result.stderr


def test_probe_tree_npe_in_200_ok_body_gets_hint(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Same nested-NPE-in-a-200 shape, but for `--action tree`."""
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "sample_format": "unknown",
                "raw_response_excerpt": 'errorMessage: NullPointerException at ...',
            },
        )
    )
    result = runner.invoke(
        cli_app,
        ["probe", "run", "--action", "tree", "--credential-id", "1"],
    )
    assert result.exit_code == 6
    assert "hint:" in result.stderr


def test_probe_normal_200_ok_sample_not_annotated(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """A normal successful sample response -- no NPE signature anywhere in
    the body -- must not be misdetected as the bug and must exit 0 with no
    hint appended."""
    respx_mock.post(f"{BASE_URL}/nexla/probe").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "sample_format": "json",
                "samples": [{"id": 1, "name": "foo"}],
            },
        )
    )
    result = runner.invoke(
        cli_app,
        ["probe", "run", "--action", "sample", "--credential-id", "1"],
    )
    assert result.exit_code == 0
    assert "hint:" not in result.stderr
