"""`nexla-cli sources` — list / get / create / update / activate / pause / delete
/ sample / file-upload.

Mirrors the deployed ``/nexla/*`` API.
"""

from __future__ import annotations

from typing import Any

import typer

from .. import client, dryrun, output, poll, validate
from ..errors import EXIT, CliError
from ._common import DRY_RUN_OPT, JSON_OPT, PARAMS_OPT, VERIFY_OPT, emit_list, emit_write

app = typer.Typer(name="sources", help="Manage Nexla data sources.", no_args_is_help=True)

_COLUMNS = ["id", "name", "status", "connector", "kind", "flow_id"]

_NO_VERIFY_OPT = typer.Option(
    False,
    "--no-verify",
    help="Skip the read-after-write check that a source update actually persisted",
)


def _leaf_values(obj: Any) -> list[Any]:
    """Flatten every scalar leaf value out of a nested dict/list structure.

    Used by the read-after-write config check to compare *values* without
    caring where the server chose to nest or rekey them.
    """
    if isinstance(obj, dict):
        out: list[Any] = []
        for v in obj.values():
            out.extend(_leaf_values(v))
        return out
    if isinstance(obj, list):
        out = []
        for v in obj:
            out.extend(_leaf_values(v))
        return out
    return [obj]


def _verify_update_persisted(
    ctx: typer.Context, source_id: int, requested: dict[str, Any]
) -> None:
    """Read the source back after a PATCH and warn if a requested change no-op'd.

    Guards a known API-side bug where ``PATCH /nexla/sources/{id}`` can
    return HTTP 200 while silently NOT persisting the change (a
    payload-shape issue for some connector types, fixed upstream
    separately). Without this, a silent no-op looks like success. Here we
    re-GET the source and compare the fields the user *explicitly* typed on
    the command line; on a positively-detected mismatch we raise
    ``EXIT.ERROR`` (operation reported success but the postcondition
    failed) so the no-op becomes visible and non-zero-exit.

    Comparison strategy, and its deliberate limits:

    * Only fields whose backing CLI option was actually provided are
      checked (via :func:`validate.commandline_named`) -- a field the user
      never set is never compared. Values set indirectly through
      ``--json``/``--params`` are out of scope.
    * ``name``/``description`` are scalars the server stores verbatim, so
      an exact ``!=`` comparison is both safe and precise.
    * ``config`` is checked LENIENTLY. The server may normalize, rekey, or
      re-nest a connector config on read-back (e.g. API connectors store it
      under ``template_config`` with prefixed keys), so an exact-equality
      check would false-warn on a reshaped-but-present config. Instead we
      flatten the requested config to its scalar leaf values and only warn
      if *none* of them appear anywhere in the read-back object -- i.e. the
      config looks entirely absent, a strong signal the whole update
      no-op'd. A false "did not persist" warning is worse than silence, so
      this intentionally stays quiet on ambiguous cases: a partial config
      update (some keys persisted, some not) or a value the server rewrote
      (a normalized path, a stringified bool) will not warn. It catches the
      whole-config silent no-op this guards against, not every possible
      field-level drift.
    """
    fields = validate.commandline_named(ctx, requested)
    if not fields:
        return
    read_back = client.request("GET", f"/nexla/sources/{source_id}")
    if not isinstance(read_back, dict):
        # A non-object read-back gives us nothing to compare against; stay
        # silent rather than risk a false warning.
        return

    missing: list[str] = []
    for key in ("name", "description"):
        if key in fields and read_back.get(key) != fields[key]:
            missing.append(key)

    if "config" in fields:
        requested_leaves = [
            v for v in _leaf_values(fields["config"]) if v not in (None, "")
        ]
        if requested_leaves:
            read_back_leaves = _leaf_values(read_back)
            if not any(v in read_back_leaves for v in requested_leaves):
                missing.append("config")

    if not missing:
        return
    raise CliError(
        EXIT.ERROR,
        f"update reported success but read-after-write shows requested field(s) did not "
        f"persist: {', '.join(missing)}. The PATCH returned success yet the source still "
        f"shows the old value(s) -- a known API-side issue where an update can silently "
        f"no-op for some connector types. Re-check the source or retry; pass --no-verify "
        f"to skip this check.",
    )


