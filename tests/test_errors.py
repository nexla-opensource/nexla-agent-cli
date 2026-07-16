from __future__ import annotations

from nexla_cli.errors import EXIT, CliError


def test_from_status_mapping() -> None:
    assert EXIT.from_status(401) == EXIT.AUTH
    assert EXIT.from_status(403) == EXIT.AUTH
    assert EXIT.from_status(404) == EXIT.NOT_FOUND
    assert EXIT.from_status(500) == EXIT.UPSTREAM
    assert EXIT.from_status(502) == EXIT.UPSTREAM
    assert EXIT.from_status(400) == EXIT.ERROR
    assert EXIT.from_status(422) == EXIT.ERROR


def test_cli_error_carries_code_message_envelope() -> None:
    err = CliError(EXIT.NOT_FOUND, "missing", envelope={"error": "not_found"})
    assert err.code == EXIT.NOT_FOUND
    assert err.message == "missing"
    assert err.envelope == {"error": "not_found"}
    assert str(err) == "missing"
