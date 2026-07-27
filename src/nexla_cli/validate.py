"""Trust-boundary input validation + raw-payload passthrough merging.

Every function here raises :class:`~nexla_cli.errors.CliError` with
``EXIT.VALIDATION`` (exit code 2) on bad input, and fires **zero** HTTP
calls in that case — validation happens before any request leaves the
process, not after a round trip to the API.

``build_body`` lives here (rather than in ``client.py``) because its
merged output is immediately routed through ``scan_body`` before any
create/update command fires its request — the passthrough helper and the
validator it depends on belong in the same module.
"""

from __future__ import annotations

import json as jsonlib
import sys
from pathlib import Path
from typing import Any

import typer

# `ParameterSource` lets us tell a caller-supplied value from a default.
# Typer 0.26+ vendors Click privately as `typer._click` (no standalone
# `click`); earlier Typers / mixed envs expose it at `click.core`. Prefer
# the public symbol, fall back to Typer's vendored fork. See the fuller note
# in ``nexla_cli.__init__``.
try:
    # `click` is often absent (Typer 0.26+ vendors it), so mypy can't resolve
    # this branch statically; the except branch is the one that binds here.
    from click.core import ParameterSource  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on which Typer is installed
    from typer._click.core import ParameterSource

from .errors import EXIT, CliError


def resource_id(raw: str) -> str:
    """Validate a resource id/name interpolated directly into a URL path.

    Rejects control characters, ``?``/``#`` (which would truncate or
    redirect the path when concatenated into an f-string URL), and any
    ``%`` (refused outright rather than guessing whether it's already
    percent-encoded, to avoid double-encoding).
    """
    if any(ord(c) < 0x20 for c in raw):
        raise CliError(EXIT.VALIDATION, "control characters not allowed in id")
    if "?" in raw or "#" in raw:
        raise CliError(EXIT.VALIDATION, "id must not contain '?' or '#'")
    if "/" in raw:
        raise CliError(EXIT.VALIDATION, "id must not contain '/'")
    if "%" in raw:
        raise CliError(EXIT.VALIDATION, "id must not be URL-encoded")
    return raw


def read_json_arg(name: str, raw: str) -> str:
    """Resolve a JSON option's value to literal JSON text, honoring ``@``.

    ``@/path/to/body.json`` reads the file, ``@-`` reads STDIN, anything
    else is already literal JSON and is returned unchanged. Agents driving
    the CLI hit argv length limits and shell-quoting hazards passing a
    non-trivial body inline; the ``@`` prefix is the long-standing curl
    convention for exactly that. Only the *first* character is special, so
    a literal JSON body (which always starts with ``{``/``[``/``"``/a
    digit) can never be mistaken for a file reference.
    """
    if not raw.startswith("@"):
        return raw
    ref = raw[1:]
    if ref == "-":
        return sys.stdin.read()
    try:
        return Path(ref).read_text()
    except OSError as e:
        raise CliError(EXIT.VALIDATION, f"--{name}: cannot read {ref}: {e.strerror}") from e


def parse_json_arg(name: str, raw: str) -> Any:
    """Parse a named JSON CLI option's value, failing cleanly on bad input.

    Command bodies that feed a ``--config``/``--options``/``--payload``/etc.
    string straight into :func:`json.loads` would otherwise leak a raw
    Python traceback (exit 1) on malformed JSON. Routing every such call
    site through this helper turns that into a clean
    ``EXIT.VALIDATION`` (exit 2) error naming the offending option --
    mirroring how ``build_body`` already handles ``--json``.

    The value is first passed through :func:`read_json_arg`, so every
    option routed through here accepts ``@file`` / ``@-`` for free.
    """
    try:
        return jsonlib.loads(read_json_arg(name, raw))
    except jsonlib.JSONDecodeError as e:
        raise CliError(EXIT.VALIDATION, f"--{name} is not valid JSON: {e}") from e


def commandline_named(
    ctx: typer.Context,
    named: dict[str, Any],
    *,
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Drop entries from ``named`` whose backing CLI option was NOT typed.

    A create/update command builds ``named`` from *all* of its named
    options, including ones the user never passed (which carry their
    declared default). Since :func:`build_body` gives ``named`` precedence
    over ``--json``, an untyped option's default would otherwise clobber a
    field the user explicitly set via ``--json`` (e.g. ``--schedule``'s
    ``"recurring"`` default overriding ``--json '{"schedule":"once"}'``).

    This keeps only the keys whose Typer/Click parameter source is
    ``COMMANDLINE`` -- i.e. the user actually provided them -- so a default
    never participates in the merge. Keys with no backing parameter (e.g.
    an ``auth`` object assembled from several options, already added only
    when the user supplied them) have source ``None`` and are kept as-is.
    ``aliases`` maps a body-field key to its parameter name where they
    differ (e.g. ``{"nexset_ids": "nexset_id"}``).
    """
    aliases = aliases or {}
    result: dict[str, Any] = {}
    for key, value in named.items():
        source = ctx.get_parameter_source(aliases.get(key, key))
        if source is None or source == ParameterSource.COMMANDLINE:
            result[key] = value
    return result


def output_path(raw: str) -> Path:
    """Resolve ``raw`` against the CWD and reject any path that escapes it."""
    cwd = Path.cwd().resolve()
    resolved = (cwd / raw).resolve()
    if resolved != cwd and cwd not in resolved.parents:
        raise CliError(EXIT.VALIDATION, "output path escapes working directory")
    return resolved


def _scan_value(value: Any, path: str) -> None:
    """Recursively reject disallowed control chars in every nested string.

    Walks dicts (by key) and lists (by index) to any depth, so a control
    char hidden inside a ``--config`` object, a ``rest.iterations[...]``
    list, or a ``credential_mappings[...]`` list of dicts is caught just
    like a top-level string. ``path`` accumulates a dotted/indexed locator
    (e.g. ``config.code`` or ``rest.iterations[0].url``) so the raised
    error still names something the user can find.
    """
    if isinstance(value, str):
        for c in value:
            if ord(c) < 0x20 and c not in "\n\r\t":
                raise CliError(
                    EXIT.VALIDATION,
                    f"field {path!r} contains disallowed control character U+{ord(c):04X}",
                )
    elif isinstance(value, dict):
        for key, nested in value.items():
            child = f"{path}.{key}" if path else str(key)
            _scan_value(nested, child)
    elif isinstance(value, list):
        for i, nested in enumerate(value):
            _scan_value(nested, f"{path}[{i}]")


def scan_body(body: dict[str, Any]) -> dict[str, Any]:
    """Reject dangerous control characters in any string value of a request body.

    Unlike ``sanitize.py`` (which strips untrusted *API response* text
    before it hits the terminal), this validates a body the user is
    authoring themselves outbound to the API -- e.g. multi-line Python/SQL
    transform source in a ``code`` field. Newlines, carriage returns, and
    tabs are legitimate there and are JSON-encoded safely regardless, so
    they're allowed through. What's still rejected is the same class
    ``sanitize.py`` strips on the way back: ANSI escapes and other C0/C1
    controls that have no legitimate reason to appear in any field
    (including names/ids), since those could corrupt terminal state if the
    value is later echoed back (e.g. in a create response) before going
    through response sanitization, or wedge into logs/headers downstream.

    The scan recurses into nested dicts and lists (see :func:`_scan_value`)
    so a control char buried inside a ``--config`` object or a
    list-of-dicts field is rejected too, not just top-level strings. This
    is a pure validation pass: ``body`` is returned unchanged on success.
    """
    _scan_value(body, "")
    return body


def build_body(named: dict[str, Any], raw_json: str | None, params: list[str]) -> dict[str, Any]:
    """Merge a create/update request body from three sources.

    Precedence, highest wins: explicit named CLI options (``named``) >
    ``--json`` raw body > ``--params key=value`` overrides. Applied in the
    reverse order below so each later ``.update()`` wins over the earlier
    ones. The merged body is run through :func:`scan_body` before being
    returned, so every create/update command gets input validation "for
    free" by routing its body through this function.
    """
    body: dict[str, Any] = {}
    for p in params:
        if "=" not in p:
            raise CliError(EXIT.VALIDATION, f"--params entry must be key=value: {p}")
        key, _, value = p.partition("=")
        body[key] = value
    if raw_json:
        # Via parse_json_arg so `--json @body.json` / `--json @-` work the
        # same as every other JSON-taking option.
        parsed = parse_json_arg("json", raw_json)
        if not isinstance(parsed, dict):
            raise CliError(EXIT.VALIDATION, "--json must be a JSON object")
        body.update(parsed)
    body.update({k: v for k, v in named.items() if v is not None})
    return scan_body(body)
