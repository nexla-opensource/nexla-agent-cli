"""Subprocess-level machine-contract tests for the installed entrypoint.

The rest of the suite drives the CLI through Typer's ``CliRunner``, which
calls the command callbacks in-process and bypasses ``main()`` -- so it
never exercises argv reordering, real stdio wiring, ``SystemExit`` code
mapping, or the ``python -m nexla_cli`` / console-script boundary. These
tests invoke the CLI as a *real* child process (``sys.executable -m
nexla_cli``, which routes through the same ``main()`` as the ``nexla``
console script) and assert the documented machine contract end-to-end:

* exit codes match the taxonomy in ``errors.EXIT`` / the ``--help`` table,
* errors go to STDERR (never STDOUT), and JSON-mode errors stay parseable,
* STDOUT stays clean (empty on error, help-only on help),
* a Python traceback NEVER leaks into either stream.

Every case is hermetic: it either fails during local validation or during
the not-configured env check, both of which fire before any HTTP request.
NEXLA_* env vars are stripped from every child so no ambient credentials
can turn a "not configured" case into a live call.
"""

from __future__ import annotations

import json as jsonlib
import os
import subprocess
import sys

TRACEBACK_MARKER = "Traceback (most recent call last)"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m nexla_cli <args>`` with NEXLA_* stripped from env.

    Uses ``sys.executable`` (the venv running pytest, which has
    ``nexla_cli`` installed) so the child imports the same package under
    test without depending on the ``nexla-cli`` script being on PATH.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEXLA_")}
    return subprocess.run(
        [sys.executable, "-m", "nexla_cli", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def _assert_no_traceback(proc: subprocess.CompletedProcess[str]) -> None:
    assert TRACEBACK_MARKER not in proc.stdout, f"traceback leaked to STDOUT:\n{proc.stdout}"
    assert TRACEBACK_MARKER not in proc.stderr, f"traceback leaked to STDERR:\n{proc.stderr}"


def test_help_exits_zero_with_help_on_stdout_and_empty_stderr() -> None:
    proc = _run("--help")
    assert proc.returncode == 0
    assert "Usage:" in proc.stdout
    assert proc.stderr == ""
    _assert_no_traceback(proc)


def test_no_args_prints_help_to_stdout() -> None:
    """Bare `nexla-cli` is `no_args_is_help=True`: help goes to STDOUT (so a
    script piping it sees it), stderr stays empty, no traceback. This
    Click fork exits 2 for the no-args help path -- asserted as current,
    documented behavior."""
    proc = _run()
    assert proc.returncode == 2
    assert "Usage:" in proc.stdout
    assert proc.stderr == ""
    _assert_no_traceback(proc)


def test_malformed_config_json_exits_validation_clean_stderr() -> None:
    """A malformed `--config` fails local JSON parsing (exit 2) before any
    network call: clean error on STDERR, empty STDOUT, no traceback."""
    proc = _run(
        "sources", "create", "--name", "x", "--connector", "s3", "--config", "{bad", "--dry-run"
    )
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr != ""
    assert "config" in proc.stderr
    _assert_no_traceback(proc)


def test_params_without_equals_exits_validation_clean_stderr() -> None:
    """`--params` with no `=` is rejected during local validation (exit 2),
    before any network call."""
    proc = _run(
        "sources", "create", "--name", "x", "--connector", "s3", "--params", "noequals", "--dry-run"
    )
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "key=value" in proc.stderr
    _assert_no_traceback(proc)


def test_list_bad_output_mode_unconfigured_exits_before_network() -> None:
    """`sources list -o xml` with NEXLA_* unset: the not-configured check
    (exit 3) fires before mode validation would (mode is resolved only at
    emit time, after the request would have gone out) -- verified live.
    Either way it exits before any network call with no traceback; we
    assert the code that actually fires (3)."""
    proc = _run("sources", "list", "-o", "xml")
    assert proc.returncode == 3
    assert proc.stdout == ""
    assert proc.stderr != ""
    _assert_no_traceback(proc)


def test_json_mode_not_configured_emits_clean_json_envelope_on_stderr() -> None:
    """`--output json sources get 1` with NEXLA_* unset: exit 3 (not
    configured), and in json mode the error is a parseable JSON envelope on
    STDERR with STDOUT empty and no traceback."""
    proc = _run("--output", "json", "sources", "get", "1")
    assert proc.returncode == 3
    assert proc.stdout == ""
    envelope = jsonlib.loads(proc.stderr)
    assert {"error", "error_type", "detail"} <= set(envelope)
    assert envelope["error_type"] == "config"
    assert envelope["detail"]
    _assert_no_traceback(proc)
