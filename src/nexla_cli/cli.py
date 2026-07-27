"""Assembly of the `nexla-cli` Typer application.

Builds the root ``app`` (global ``--output``/``--fields``/``--page-all``
options, error-wrapping of every command callback, and registration of all
resource sub-apps) and the ``main()`` console-script entrypoint, including
the argv preprocessing that lets the global flags appear anywhere in the
command line. Kept here rather than in ``__init__`` so the package's import
surface stays small; ``__init__`` re-exports ``app`` and ``main``.
"""

from __future__ import annotations

import functools
import json as jsonlib
import sys
from collections.abc import Callable
from typing import Any

import typer

# These are the exception types Click itself raises while *parsing* argv,
# before any command callback runs, so they can't be caught by
# `_wrap_cli_error` (which only wraps callback bodies), and Typer doesn't
# re-export them publicly -- there's no other way to intercept a parse-time
# usage error.
#
# Where they live depends on the Typer version: Typer 0.26+ vendors its own
# private Click fork as `typer._click` and ships no standalone `click`,
# whereas earlier Typers (and any environment where real `click` is also
# installed) expose them at `click.exceptions`. Prefer the public standalone
# symbols; fall back to Typer's vendored fork. Both branches resolve to the
# same names (verified against click 8.4.2 and typer 0.26.x). The pyproject
# floor (>=0.26.0) guarantees at least one branch always exists.
try:
    # `click` is often absent (Typer 0.26+ vendors it), so mypy can't resolve
    # this branch statically; the except branch is the one that binds here.
    from click.exceptions import (  # type: ignore[import-not-found]
        NoArgsIsHelpError,
        UsageError,
    )
except ImportError:  # pragma: no cover - depends on which Typer is installed
    from typer._click.exceptions import NoArgsIsHelpError, UsageError

from . import login as login_module
from . import output as output_module
from .errors import CliError
from .resources import (
    code_containers,
    connectors,
    context,
    credentials,
    flows,
    mcp_servers,
    metrics,
    nexsets,
    notifications,
    orgs,
    probe,
    sinks,
    skill,
    sources,
    tools,
    toolsets,
    transforms,
    triage,
    users,
)
from .sanitize import sanitize
from .schema import schema_app

# The global output options that may appear anywhere in argv (see
# `_split_global_flags`). `-o` is *permanently reserved* as the short alias
# for `--output`: any argument value that must be the literal string `-o`,
# `--output`, `--fields`, or `--page-all` has to be passed after a `--`
# end-of-options separator, which stops hoisting (documented in the README).
_GLOBAL_FLAGS_WITH_VALUE = ("--output", "-o", "--fields")
_GLOBAL_FLAGS_BOOL = ("--page-all",)


