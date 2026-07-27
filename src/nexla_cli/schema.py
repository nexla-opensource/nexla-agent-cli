"""`nexla-cli schema [<command>]` — machine-readable command/API signatures.

Fetches the live deployed API's own ``/openapi.json`` (unauthenticated,
same call every other unauthenticated CLI call makes via
``client.request(..., require_auth=False)``) rather than importing a
Pydantic model — the standalone ``nexla-cli`` package cannot import
``express_api`` at all. Reflects whatever API version is
actually deployed at ``NEXLA_API_URL``.

**Exempt from ``--output``/``--fields``/``--page-all``**, same as
``login``: this command's whole purpose is a fixed, machine-readable JSON
document, so it always prints raw JSON via ``typer.echo(json.dumps(...))``
and never routes through ``output.emit()``.
"""

from __future__ import annotations

import json as jsonlib
from typing import Any

import typer

from . import openapi_client
from .errors import EXIT, CliError
from .sanitize import sanitize

schema_app = typer.Typer(
    name="schema", help="Machine-readable command/API signatures.", no_args_is_help=False
)

# Typer auto-adds these to the root group; they're shell-completion plumbing,
# not part of the CLI's own surface, so keep them out of the command catalog.
_COMPLETION_PARAMS = {"install_completion", "show_completion"}


def _param_info(param: Any) -> dict[str, Any]:
    """One Click parameter -> a flat, JSON-friendly descriptor.

    ``name`` is the CLI-facing token an agent actually types: the primary
    ``--long`` option for options (so a bool flag reads as ``--dry-run``, not
    the Python identifier ``dry_run``), and the bare arg name for positionals.
    """
    if param.param_type_name == "argument":
        name = param.name
    else:
        longs = [opt for opt in param.opts if opt.startswith("--")]
        name = longs[0] if longs else (param.opts[0] if param.opts else param.name)
    return {
        "name": name,
        "type": getattr(param.type, "name", None),
        "required": bool(param.required),
        "default": param.default,
        "is_flag": bool(getattr(param, "is_flag", False)),
        "help": getattr(param, "help", None),
    }


def _params(cmd: Any) -> list[dict[str, Any]]:
    return [_param_info(p) for p in cmd.params if p.name not in _COMPLETION_PARAMS]


def _walk(path: list[str], cmd: Any, out: list[dict[str, Any]]) -> None:
    """Depth-first collect every non-hidden invocable command under ``cmd``.

    A group (``hasattr(cmd, "commands")``) contributes its children; hidden
    children are skipped whole (matching ``--help``, which hides the
    not-in-v1 groups). A group that is itself invocable and carries real
    params -- e.g. ``schema`` -- is also emitted as a command in its own right.
    """
    if hasattr(cmd, "commands"):
        for name in sorted(cmd.commands):
            sub = cmd.commands[name]
            if sub.hidden:
                continue
            _walk([*path, name], sub, out)
        if getattr(cmd, "invoke_without_command", False) and _params(cmd):
            out.append({"path": " ".join(path), "help": cmd.help, "params": _params(cmd)})
    else:
        out.append({"path": " ".join(path), "help": cmd.help, "params": _params(cmd)})


def _command_catalog(root: Any) -> dict[str, Any]:
    """Introspect the whole Click command tree into a machine-readable catalog.

    Pure reflection over the live tree (no network), so it can't drift from
    the real command surface. The exit-code taxonomy is included once at the
    top -- agents branch on the numeric code, not message text.
    """
    commands: list[dict[str, Any]] = []
    for name in sorted(root.commands):
        sub = root.commands[name]
        if sub.hidden:
            continue
        _walk([name], sub, commands)
    return {
        "exit_codes": [{"name": m.name, "code": int(m)} for m in EXIT],
        "global_options": _params(root),
        "commands": commands,
    }


@schema_app.callback(invoke_without_command=True)
def dump(
    ctx: typer.Context,
    command: str | None = typer.Argument(
        None, help="e.g. 'sources.create'; omit for the whole /nexla surface"
    ),
    commands: bool = typer.Option(
        False,
        "--commands",
        help="Dump the whole CLI command tree (paths, params, exit codes) as JSON; no network.",
    ),
) -> None:
    """Print the live ``/nexla/*`` OpenAPI subset, or one command's signature.

    With ``--commands`` instead prints a pure-introspection catalog of the
    CLI itself (every command, its params, and the exit-code taxonomy) with
    no network call -- the machine-readable map of the command surface.
    """
    if commands:
        catalog = _command_catalog(ctx.find_root().command)
        typer.echo(jsonlib.dumps(sanitize(catalog), indent=2, default=str))
        return

    spec = openapi_client.fetch_openapi()
    if command is None:
        paths = openapi_client.nexla_paths(spec)
        typer.echo(
            jsonlib.dumps(
                sanitize({"openapi": spec.get("openapi"), "paths": paths}), indent=2, default=str
            )
        )
        return

    resource, _, verb = command.partition(".")
    if not verb:
        raise CliError(EXIT.VALIDATION, "command must be 'resource.verb', e.g. 'sources.create'")

    match = openapi_client.resolve(spec, resource, verb)
    if match is None:
        raise CliError(EXIT.NOT_FOUND, f"no known route for '{command}'")

    body_schema = openapi_client.request_body_schema(spec, match["operation"])
    result = {
        "command": command,
        "method": match["method"],
        "path": match["path"],
        "parameters": match["operation"].get("parameters", []),
        "request_body": body_schema,
    }
    typer.echo(jsonlib.dumps(sanitize(result), indent=2, default=str))
