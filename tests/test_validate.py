from __future__ import annotations

import io

import pytest
import respx
from typer.testing import CliRunner

from nexla_cli import validate
from nexla_cli.errors import EXIT, CliError

from .conftest import BASE_URL


@pytest.mark.parametrize("bad_id", ["1?x", "a\x01", "%2F", "a#b", "1?a=b", "a/b", "../x", "/etc"])
def test_resource_id_rejects_bad_input(bad_id: str) -> None:
    with pytest.raises(CliError) as exc:
        validate.resource_id(bad_id)
    assert exc.value.code == EXIT.VALIDATION


def test_resource_id_accepts_clean_input() -> None:
    assert validate.resource_id("abc-123") == "abc-123"


@pytest.mark.parametrize("bad_path", ["../etc", "../../etc/passwd", "a/../../b"])
def test_output_path_rejects_traversal(
    respx_mock: respx.MockRouter, bad_path: str
) -> None:
    with pytest.raises(CliError) as exc:
        validate.output_path(bad_path)
    assert exc.value.code == EXIT.VALIDATION
    # path validation never fires an HTTP call, by construction.
    assert respx_mock.calls.call_count == 0


def test_output_path_accepts_relative_path_within_cwd() -> None:
    p = validate.output_path("out.json")
    assert p.is_absolute()
    assert p.name == "out.json"


def test_scan_body_rejects_control_chars() -> None:
    with pytest.raises(CliError) as exc:
        validate.scan_body({"name": "a\x01b"})
    assert exc.value.code == EXIT.VALIDATION


def test_scan_body_rejects_ansi_escape_and_names_field_and_char() -> None:
    """A real ANSI escape sequence is still rejected, and the error names
    both the offending field and the codepoint -- not a bare opaque
    "control characters not allowed"."""
    with pytest.raises(CliError) as exc:
        validate.scan_body({"code": "print('x')\x1b[31mred\x1b[0m"})
    assert exc.value.code == EXIT.VALIDATION
    assert "code" in str(exc.value)
    assert "001B" in str(exc.value)


def test_scan_body_accepts_clean_body() -> None:
    assert validate.scan_body({"name": "clean", "count": 3}) == {"name": "clean", "count": 3}


def test_scan_body_accepts_multiline_code() -> None:
    """Transform source is authored by the user, not untrusted API-response
    data -- newlines/tabs/carriage returns must pass through so a normal
    multi-statement Python/SQL transform body doesn't need to be flattened
    into one semicolon-joined statement."""
    code = "def transform(record, *args):\n\tx = record['a'] + 1\n\treturn {'a': x}\r\n"
    assert validate.scan_body({"code": code})["code"] == code


def test_scan_body_rejects_control_char_nested_in_dict() -> None:
    """A control char buried inside a nested dict (e.g. a `--config` object)
    is rejected, not just top-level strings, and the error names a dotted
    path to the offending leaf."""
    with pytest.raises(CliError) as exc:
        validate.scan_body({"config": {"code": "print('x')\x1b[31m"}})
    assert exc.value.code == EXIT.VALIDATION
    assert "config.code" in str(exc.value)
    assert "001B" in str(exc.value)


def test_scan_body_rejects_control_char_nested_in_list_of_dicts() -> None:
    """A control char inside a list-of-dicts field (e.g.
    `credential_mappings[...]` / `rest.iterations[...]`) is rejected, with
    an indexed path naming the element."""
    with pytest.raises(CliError) as exc:
        validate.scan_body({"rest": {"iterations": [{"url": "ok"}, {"url": "bad\x00"}]}})
    assert exc.value.code == EXIT.VALIDATION
    assert "rest.iterations[1].url" in str(exc.value)


def test_scan_body_accepts_clean_nested_body() -> None:
    """A deeply nested but clean body passes through unchanged."""
    clean = {"config": {"opts": ["a", "b"], "n": 3}, "tags": ["x", "y"]}
    assert validate.scan_body(clean) == clean


def test_scan_body_allows_newline_in_nested_code_field() -> None:
    """Newlines/tabs/CR stay legal even when the `code` field is nested
    inside a `--config`-style object (transform source is user-authored)."""
    code = "def transform(r):\n\treturn r\r\n"
    body = {"config": {"code": code}}
    assert validate.scan_body(body)["config"]["code"] == code


def test_build_body_precedence_named_over_json_over_params() -> None:
    body = validate.build_body(
        {"name": "from-named"},
        '{"name": "from-json", "connector": "from-json"}',
        ["connector=from-params", "extra=1"],
    )
    # named opts win over --json; --json wins over --params; --params only
    # fills keys neither of the other two set.
    assert body == {"name": "from-named", "connector": "from-json", "extra": "1"}


def test_build_body_params_only_fill_gaps() -> None:
    body = validate.build_body({}, None, ["connector=s3", "kind=object_store"])
    assert body == {"connector": "s3", "kind": "object_store"}


def test_build_body_invalid_json_raises_validation() -> None:
    with pytest.raises(CliError) as exc:
        validate.build_body({}, "{not valid json", [])
    assert exc.value.code == EXIT.VALIDATION


def test_build_body_non_object_json_raises_validation() -> None:
    with pytest.raises(CliError) as exc:
        validate.build_body({}, "[1, 2, 3]", [])
    assert exc.value.code == EXIT.VALIDATION


def test_build_body_scans_merged_body_for_control_chars() -> None:
    with pytest.raises(CliError) as exc:
        validate.build_body({}, None, ["name=a\x01b"])
    assert exc.value.code == EXIT.VALIDATION


# ---- parse_json_arg (bug 2.1) ----------------------------------------------


def test_parse_json_arg_valid_object() -> None:
    assert validate.parse_json_arg("config", '{"a": 1}') == {"a": 1}


def test_parse_json_arg_valid_scalar_and_array() -> None:
    assert validate.parse_json_arg("input", "[1, 2]") == [1, 2]


def test_parse_json_arg_malformed_raises_clean_validation_error() -> None:
    """A malformed named-JSON option must fail as EXIT.VALIDATION (exit 2)
    naming the option -- not let json's exception bubble to a raw
    traceback (exit 1)."""
    with pytest.raises(CliError) as exc:
        validate.parse_json_arg("config", "{bad")
    assert exc.value.code == EXIT.VALIDATION
    assert "--config is not valid JSON" in str(exc.value)


# ---- build_body --params key=value guard (bug 2.7) -------------------------


def test_build_body_params_without_equals_raises_validation() -> None:
    with pytest.raises(CliError) as exc:
        validate.build_body({}, None, ["noequalskey"])
    assert exc.value.code == EXIT.VALIDATION
    assert "key=value" in str(exc.value)


def test_build_body_params_empty_value_after_equals_is_allowed() -> None:
    # `key=` (explicit empty value) stays valid -- only a *missing* `=` is
    # rejected; we don't second-guess a deliberately empty string value.
    assert validate.build_body({}, None, ["key="]) == {"key": ""}


@pytest.mark.parametrize("bad_id", ["1?x", "a\x01", "%2F", "a#b"])
def test_wired_command_rejects_bad_id_with_zero_http_calls(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter, bad_id: str
) -> None:
    """`connectors describe` runs its id through validate.resource_id before
    ever calling client.request — a bad id must exit 2 and fire no request."""
    from nexla_cli import app

    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    result = CliRunner().invoke(app, ["connectors", "describe", bad_id])
    assert result.exit_code == EXIT.VALIDATION
    assert respx_mock.calls.call_count == 0


def test_passthrough_json_and_params_merge_into_request_body(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    """--json/--params on a create command produce the merged body in the
    actual POST, per build_body's documented precedence."""
    import httpx

    from nexla_cli import app

    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    route = respx_mock.post(f"{BASE_URL}/nexla/credentials").mock(
        return_value=httpx.Response(201, json={"id": 1, "name": "x"})
    )
    result = CliRunner().invoke(
        app,
        [
            "credentials",
            "create",
            "--name",
            "x",
            "--connector",
            "s3",
            "--json",
            '{"name":"x","description":"from-json"}',
            "--params",
            "connector=ignored-lowest-precedence",
        ],
    )
    assert result.exit_code == 0
    assert route.called
    import json as jsonlib

    sent = jsonlib.loads(route.calls.last.request.content)
    # named --name/--connector win over --json; --json's description survives
    # since there's no named "description" option on this command's create.
    assert sent["name"] == "x"
    assert sent["connector"] == "s3"
    assert sent["description"] == "from-json"


# ---- @file / @- JSON payload sourcing ---------------------------------------


def test_parse_json_arg_at_file_reads_the_file(tmp_path) -> None:
    body = tmp_path / "body.json"
    body.write_text('{"a": 1}')
    assert validate.parse_json_arg("config", f"@{body}") == {"a": 1}


def test_parse_json_arg_at_dash_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO('{"from": "stdin"}'))
    assert validate.parse_json_arg("json", "@-") == {"from": "stdin"}


def test_parse_json_arg_at_missing_file_is_validation_error(tmp_path) -> None:
    with pytest.raises(CliError) as exc:
        validate.parse_json_arg("config", f"@{tmp_path / 'nope.json'}")
    assert exc.value.code == EXIT.VALIDATION
    assert "cannot read" in str(exc.value)


def test_parse_json_arg_at_file_with_invalid_json_is_validation_error(tmp_path) -> None:
    body = tmp_path / "bad.json"
    body.write_text("{not json")
    with pytest.raises(CliError) as exc:
        validate.parse_json_arg("config", f"@{body}")
    assert exc.value.code == EXIT.VALIDATION
    assert "--config is not valid JSON" in str(exc.value)


def test_parse_json_arg_inline_json_is_unchanged() -> None:
    # The `@` prefix is positional-only: literal JSON never starts with it.
    assert validate.parse_json_arg("config", '{"@weird": "@notafile"}') == {"@weird": "@notafile"}


def test_build_body_json_accepts_at_file(tmp_path) -> None:
    body = tmp_path / "b.json"
    body.write_text('{"name": "from-file"}')
    assert validate.build_body({}, f"@{body}", []) == {"name": "from-file"}


def test_build_body_named_still_beats_at_file_json(tmp_path) -> None:
    # `@file` only changes where the --json text comes from, never the
    # named > --json > --params precedence.
    body = tmp_path / "b.json"
    body.write_text('{"name": "from-file", "keep": 1}')
    assert validate.build_body({"name": "named"}, f"@{body}", ["name=param"]) == {
        "name": "named",
        "keep": 1,
    }
