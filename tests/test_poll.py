from __future__ import annotations

import pytest

from nexla_cli.errors import CliError
from nexla_cli.poll import poll_until


def test_poll_until_truthy_field_returns_immediately() -> None:
    body = {"id": 1, "source_nexset_id": 42}
    assert poll_until(lambda: body, "source_nexset_id", timeout=5, interval=0) == body


def test_poll_until_truthy_field_waits_for_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter([{"source_nexset_id": None}, {"source_nexset_id": None}, {"source_nexset_id": 7}])
    sleeps: list[float] = []
    monkeypatch.setattr("nexla_cli.poll.time.sleep", lambda s: sleeps.append(s))
    result = poll_until(lambda: next(calls), "source_nexset_id", timeout=5, interval=1)
    assert result == {"source_nexset_id": 7}
    assert sleeps == [1, 1]


def test_poll_until_exact_match(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter([{"runtime_status": "IDLE"}, {"runtime_status": "ACTIVE"}])
    monkeypatch.setattr("nexla_cli.poll.time.sleep", lambda s: None)
    result = poll_until(lambda: next(calls), "runtime_status=ACTIVE", timeout=5, interval=1)
    assert result == {"runtime_status": "ACTIVE"}


def test_poll_until_dotted_field() -> None:
    body = {"status": {"phase": "done"}}
    assert poll_until(lambda: body, "status.phase=done", timeout=5, interval=1) == body


def test_poll_until_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([0.0, 0.0, 10.0])  # deadline computed from the first tick, exceeded on the third
    monkeypatch.setattr("nexla_cli.poll.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("nexla_cli.poll.time.sleep", lambda s: None)
    with pytest.raises(CliError) as exc_info:
        poll_until(lambda: {"source_nexset_id": None}, "source_nexset_id", timeout=5, interval=1)
    assert exc_info.value.code == 1
    assert "timed out after 5s" in exc_info.value.message
