"""Shared ``--wait-until`` polling for ``get`` commands on resources that
finish provisioning asynchronously.

``sources create``/``sinks create`` auto-activate but don't block on
activation (see AGENTS.md), and a transform's derived nexset takes a
moment to get real samples -- without this, a caller has to hand-write a
``for i in ...; do ...; sleep N; done`` bash loop around
``nexla-cli <resource> get <id>`` to wait for readiness. This gives that loop
a name instead of asking every caller to reinvent it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import typer

from .errors import EXIT, CliError

WAIT_TIMEOUT_OPT = typer.Option(300, "--wait-timeout", help="Max seconds to poll with --wait-until")
WAIT_INTERVAL_OPT = typer.Option(5, "--wait-interval", help="Seconds between polls with --wait-until")


def wait_until_option(example: str) -> Any:
    """Build a ``--wait-until`` option with a resource-specific example.

    A single shared example across sources/nexsets/sinks would show
    ``source_nexset_id`` on `nexsets get`, where that field doesn't even
    exist -- each caller passes the field that's actually relevant to it.
    """
    return typer.Option(
        None,
        "--wait-until",
        help=f"Poll until this dotted field is truthy, or 'field=value' for an exact "
        f"match (e.g. {example})",
    )


def _dotted_get(body: Any, field: str) -> Any:
    cur = body
    for part in field.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def poll_until(fetch: Callable[[], Any], condition: str, timeout: int, interval: int) -> Any:
    """Call ``fetch()`` repeatedly until ``condition`` is met or ``timeout`` elapses.

    ``condition`` is a dotted field name (waits for a truthy/non-empty
    value) or ``field=value`` for an exact string match. Raises
    :class:`CliError` (exit ``EXIT.ERROR``) on timeout, including the last
    observed value so the caller knows how far it got.
    """
    field, sep, expected = condition.partition("=")
    deadline = time.monotonic() + timeout
    while True:
        body = fetch()
        value = _dotted_get(body, field)
        met = (str(value) == expected) if sep else bool(value)
        if met:
            return body
        if time.monotonic() >= deadline:
            raise CliError(
                EXIT.ERROR,
                f"timed out after {timeout}s waiting for {condition!r} (last value: {value!r})",
            )
        time.sleep(interval)
