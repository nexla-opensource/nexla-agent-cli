from __future__ import annotations

import json as jsonlib

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_list(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"id": 1, "name": "s1", "status": "ACTIVE", "connector": "gdrive"}],
                "page": 1,
                "per_page": 50,
                "next_page": None,
            },
        )
    )
    result = runner.invoke(cli_app, ["sources", "list"])
    assert result.exit_code == 0
    assert route.calls.last.request.method == "GET"
    assert route.calls.last.request.url.path == "/nexla/sources"
    assert "s1" in result.stdout


def test_get(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "s1", "status": "ACTIVE"})
    )
    result = runner.invoke(cli_app, ["sources", "get", "1"])
    assert result.exit_code == 0
    assert route.called
    assert "s1" in result.stdout


def test_get_wait_until_polls_until_field_appears(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setattr("nexla_cli.poll.time.sleep", lambda s: None)
    route = respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        side_effect=[
            httpx.Response(200, json={"id": 1, "source_nexset_id": None}),
            httpx.Response(200, json={"id": 1, "source_nexset_id": 42}),
        ]
    )
    result = runner.invoke(
        cli_app, ["sources", "get", "1", "--wait-until", "source_nexset_id", "--wait-interval", "0"]
    )
    assert result.exit_code == 0
    assert route.call_count == 2
    assert "42" in result.stdout


def test_get_not_found(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE_URL}/nexla/sources/99").mock(
        return_value=httpx.Response(404, json={"detail": {"error": "not_found"}})
    )
    result = runner.invoke(cli_app, ["sources", "get", "99"])
    assert result.exit_code == 5  # EXIT.NOT_FOUND


def test_create(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(201, json={"id": 5, "name": "new-src", "status": "ACTIVE"})
    )
    result = runner.invoke(
        cli_app,
        [
            "sources",
            "create",
            "--name",
            "new-src",
            "--connector",
            "webhook",
            "--config",
            "{}",
        ],
    )
    assert result.exit_code == 0
    assert route.called
    body = respx_mock.calls.last.request.content
    assert b"new-src" in body
    assert "new-src" in result.stdout


def test_update(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.patch(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "renamed", "status": "ACTIVE"})
    )
    # read-after-write verification (on by default) re-GETs and sees the change
    respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "renamed", "status": "ACTIVE"})
    )
    result = runner.invoke(cli_app, ["sources", "update", "1", "--name", "renamed"])
    assert result.exit_code == 0
    assert route.called


def test_update_verify_readback_reflects_change(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Update whose read-back reflects the change -> exit 0, no warning."""
    respx_mock.patch(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "renamed", "status": "ACTIVE"})
    )
    get_route = respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "renamed", "status": "ACTIVE"})
    )
    result = runner.invoke(cli_app, ["sources", "update", "1", "--name", "renamed"])
    assert result.exit_code == 0
    assert get_route.called
    assert "did not persist" not in result.stderr


def test_update_verify_warns_when_name_did_not_persist(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """PATCH returns 200 but read-back still shows the OLD name -> warn + nonzero."""
    respx_mock.patch(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "renamed", "status": "ACTIVE"})
    )
    get_route = respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "old-name", "status": "ACTIVE"})
    )
    result = runner.invoke(cli_app, ["sources", "update", "1", "--name", "renamed"])
    assert result.exit_code == 1  # EXIT.ERROR
    assert get_route.called
    assert "name" in result.stderr
    assert "did not persist" in result.stderr


def test_update_verify_config_reshaped_no_false_warning(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Config value present-but-reshaped in read-back -> no false warning (lenient)."""
    respx_mock.patch(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "status": "ACTIVE"})
    )
    # server nests the requested config under template_config with prefixed
    # keys -- the value "s3://bucket/path" survives but is reshaped/rekeyed.
    get_route = respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "status": "ACTIVE",
                "template_config": {"source.path": "s3://bucket/path"},
            },
        )
    )
    result = runner.invoke(
        cli_app,
        ["sources", "update", "1", "--config", '{"path": "s3://bucket/path"}'],
    )
    assert result.exit_code == 0
    assert get_route.called
    assert "did not persist" not in result.stderr


def test_update_no_verify_skips_readback(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """--no-verify -> no follow-up GET fired, exit 0."""
    respx_mock.patch(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "renamed", "status": "ACTIVE"})
    )
    get_route = respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "old-name"})
    )
    result = runner.invoke(
        cli_app, ["sources", "update", "1", "--name", "renamed", "--no-verify"]
    )
    assert result.exit_code == 0
    assert not get_route.called


