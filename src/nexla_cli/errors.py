"""Exit-code taxonomy + the CLI's structured error exception.

Agents branch on the numeric exit code, not on message text — keep this
table stable and documented in ``--help`` epilogs.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class EXIT(IntEnum):
    """Stable exit-code taxonomy for the `nexla` CLI.

    An ``IntEnum`` so members compare/serialize as their integer code
    (``EXIT.CONFIG == 3``, ``typer.Exit(EXIT.CONFIG)`` works) while giving
    readable reprs in tracebacks and logs.
    """

    OK = 0
    ERROR = 1  # generic / unexpected
    VALIDATION = 2  # bad local input (validation, dry-run failures)
    CONFIG = 3  # missing env / not configured
    AUTH = 4  # 401/403 from the API
    NOT_FOUND = 5  # 404
    UPSTREAM = 6  # 5xx / 502 gateway

    @staticmethod
    def from_status(code: int) -> EXIT:
        if code in (401, 403):
            return EXIT.AUTH
        if code == 404:
            return EXIT.NOT_FOUND
        if code >= 500:
            return EXIT.UPSTREAM
        return EXIT.ERROR

    @property
    def slug(self) -> str:
        """Stable machine-parseable name for this exit code (for JSON errors).

        Agents can branch on ``error_type`` without parsing message text or
        memorizing numbers. Kept in lockstep with the code so the two never
        disagree.
        """
        return self.name.lower()


class CliError(Exception):
    """Raised anywhere in the CLI to signal a specific exit code + message.

    Every ``app.command()`` callback is wrapped (see
    ``cli/__init__.py::_wrap_cli_error``) so this maps to ``typer.Exit(code)``
    with the message on stderr, regardless of entrypoint (installed console
    script or ``CliRunner.invoke`` in tests).
    """

    def __init__(
        self,
        code: int,
        message: str,
        *,
        envelope: dict[str, Any] | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.envelope = envelope
        # An optional next step for the caller (human or agent): the command to
        # run, the env var to set, the flag to add. Surfaced in the error output.
        self.hint = hint

    @property
    def error_type(self) -> str:
        """Machine-parseable error category, derived from the exit code."""
        try:
            return EXIT(self.code).slug
        except ValueError:
            return "error"