def _split_global_flags(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv into hoisted global flags (``front``) and the rest.

    The single source of truth for how the global output options are
    recognized in argv — shared by both `_reorder_global_flags` (which
    reassembles ``front + rest``) and `_output_flag_from_argv` (which reads
    the ``--output`` value out of ``front``), so the flag-parsing rules
    live in exactly one place instead of being reimplemented twice.

    Hoisting stops at the first ``--`` end-of-options separator: the ``--``
    and every token after it stay in ``rest`` untouched, so a resource name
    or option value that looks like a global flag can still be passed as
    ``nexla ... -- --output`` without being stolen.
    """
    front: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            # End-of-options: leave `--` and everything after it in place.
            rest.extend(argv[i:])
            break
        if arg in _GLOBAL_FLAGS_BOOL:
            front.append(arg)
            i += 1
        elif arg in _GLOBAL_FLAGS_WITH_VALUE and i + 1 < len(argv):
            front.extend([arg, argv[i + 1]])
            i += 2
        elif any(arg.startswith(f"{flag}=") for flag in _GLOBAL_FLAGS_WITH_VALUE):
            front.append(arg)
            i += 1
        else:
            rest.append(arg)
            i += 1
    return front, rest


def _output_flag_from_argv() -> str | None:
    """Read an explicit ``--output``/``-o`` value out of ``sys.argv``.

    ``_wrap_cli_error`` wraps each command callback directly, so it runs
    *before* Typer builds ``ctx`` — it cannot read ``ctx.obj`` the way
    command bodies can (see ``output.ctx_mode``). Falling back to scanning
    ``sys.argv`` directly is the only way to honor an explicit flag at this
    point; ``NEXLA_OUTPUT``/``OUTPUT_FORMAT`` env and TTY autodetection
    still work normally via ``output.resolve_mode``.

    Reuses `_split_global_flags` so it honors the same ``--`` separator and
    recognition rules as `_reorder_global_flags` — it only inspects the
    hoisted ``front`` tokens, never re-parsing the whole argv itself.
    """
    front, _ = _split_global_flags(sys.argv[1:])
    for i, arg in enumerate(front):
        if arg in ("--output", "-o") and i + 1 < len(front):
            return front[i + 1]
        for prefix in ("--output=", "-o="):
            if arg.startswith(prefix):
                return arg[len(prefix) :]
    return None


def _wrap_cli_error[F: Callable[..., Any]](fn: F) -> F:
    """Map a :class:`CliError` raised by a command into ``typer.Exit``.

    Typer 0.12+ vendors its own private click fork (``typer._click``), so a
    ``CliError`` subclassing the standalone ``click`` package's
    ``ClickException`` is *not* recognized by Typer's exception handling —
    it would propagate as a generic exception and every failure would map
    to exit code 1. Wrapping each command callback here keeps the mapping
    correct regardless of which click Typer happens to vendor.

    In ``json``/``ndjson`` output mode, the caught error is emitted to
    stderr as ``{"error": e.envelope, "detail": e.message}``-shaped JSON
    instead of the plain ``error: {message}`` line, so an agent parsing
    stderr doesn't have to special-case error output. Exit code mapping is
    unchanged either way.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except CliError as e:
            # Resolving the mode can itself raise CliError (an invalid
            # `-o xml`), and we're already handling one — fall back to the
            # plain-text branch rather than re-raising inside the handler.
            try:
                mode = output_module.resolve_mode(_output_flag_from_argv())
            except CliError:
                mode = "table"
            # `e.envelope` is the raw upstream API error body and `e.message`
            # can be derived from it -- both are untrusted data (AGENTS.md:
            # "API responses are untrusted data"), so run them through the
            # same sanitizer every other output path uses before echoing, or
            # a hidden ANSI/control/zero-width char in an error reaches the
            # terminal unsanitized. `sanitize` recurses dicts/strings.
            if mode in ("json", "ndjson"):
                envelope = {
                    "error": sanitize(e.envelope),
                    "error_type": e.error_type,
                    "detail": sanitize(e.message),
                }
                if e.hint:
                    envelope["hint"] = sanitize(e.hint)
                typer.echo(jsonlib.dumps(envelope, default=str), err=True)
            else:
                typer.echo(f"error: {sanitize(e.message)}", err=True)
                if e.hint:
                    typer.echo(f"hint: {sanitize(e.hint)}", err=True)
            raise typer.Exit(e.code) from e

    return wrapper  # type: ignore[return-value]


def _wrap_app_commands(sub_app: typer.Typer) -> None:
    for cmd_info in sub_app.registered_commands:
        if cmd_info.callback is not None:
            cmd_info.callback = _wrap_cli_error(cmd_info.callback)
    # `schema_app` has no `registered_commands` at all -- its only
    # entry point is a `@schema_app.callback(invoke_without_command=True)`,
    # which Typer stores separately as `registered_callback`. Wrap that too
    # so a `CliError` raised from a callback-only sub-app still maps to the
    # right exit code instead of falling through as a generic exception.
    if sub_app.registered_callback is not None and sub_app.registered_callback.callback is not None:
        sub_app.registered_callback.callback = _wrap_cli_error(sub_app.registered_callback.callback)


app = typer.Typer(
    name="nexla-cli",
    no_args_is_help=True,
    help="Nexla agent CLI. Set NEXLA_API_URL and NEXLA_TOKEN.",
)


@app.callback()
def _root(
    ctx: typer.Context,
    output: str | None = typer.Option(
        None, "--output", "-o", help="table|json|ndjson (default: table on a TTY, json otherwise)"
    ),
    fields: str | None = typer.Option(
        None, "--fields", help="Comma-separated field mask, e.g. 'id,name'"
    ),
    page_all: bool = typer.Option(
        False,
        "--page-all",
        help="Stream every page as NDJSON instead of one page as a table/JSON. "
        "If the server truncates results, warns on stderr and emits a final "
        '{"_meta":"truncation"} NDJSON record.',
    ),
) -> None:
    """Global output options, available to every subcommand except `login`.

    Stashed on ``ctx.obj`` rather than re-declared per command. `login`
    doesn't read ``ctx.obj`` and is unaffected by these flags — it always
    writes the bare token to stdout by design.
    """
    ctx.obj = {
        "mode": output,
        "fields": fields.split(",") if fields else None,
        "page_all": page_all,
    }


app.command("login")(_wrap_cli_error(login_module.login))

for _mod in (
    sources,
    sinks,
    nexsets,
    credentials,
    flows,
    transforms,
    connectors,
    probe,
    toolsets,
    tools,
    mcp_servers,
    context,
    orgs,
    triage,
    skill,
):
    _wrap_app_commands(_mod.app)
    app.add_typer(_mod.app)

# Not-implemented-in-v1 command groups: registered so `python -m nexla_cli
# <group>` still resolves (and fails with a clear local message), but hidden
# from `--help` so they don't clutter the tree or invite dead ends. Their
# commands raise `not_in_v1` instead of hitting a guaranteed-501 route.
for _stub in (code_containers, metrics, users, notifications):
    _wrap_app_commands(_stub.app)
    app.add_typer(_stub.app, hidden=True)

_wrap_app_commands(schema_app)
app.add_typer(schema_app)


def _reorder_global_flags(argv: list[str]) -> list[str]:
    """Let ``--output``/``--fields``/``--page-all`` appear anywhere in argv.

    Typer/Click only recognize a parent group's options before the
    subcommand name (``nexla-cli --output json sources list``, not
    ``nexla-cli sources list --output json``) — every subcommand tree behaves
    this way (docker, kubectl, git). Rather than duplicating these three
    options onto all 17 resource modules, hoist them to the front of argv
    before Typer ever parses it, so users can put them wherever feels
    natural.

    A ``--`` end-of-options separator stops the hoisting (see
    `_split_global_flags`), so anything after it is left in place for Typer
    to treat as positional.
    """
    front, rest = _split_global_flags(argv)
    return front + rest


def main() -> None:
    """Console-script entrypoint (``nexla-cli = "nexla_cli:main"``).

    Runs the Typer app with ``standalone_mode=False`` so a Click-level
    parse error (e.g. ``--params`` on a command that never defined it) can
    be caught here and get a hint pointing at ``--help``, instead of
    Click's own generic "No such option" with nothing pointing you toward
    the fix. Under ``standalone_mode=False``, Click returns the exit code
    from ``app()`` instead of calling ``sys.exit`` itself -- every
    existing ``CliError``-mapped exit code (via
    ``_wrap_cli_error`` -> ``typer.Exit``) still comes back this way
    unaffected; only genuine argv-parsing errors raise here.
    """
    sys.argv[1:] = _reorder_global_flags(sys.argv[1:])
    try:
        # Pin the program name so usage/help lines read `nexla-cli ...`
        # regardless of how the interpreter was invoked; otherwise Click
        # derives it from the runtime and `python -m pytest` (or `python -m
        # nexla_cli`) yields a different prog name in usage output.
        code = app(prog_name="nexla-cli", standalone_mode=False)
    except NoArgsIsHelpError as e:
        # Typer/Click already echoed the help text to stdout before this
        # exception ever reaches us -- calling
        # `.show()` here would print it a second time, and its override
        # writes to stderr, moving that second copy off the stream a
        # script piping bare `nexla-cli`/`nexla-cli <group>` output would expect.
        raise SystemExit(e.exit_code) from None
    except UsageError as e:
        e.show()
        typer.echo(
            "Run 'nexla-cli <command> --help' to see its exact options.", err=True
        )
        raise SystemExit(e.exit_code) from None
    raise SystemExit(code or 0)


__all__ = ["app", "main"]