def test_update_dry_run_fires_no_patch_or_get(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    """--dry-run -> no PATCH, no read-after-write GET."""
    monkeypatch.setattr(
        "nexla_cli.dryrun.openapi_client.fetch_openapi", lambda: {"paths": {}}
    )
    monkeypatch.setattr(
        "nexla_cli.dryrun.openapi_client.resolve",
        lambda spec, resource, verb: {"operation": {}},
    )
    monkeypatch.setattr(
        "nexla_cli.dryrun.openapi_client.request_body_schema", lambda spec, op: None
    )
    patch_route = respx_mock.patch(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    get_route = respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(
        cli_app, ["sources", "update", "1", "--name", "renamed", "--dry-run"]
    )
    assert result.exit_code == 0
    assert not patch_route.called
    assert not get_route.called


def test_activate(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/sources/1/activate").mock(
        return_value=httpx.Response(200, json={"id": 1, "status": "ACTIVE"})
    )
    result = runner.invoke(cli_app, ["sources", "activate", "1"])
    assert result.exit_code == 0
    assert route.called


def test_pause(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/sources/1/pause").mock(
        return_value=httpx.Response(200, json={"id": 1, "status": "PAUSED"})
    )
    result = runner.invoke(cli_app, ["sources", "pause", "1"])
    assert result.exit_code == 0
    assert route.called


def test_delete(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.delete(f"{BASE_URL}/nexla/sources/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["sources", "delete", "1"])
    assert result.exit_code == 0
    assert route.called
    assert "deleted" in result.stdout and "true" in result.stdout


def test_delete_force_pauses_first(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # --force pauses before deleting (the API refuses to delete an active source).
    pause = respx_mock.post(f"{BASE_URL}/nexla/sources/1/pause").mock(
        return_value=httpx.Response(200, json={"id": 1, "status": "PAUSED"})
    )
    delete = respx_mock.delete(f"{BASE_URL}/nexla/sources/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["sources", "delete", "1", "--force"])
    assert result.exit_code == 0
    assert pause.called and delete.called
    assert "deleted" in result.stdout


def test_delete_without_force_does_not_pause(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    pause = respx_mock.post(f"{BASE_URL}/nexla/sources/1/pause").mock(
        return_value=httpx.Response(200, json={})
    )
    respx_mock.delete(f"{BASE_URL}/nexla/sources/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["sources", "delete", "1"])
    assert result.exit_code == 0
    assert not pause.called


def test_sample(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/sources/1/sample").mock(
        return_value=httpx.Response(200, json={"dataset_id": 9, "processed": 1})
    )
    result = runner.invoke(cli_app, ["sources", "sample", "1", "--payload", '{"a": 1}'])
    assert result.exit_code == 0
    assert route.called


def test_file_upload(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/sources/1/file_upload").mock(
        return_value=httpx.Response(200, json={"uploaded": [], "failed": []})
    )
    result = runner.invoke(
        cli_app,
        ["sources", "file-upload", "1", "--sandbox", "sbx-1", "--path", "/workspace/a.csv"],
    )
    assert result.exit_code == 0
    assert route.called
    assert jsonlib.loads(route.calls.last.request.content) == {
        "sandbox_id": "sbx-1",
        "files": [{"path": "/workspace/a.csv"}],
    }


def test_file_upload_requires_sandbox(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Without --sandbox the CLI refuses to fire (no arbitrary-sandbox call)."""
    route = respx_mock.post(f"{BASE_URL}/nexla/sources/1/file_upload").mock(
        return_value=httpx.Response(200, json={})
    )
    result = runner.invoke(
        cli_app, ["sources", "file-upload", "1", "--path", "/workspace/a.csv"]
    )
    assert result.exit_code == 3  # EXIT.CONFIG
    assert not route.called


def test_list_page_all_streams_ndjson_past_a_full_page(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Boundary case: a page exactly `per_page` long is not the last page.

    Mirrors a real 51-source org with the default ``--per-page 50``: page 1
    is a full 50-item page with ``next_page=2``, page 2 has the trailing 1
    item and ``next_page=None``. A ``len(batch) < per_page`` heuristic would
    stop after page 1 and silently drop the last item; ``client.paginate``
    drives off ``next_page`` instead (see ``test_client.py``), but that's
    only unit-tested at the ``client.paginate`` level — this exercises the
    full command wiring through ``sources list --page-all``.
    """
    respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "items": [
                        {"id": i, "name": f"s{i}", "status": "ACTIVE", "connector": "s3"}
                        for i in range(1, 51)
                    ],
                    "page": 1,
                    "per_page": 50,
                    "next_page": 2,
                },
            ),
            httpx.Response(
                200,
                json={
                    "items": [{"id": 51, "name": "s51", "status": "ACTIVE", "connector": "s3"}],
                    "page": 2,
                    "per_page": 50,
                    "next_page": None,
                },
            ),
        ]
    )
    result = runner.invoke(cli_app, ["--output", "ndjson", "--page-all", "sources", "list"])
    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line]
    assert len(lines) == 51
    ids = [jsonlib.loads(line)["id"] for line in lines]
    assert ids == list(range(1, 52))


def test_list_page_all_forwards_filters_across_pages(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/sources").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "items": [{"id": 1, "name": "s1", "status": "ACTIVE", "connector": "s3"}],
                    "page": 1,
                    "per_page": 2,
                    "next_page": 2,
                },
            ),
            httpx.Response(
                200,
                json={
                    "items": [{"id": 2, "name": "s2", "status": "ACTIVE", "connector": "s3"}],
                    "page": 2,
                    "per_page": 2,
                    "next_page": None,
                },
            ),
        ]
    )
    result = runner.invoke(
        cli_app,
        ["--output", "ndjson", "--page-all", "sources", "list", "--connector", "s3", "--per-page", "2"],
    )
    assert result.exit_code == 0
    assert route.call_count == 2
    for call in route.calls:
        assert call.request.url.params["connector"] == "s3"


def test_missing_env_maps_to_config_exit(cli_app) -> None:
    result = CliRunner().invoke(cli_app, ["sources", "list"], env={"NEXLA_API_URL": "", "NEXLA_TOKEN": ""})
    assert result.exit_code == 3  # EXIT.CONFIG
