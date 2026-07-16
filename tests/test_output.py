from __future__ import annotations

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nexla_cli import output

from .conftest import BASE_URL


def test_emit_none_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    output.emit(None)
    assert capsys.readouterr().out == ""


def test_emit_unwraps_page_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    page = {"items": [{"id": 1, "name": "a"}], "page": 1, "per_page": 50, "next_page": None}
    output.emit(page, columns=["id", "name"])
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].split() == ["ID", "NAME"]
    assert lines[1].split() == ["1", "a"]


def test_emit_empty_list(capsys: pytest.CaptureFixture[str]) -> None:
    output.emit({"items": [], "page": 1, "per_page": 50})
    assert "(no results)" in capsys.readouterr().out


def test_emit_dict_renders_kv(capsys: pytest.CaptureFixture[str]) -> None:
    output.emit({"id": 1, "name": "widget"})
    out = capsys.readouterr().out
    assert "id" in out and "1" in out
    assert "name" in out and "widget" in out


def test_emit_empty_dict(capsys: pytest.CaptureFixture[str]) -> None:
    output.emit({})
    assert "(empty)" in capsys.readouterr().out


def test_emit_bare_list_not_wrapped(capsys: pytest.CaptureFixture[str]) -> None:
    # orgs.list returns a bare array, not a Page[T] envelope.
    output.emit([{"id": 1, "name": "org1"}], columns=["id", "name"])
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].split() == ["ID", "NAME"]
    assert lines[1].split() == ["1", "org1"]


def test_emit_ndjson_mode_one_line_per_item(capsys: pytest.CaptureFixture[str]) -> None:
    output.emit([{"id": 1}, {"id": 2}], mode="ndjson")
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line) for line in lines] == [{"id": 1}, {"id": 2}]


def test_emit_json_mode_preserves_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    page = {"items": [{"id": 1}], "page": 1, "per_page": 50, "next_page": None}
    output.emit(page, mode="json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["items"] == [{"id": 1}]
    assert payload["next_page"] is None


def test_emit_fields_mask_keeps_only_requested_keys(capsys: pytest.CaptureFixture[str]) -> None:
    output.emit({"id": 1, "name": "a", "status": "ACTIVE"}, mode="json", fields=["id", "name"])
    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {"id", "name"}


def test_emit_fields_mask_omits_absent_field(capsys: pytest.CaptureFixture[str]) -> None:
    # A requested field that doesn't exist is omitted, not emitted as null.
    output.emit({"id": 1, "connector": "s3"}, mode="json", fields=["id", "connector_type"])
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"id": 1}


def test_emit_fields_mask_table_uses_only_requested_columns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Table mode must honor --fields as the column set, not render the full
    # fixed `columns` with blank cells for the masked-out keys.
    output.emit(
        {"items": [{"id": 1, "name": "a", "connector": "s3", "kind": "file"}]},
        mode="table",
        columns=["id", "name", "connector", "kind"],
        fields=["id", "name"],
    )
    header = capsys.readouterr().out.strip().splitlines()[0].split()
    assert header == ["ID", "NAME"]


def test_resolve_mode_rejects_invalid_flag() -> None:
    from nexla_cli.errors import EXIT, CliError

    with pytest.raises(CliError) as exc:
        output.resolve_mode("xml")
    assert exc.value.code == EXIT.VALIDATION
    assert "xml" in exc.value.message


def test_resolve_mode_rejects_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexla_cli.errors import CliError

    monkeypatch.setenv("NEXLA_OUTPUT", "yaml")
    with pytest.raises(CliError):
        output.resolve_mode(None)


@pytest.mark.parametrize(
    ("flag", "env", "isatty", "expected"),
    [
        (None, None, True, "table"),
        (None, None, False, "json"),
        (None, "ndjson", True, "ndjson"),  # env overrides TTY autodetect
        ("table", "ndjson", False, "table"),  # explicit flag overrides everything
    ],
)
def test_resolve_mode_precedence(
    monkeypatch: pytest.MonkeyPatch,
    flag: str | None,
    env: str | None,
    isatty: bool,
    expected: str,
) -> None:
    monkeypatch.delenv("NEXLA_OUTPUT", raising=False)
    monkeypatch.delenv("OUTPUT_FORMAT", raising=False)
    if env is not None:
        monkeypatch.setenv("NEXLA_OUTPUT", env)
    monkeypatch.setattr(output.sys.stdout, "isatty", lambda: isatty)
    assert output.resolve_mode(flag) == expected