@app.command("list")
def list_(
    ctx: typer.Context,
    connector: str | None = typer.Option(None),
    flow_id: int | None = typer.Option(
        None,
        help="NOTE: declared in the API's OpenAPI schema but rejected by the live "
        "endpoint (exit 1, 'additional properties'); server-side mismatch, not usable today",
    ),
    access_role: str = typer.Option("collaborator"),
    page: int = typer.Option(1),
    per_page: int = typer.Option(50),
) -> None:
    """List sources."""
    params: dict[str, object] = {"access_role": access_role, "page": page, "per_page": per_page}
    if connector is not None:
        params["connector"] = connector
    if flow_id is not None:
        params["flow_id"] = flow_id
    emit_list(ctx, "/nexla/sources", params, _COLUMNS, per_page)


@app.command("get")
def get(
    ctx: typer.Context,
    source_id: int,
    wait_until: str | None = poll.wait_until_option("source_nexset_id, or status=ACTIVE"),
    wait_timeout: int = poll.WAIT_TIMEOUT_OPT,
    wait_interval: int = poll.WAIT_INTERVAL_OPT,
) -> None:
    """Get one source by id. `--wait-until source_nexset_id` polls until it appears."""

    def fetch() -> object:
        return client.request("GET", f"/nexla/sources/{source_id}")

    body = poll.poll_until(fetch, wait_until, wait_timeout, wait_interval) if wait_until else fetch()
    output.emit(body, mode=output.ctx_mode(ctx), fields=output.ctx_fields(ctx))


@app.command("create")
def create(
    ctx: typer.Context,
    name: str = typer.Option(...),
    connector: str = typer.Option(...),
    description: str | None = typer.Option(None),
    credential_id: int | None = typer.Option(None),
    endpoint: str | None = typer.Option(None),
    mode: str | None = typer.Option(None, help="db connectors only: 'default' or 'query'"),
    config: str = typer.Option(
        "{}", help="JSON object of connector-specific fields; accepts @file.json or @-"
    ),
    schedule: str = typer.Option("recurring", help="'recurring' or 'once'"),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
    verify: bool = VERIFY_OPT,
) -> None:
    """Create and activate a source."""
    named: dict[str, object] = {
        "name": name,
        "description": description,
        "credential_id": credential_id,
        "connector": connector,
        "endpoint": endpoint,
        "mode": mode,
        "config": validate.parse_json_arg("config", config) if config != "{}" else None,
        "schedule": schedule,
    }
    body = validate.build_body(
        validate.commandline_named(ctx, named) if json_body is not None else named,
        json_body,
        params,
    )
    if dry_run:
        dryrun.run_dry_run(resource="sources", verb="create", body=body)
    emit_write(
        ctx,
        client.request("POST", "/nexla/sources", json=body),
        "/nexla/sources",
        verify=verify,
    )


