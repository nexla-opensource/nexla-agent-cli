"""Not-implemented-in-v1 groups: code-containers, metrics, users, notifications.

These are hidden from the top-level help and fail locally with a stable
exit code, making NO network call — no round-trip to a guaranteed-501 route.
`orgs get` is the same (hidden, local-fail) while `orgs list` stays real.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nexla_cli.errors import EXIT


@pytest.mark.parametrize(
    "args",
    [
        ["code-containers", "list"],
        ["metrics", "catalog"],
        ["metrics", "for-resource", "source", "1"],
        ["metrics", "get", "source", "1", "records"],
        ["users", "list"],
        ["users", "get", "1"],
        ["notifications", "list"],
        ["orgs", "get", "1"],
    ],
)
def test_stub_command_fails_locally_without_network(
    runner: CliRunner,
    cli_app,
    respx_mock: respx.MockRouter,
    args: list[str],
) -> None:
    # A catch-all route that would answer if any request were made — the
    # command must fail *before* touching the network, so it stays uncalled.
    caught = respx_mock.route(host="api.test").mock(
        return_value=httpx.Response(200, json={})
    )
    result = runner.invoke(cli_app, args)
    assert result.exit_code == EXIT.ERROR
    assert "not available in this release" in result.stderr
    assert not caught.called, "stub command must not make a network call"


def test_hidden_groups_absent_from_help(runner: CliRunner, cli_app) -> None:
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    for hidden in ("code-containers", "metrics", "users", "notifications"):
        assert hidden not in result.stdout


def test_orgs_get_hidden_but_list_visible(runner: CliRunner, cli_app) -> None:
    result = runner.invoke(cli_app, ["orgs", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "get" not in result.stdout