def test_golden_output_table_vs_json(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    from nexla_cli import app

    items = [{"id": 1, "name": "s1", "status": "ACTIVE", "connector": "gdrive"}]
    page = {"items": items, "page": 1, "per_page": 50, "next_page": None}
    respx_mock.get(f"{BASE_URL}/nexla/sources").mock(return_value=httpx.Response(200, json=page))

    runner = CliRunner()
    # force table explicitly: CliRunner's captured stdout isn't a TTY, so the
    # zero-flag default here is json (agent-native) — see the TTY-default test.
    table_result = runner.invoke(app, ["--output", "table", "sources", "list"])
    assert table_result.exit_code == 0
    assert "ID" in table_result.stdout and "s1" in table_result.stdout

    respx_mock.get(f"{BASE_URL}/nexla/sources").mock(return_value=httpx.Response(200, json=page))
    json_result = runner.invoke(app, ["--output", "json", "sources", "list"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["items"] == items


def test_page_all_streams_ndjson_across_three_pages(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    from nexla_cli import app

    pages = [
        httpx.Response(200, json={"items": [{"id": i} for i in range(100)], "next_page": 2}),
        httpx.Response(200, json={"items": [{"id": i} for i in range(100, 200)], "next_page": 3}),
        httpx.Response(200, json={"items": [{"id": i} for i in range(200, 240)], "next_page": None}),
    ]
    route = respx_mock.get(f"{BASE_URL}/nexla/sources").mock(side_effect=pages)

    result = CliRunner().invoke(app, ["--page-all", "sources", "list"])
    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 240
    for line in lines:
        json.loads(line)  # each NDJSON line parses independently
    assert route.call_count == 3  # no 4th request once next_page is null


def test_fields_mask_shrinks_list_and_get_output(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    from nexla_cli import app

    runner = CliRunner()

    page = {
        "items": [{"id": 1, "name": "s1", "status": "ACTIVE", "connector": "gdrive"}],
        "page": 1,
        "per_page": 50,
        "next_page": None,
    }
    respx_mock.get(f"{BASE_URL}/nexla/sources").mock(return_value=httpx.Response(200, json=page))
    list_result = runner.invoke(app, ["--output", "json", "--fields", "id,name", "sources", "list"])
    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.stdout)
    assert set(list_payload["items"][0].keys()) == {"id", "name"}

    respx_mock.get(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "s1", "status": "ACTIVE"})
    )
    get_result = runner.invoke(app, ["--output", "json", "--fields", "id,name", "sources", "get", "1"])
    assert get_result.exit_code == 0
    get_payload = json.loads(get_result.stdout)
    assert set(get_payload.keys()) == {"id", "name"}


def test_json_mode_error_envelope(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    monkeypatch.setenv("NEXLA_OUTPUT", "json")
    from nexla_cli import app

    respx_mock.get(f"{BASE_URL}/nexla/sources/99").mock(
        return_value=httpx.Response(404, json={"detail": {"error": "not_found"}})
    )
    result = CliRunner().invoke(app, ["sources", "get", "99"])
    assert result.exit_code == 5  # EXIT.NOT_FOUND
    payload = json.loads(result.stderr)
    assert payload["error"] == {"error": "not_found"}
    assert "detail" in payload


def test_emit_sanitizes_ansi_and_zero_width_chars_in_every_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    dirty = {"id": 1, "name": "s\x1b[31m1" + chr(0x200B) + "hidden"}

    output.emit(dirty, mode="json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "s1hidden"

    output.emit(dirty, mode="ndjson")
    line = capsys.readouterr().out.strip()
    assert json.loads(line)["name"] == "s1hidden"

    output.emit(dirty, mode="table")
    assert "\x1b[31m" not in capsys.readouterr().out


def test_table_mode_error_stays_plain_text(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    monkeypatch.setenv("NEXLA_OUTPUT", "table")  # force table mode, independent of TTY autodetect
    from nexla_cli import app

    respx_mock.get(f"{BASE_URL}/nexla/sources/99").mock(
        return_value=httpx.Response(404, json={"detail": {"error": "not_found"}})
    )
    result = CliRunner().invoke(app, ["sources", "get", "99"])
    assert result.exit_code == 5
    assert result.stderr.startswith("error: ")


# An upstream API error body is untrusted data, exactly like a success body.
# The `\x1b[31m` ANSI escape and the zero-width space (0x200B) must be
# stripped from both `error` (the raw envelope) and `detail` (the derived
# message) before they reach the terminal, in every output mode.
_DIRTY_ERROR = "not_found" + "\x1b[31m" + chr(0x200B) + "hidden"
_CLEAN_ERROR = "not_foundhidden"


def test_json_mode_error_envelope_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    monkeypatch.setenv("NEXLA_OUTPUT", "json")
    from nexla_cli import app

    respx_mock.get(f"{BASE_URL}/nexla/sources/99").mock(
        return_value=httpx.Response(404, json={"detail": {"error": _DIRTY_ERROR}})
    )
    result = CliRunner().invoke(app, ["sources", "get", "99"])
    assert result.exit_code == 5  # EXIT.NOT_FOUND
    # No hidden/control chars survive anywhere in the emitted stderr.
    assert "\x1b" not in result.stderr and chr(0x200B) not in result.stderr
    payload = json.loads(result.stderr)
    assert payload["error"] == {"error": _CLEAN_ERROR}  # nested envelope sanitized
    assert payload["detail"] == _CLEAN_ERROR  # derived message sanitized


def test_table_mode_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    monkeypatch.setenv("NEXLA_OUTPUT", "table")
    from nexla_cli import app

    respx_mock.get(f"{BASE_URL}/nexla/sources/99").mock(
        return_value=httpx.Response(404, json={"detail": {"error": _DIRTY_ERROR}})
    )
    result = CliRunner().invoke(app, ["sources", "get", "99"])
    assert result.exit_code == 5
    assert result.stderr.startswith("error: ")
    assert "\x1b" not in result.stderr and chr(0x200B) not in result.stderr
    assert _CLEAN_ERROR in result.stderr