@app.command("update")
def update(
    ctx: typer.Context,
    source_id: int,
    name: str | None = typer.Option(None),
    description: str | None = typer.Option(None),
    config: str | None = typer.Option(None, help="JSON object; accepts @file.json or @-"),
    json_body: str | None = JSON_OPT,
    params: list[str] = PARAMS_OPT,
    dry_run: bool = DRY_RUN_OPT,
    verify: bool = VERIFY_OPT,
    no_verify: bool = _NO_VERIFY_OPT,
) -> None:
    """Update a source's name/description/config.

    After a successful (non-dry-run) update, re-reads the source and warns
    with a non-zero exit if a field the user explicitly set did not
    actually persist -- guarding a known API-side bug where a PATCH can
    return success yet silently no-op. Pass ``--no-verify`` to skip.

    ``--verify`` is a separate, additive thing: it changes *what is
    emitted* (the re-read resource rather than the PATCH response). The
    ``--no-verify`` persistence check runs independently of it.
    """
    named: dict[str, object] = {
        "name": name,
        "description": description,
        "config": validate.parse_json_arg("config", config) if config is not None else None,
    }
    body = validate.build_body(
        validate.commandline_named(ctx, named) if json_body is not None else named,
        json_body,
        params,
    )
    if dry_run:
        dryrun.run_dry_run(resource="sources", verb="update", body=body)
    emit_write(
        ctx,
        client.request("PATCH", f"/nexla/sources/{source_id}", json=body),
        "/nexla/sources",
        verify=verify,
        resource_id=source_id,
    )
    # Read-after-write postcondition check. Emitted output above is the
    # primary PATCH response (the user sees it first); the warning + nonzero
    # exit come after, on a positively-detected silent no-op.
    if not no_verify:
        _verify_update_persisted(ctx, source_id, named)


@app.command("activate")
def activate(ctx: typer.Context, source_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Activate a paused source."""
    if dry_run:
        dryrun.run_dry_run(resource="sources", verb="activate", body={})
    output.emit(
        client.request("POST", f"/nexla/sources/{source_id}/activate"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("pause")
def pause(ctx: typer.Context, source_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Pause an active source."""
    if dry_run:
        dryrun.run_dry_run(resource="sources", verb="pause", body={})
    output.emit(
        client.request("POST", f"/nexla/sources/{source_id}/pause"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("delete")
def delete(ctx: typer.Context, source_id: int, dry_run: bool = DRY_RUN_OPT) -> None:
    """Delete a source."""
    if dry_run:
        dryrun.run_dry_run(resource="sources", verb="delete", body={})
    output.emit_delete(ctx, client.request("DELETE", f"/nexla/sources/{source_id}"), source_id)


@app.command("sample")
def sample(
    ctx: typer.Context,
    source_id: int,
    payload: str = typer.Option(..., help="JSON payload to POST; accepts @file.json or @-"),
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Post a sample payload to a webhook source."""
    body = {"payload": validate.parse_json_arg("payload", payload)}
    if dry_run:
        dryrun.run_dry_run(resource="sources", verb="sample", body=body)
    output.emit(
        client.request("POST", f"/nexla/sources/{source_id}/sample", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("file-upload")
def file_upload(
    ctx: typer.Context,
    source_id: int,
    path: list[str] = typer.Option(
        ...,
        help="Path INSIDE the named Nexla-managed sandbox (not your local machine); repeatable",
    ),
    sandbox: str = typer.Option(
        None,
        "--sandbox",
        help="Sandbox / session id whose files to read. Required: without it the "
        "server would pick an arbitrary sandbox, so the CLI refuses to fire.",
    ),
    dry_run: bool = DRY_RUN_OPT,
) -> None:
    """Register files that already live in a Nexla-managed sandbox with a file-upload source.

    ``--path`` is resolved by the server INSIDE the sandbox you name with
    ``--sandbox`` — it is NOT read from the machine running the CLI, and there
    is no local upload. A standalone install has no implicit sandbox, so
    ``--sandbox`` is mandatory; omitting it exits ``CONFIG`` (3) with no network
    call rather than letting the server select an arbitrary sandbox.
    """
    if not sandbox:
        raise CliError(
            EXIT.CONFIG,
            "sources file-upload needs an explicit --sandbox/session id: --path is "
            "resolved inside a Nexla-managed sandbox, not your local machine, and "
            "there is no local file upload in a standalone install. Rerun with "
            "--sandbox <id> to name the sandbox to read from.",
        )
    body = {"sandbox_id": sandbox, "files": [{"path": p} for p in path]}
    if dry_run:
        dryrun.run_dry_run(resource="sources", verb="file-upload", body=body)
    output.emit(
        client.request("POST", f"/nexla/sources/{source_id}/file_upload", json=body),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )
