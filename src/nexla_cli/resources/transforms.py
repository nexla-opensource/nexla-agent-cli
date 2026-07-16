"""`nexla-cli transforms` — test-only surface (no CRUD).

Mirrors the deployed ``/nexla/*`` API. Derived nexsets are
persisted via ``nexla-cli nexsets transform``, not here.
"""

from __future__ import annotations

import typer

from .. import client, output, validate

app = typer.Typer(name="transforms", help="Test Nexla transforms.", no_args_is_help=True)


@app.command("test")
def test(
    ctx: typer.Context,
    language: str = typer.Option(..., help="'python' or 'sql'"),
    code: str = typer.Option(...),
    input: str = typer.Option("[]", help="JSON array of records"),
    options: str | None = typer.Option(None, help="JSON object (SQL only)"),
    parent_nexset_id: int | None = typer.Option(None),
) -> None:
    """Dry-run a transform against sample input."""
    body = {
        "language": language,
        "code": code,
        "input": validate.parse_json_arg("input", input),
        "options": validate.parse_json_arg("options", options) if options is not None else None,
        "parent_nexset_id": parent_nexset_id,
    }
    validate.scan_body(body)
    output.emit(
        client.request("POST", "/nexla/transforms/test", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )
