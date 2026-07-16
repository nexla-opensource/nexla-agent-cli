from __future__ import annotations

import json

import httpx
import pytest
import respx

from nexla_cli import client
from nexla_cli.errors import EXIT, CliError

BASE_URL = "https://api.test"


def test_timeout_defaults_to_30(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXLA_TIMEOUT", raising=False)
    assert client.timeout() == 30.0


def test_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_TIMEOUT", "5")
    assert client.timeout() == 5.0


@pytest.mark.parametrize("bad", ["abc", "0", "-3"])
def test_timeout_invalid_raises_config(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("NEXLA_TIMEOUT", bad)
    with pytest.raises(CliError) as exc:
        client.timeout()
    assert exc.value.code == EXIT.CONFIG


def test_base_missing_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXLA_API_URL", raising=False)
    with pytest.raises(CliError) as exc:
        client.request("GET", "/nexla/sources")
    assert exc.value.code == EXIT.CONFIG


def test_token_missing_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.delenv("NEXLA_TOKEN", raising=False)
    with pytest.raises(CliError) as exc:
        client.request("GET", "/nexla/sources")
    assert exc.value.code == EXIT.CONFIG


def test_require_auth_false_skips_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.delenv("NEXLA_TOKEN", raising=False)
    with respx.mock:
        route = respx.post(f"{BASE_URL}/login").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = client.request("POST", "/login", json={"service_key": "x"}, require_auth=False)
    assert result == {"ok": True}
    assert route.calls.last.request.headers.get("authorization") is None


def test_success_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    with respx.mock:
        respx.get(f"{BASE_URL}/nexla/sources/1").mock(
            return_value=httpx.Response(200, json={"id": 1})
        )
        result = client.request("GET", "/nexla/sources/1")
    assert result == {"id": 1}


def test_204_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    with respx.mock:
        respx.delete(f"{BASE_URL}/nexla/sources/1").mock(return_value=httpx.Response(204))
        result = client.request("DELETE", "/nexla/sources/1")
    assert result is None


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [(401, EXIT.AUTH), (403, EXIT.AUTH), (404, EXIT.NOT_FOUND), (500, EXIT.UPSTREAM), (502, EXIT.UPSTREAM)],
)
def test_failure_status_maps_to_exit_code(
    monkeypatch: pytest.MonkeyPatch, status: int, expected_exit: int
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    with respx.mock:
        respx.get(f"{BASE_URL}/nexla/sources/1").mock(
            return_value=httpx.Response(status, json={"detail": {"error": "boom"}})
        )
        with pytest.raises(CliError) as exc:
            client.request("GET", "/nexla/sources/1")
    assert exc.value.code == expected_exit


def test_network_error_maps_to_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    with respx.mock:
        respx.get(f"{BASE_URL}/nexla/sources/1").mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(CliError) as exc:
            client.request("GET", "/nexla/sources/1")
    assert exc.value.code == EXIT.UPSTREAM


def test_2xx_non_json_body_raises_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    with respx.mock:
        respx.get(f"{BASE_URL}/nexla/sources/1").mock(
            return_value=httpx.Response(
                200, text="<html>gateway error</html>", headers={"content-type": "text/html"}
            )
        )
        with pytest.raises(CliError) as exc:
            client.request("GET", "/nexla/sources/1")
    assert exc.value.code == EXIT.UPSTREAM
    assert "non-JSON response" in exc.value.message
    assert "/nexla/sources/1" in exc.value.message


def test_2xx_non_json_excerpt_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    with respx.mock:
        respx.get(f"{BASE_URL}/nexla/sources/1").mock(
            return_value=httpx.Response(200, text="x" * 5000)
        )
        with pytest.raises(CliError) as exc:
            client.request("GET", "/nexla/sources/1")
    # Full 5000-char body must not be echoed back — excerpt bounded to ~200
    # chars, so the whole message stays far short of the 5000-char body.
    assert len(exc.value.message) < 300


def test_paginate_streams_all_pages_and_forwards_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    pages = [
        httpx.Response(
            200, json={"items": [{"id": i} for i in range(100)], "next_page": 2}
        ),
        httpx.Response(
            200, json={"items": [{"id": i} for i in range(100, 200)], "next_page": 3}
        ),
        httpx.Response(
            200, json={"items": [{"id": i} for i in range(200, 240)], "next_page": None}
        ),
    ]
    with respx.mock:
        route = respx.get(f"{BASE_URL}/nexla/sources").mock(side_effect=pages)
        items = list(
            client.paginate("/nexla/sources", params={"connector": "s3"}, per_page=100)
        )
    assert len(items) == 240
    assert route.call_count == 3  # no 4th request once next_page is null
    for i, call in enumerate(route.calls, start=1):
        query = dict(httpx.QueryParams(call.request.url.query))
        assert query["connector"] == "s3"
        assert query["page"] == str(i)
        assert query["per_page"] == "100"


def test_paginate_warns_on_server_side_truncation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    pages = [
        httpx.Response(
            200, json={"items": [{"id": i} for i in range(100)], "next_page": 2}
        ),
        httpx.Response(
            200,
            json={
                "items": [{"id": i} for i in range(100, 150)],
                "next_page": None,
                "truncated": True,
            },
        ),
    ]
    with respx.mock:
        respx.get(f"{BASE_URL}/nexla/sources").mock(side_effect=pages)
        items = list(client.paginate("/nexla/sources", per_page=100))
    # All items across pages are still yielded — stream shape unchanged.
    assert len(items) == 150
    captured = capsys.readouterr()
    # Human surfacing: a WARNING on stderr.
    assert "truncated" in captured.err
    assert "/nexla/sources" in captured.err
    # Machine surfacing: a final NDJSON metadata record on stdout, strictly
    # last, flagging truncation without polluting the item stream.
    out_lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(out_lines) == 1
    meta = json.loads(out_lines[0])
    assert meta == {
        "_meta": "truncation",
        "truncated": True,
        "path": "/nexla/sources",
        "message": "results were truncated server-side and may be incomplete",
    }


def test_paginate_truncation_flagged_on_non_final_page(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Credential filtering can flag ``truncated`` on an early page while still
    # returning a ``next_page`` — the signal must latch and survive to the end.
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    pages = [
        httpx.Response(
            200,
            json={
                "items": [{"id": i} for i in range(100)],
                "next_page": 2,
                "truncated": True,
            },
        ),
        httpx.Response(
            200,
            json={"items": [{"id": i} for i in range(100, 130)], "next_page": None},
        ),
    ]
    with respx.mock:
        respx.get(f"{BASE_URL}/nexla/sources").mock(side_effect=pages)
        items = list(client.paginate("/nexla/sources", per_page=100))
    assert len(items) == 130
    captured = capsys.readouterr()
    assert "truncated" in captured.err
    meta = json.loads([ln for ln in captured.out.splitlines() if ln.strip()][0])
    assert meta["_meta"] == "truncation"
    assert meta["truncated"] is True


def test_paginate_no_warning_when_not_truncated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    with respx.mock:
        respx.get(f"{BASE_URL}/nexla/sources").mock(
            return_value=httpx.Response(
                200, json={"items": [{"id": 1}], "next_page": None}
            )
        )
        items = list(client.paginate("/nexla/sources", per_page=100))
    assert len(items) == 1
    assert capsys.readouterr().err == ""
