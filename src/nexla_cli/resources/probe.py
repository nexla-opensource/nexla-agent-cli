"""`nexla-cli probe` — probe a credential or inline config.

Mirrors the deployed ``/nexla/*`` API: one action-discriminated
endpoint covering validate/tree/sample. Exactly one of
``--credential-id``/``--connector`` must be given.
"""

from __future__ import annotations

import re

import typer

from .. import client, output, validate
from ..errors import EXIT, CliError

app = typer.Typer(name="probe", help="Probe a Nexla credential or inline config.", no_args_is_help=True)

# ``--params`` is a free-form, kind-discriminated bag on the server side --
# the shape that's valid depends entirely on the connector's `kind`
# (surfaced by `nexla-cli connectors search <name>`/`describe <name>`), and
# nothing in the live OpenAPI schema documents it (it's typed as a bare
# `additionalProperties: true` object there). See AGENTS.md/SKILL.md
# "probe params shape depends on connector kind" for the authoritative,
# longer version of this -- keep the two in sync if this changes.
_PARAMS_HELP = (
    "JSON object of action params; shape depends on the connector's `kind` "
    "(see `nexla-cli connectors search <name>` for kind). api: "
    '{"endpoint": "<connector>.<endpoint_id>", "config": {...}} (get '
    "endpoint/field names from `describe-source`/`describe-source-endpoint`). "
    'db: {"db_query_mode": "Default", "table": ..., "database": ...} or '
    '{"db_query_mode": "Query", "query": ...}. file: {"path": ...} (required). '
    'rest: {"url": ..., "method": "GET", "response.data.path": ...} or the '
    'full passthrough {"rest.iterations": [...]}.'
)

# Java NPE-style messages the upstream probe service returns verbatim
# (e.g. `Cannot read field "template" because "varInfo" is null`) when
# `--params` doesn't match the connector's `kind` -- these pass through
# `client.request` as an opaque 500 with no indication of the real cause.
# Detecting the shape (rather than one exact message) survives the field
# name varying per connector/kind.
_NPE_SIGNATURE = re.compile(r"cannot read (field|property|array)|nullpointerexception", re.IGNORECASE)
_NPE_HINT = (
    "this looks like an upstream Java NPE, which usually means --params "
    "doesn't match the connector's expected shape for its kind (api/db/file/"
    "rest) -- run `nexla-cli probe run --help` for the shape per kind"
)


def _annotate_npe(e: CliError, action: str) -> CliError:
    """Append a shape-mismatch hint to `sample`/`tree` 500s that look like the
    upstream NPE signature, without changing the exit code or envelope."""
    if action not in ("sample", "tree"):
        return e
    envelope = e.envelope or {}
    message = envelope.get("errorMessage") or envelope.get("error")
    if not isinstance(message, str) or not _NPE_SIGNATURE.search(message):
        return e
    return CliError(e.code, f"{e.message}\nhint: {_NPE_HINT}", envelope=e.envelope)


def _npe_message_in_success_body(data: object) -> str | None:
    """Find the upstream NPE signature when the probe service buries it
    inside a 200 OK envelope instead of raising a non-2xx status.

    Observed live: `sample`/`tree` against a mismatched `--params` shape can
    come back as ``{"ok": true, "sample_format": "unknown",
    "raw_response_excerpt": "...\\"errorMessage\\": \\"Cannot read field ...
    \\"varInfo\\" is null\\", \\"statusCode\\": 500..."}`` -- HTTP 200, no
    exception, no hint. Check the same well-known fields as the error path
    plus ``raw_response_excerpt``, which is where this excerpt actually
    lands (it's a truncated/escaped string, not necessarily valid nested
    JSON, so this deliberately searches the raw text rather than parsing it).
    """
    if not isinstance(data, dict):
        return None
    for key in ("errorMessage", "error", "raw_response_excerpt"):
        value = data.get(key)
        if isinstance(value, str) and _NPE_SIGNATURE.search(value):
            return value
    return None


@app.command("run")
def run(
    ctx: typer.Context,
    action: str = typer.Option(..., help="'validate', 'tree', or 'sample'"),
    credential_id: int | None = typer.Option(None),
    connector: str | None = typer.Option(None, help="Inline credential: connector name"),
    auth_mode: str | None = typer.Option(None, help="Inline credential: auth mode"),
    config: str = typer.Option("{}", help="Inline credential: JSON config"),
    params: str = typer.Option("{}", help=_PARAMS_HELP),
) -> None:
    """Validate a credential, or sample/tree an endpoint."""
    if (credential_id is None) == (connector is None):
        raise CliError(EXIT.VALIDATION, "specify exactly one of --credential-id or --connector")
    body: dict[str, object] = {"action": action, "params": validate.parse_json_arg("params", params)}
    if credential_id is not None:
        body["credential_id"] = credential_id
    else:
        body["credential"] = {
            "connector": connector,
            "auth_mode": auth_mode,
            "config": validate.parse_json_arg("config", config),
        }
    try:
        response = client.request("POST", "/nexla/probe", json=body)
    except CliError as e:
        raise _annotate_npe(e, action) from e
    if action in ("sample", "tree"):
        npe_message = _npe_message_in_success_body(response)
        if npe_message is not None:
            envelope = response if isinstance(response, dict) else None
            raise CliError(EXIT.UPSTREAM, f"{npe_message}\nhint: {_NPE_HINT}", envelope=envelope)
    output.emit(
        response,
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )
