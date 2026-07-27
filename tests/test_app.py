"""Top-level `nexla` app assembly: --help renders for every group, no network."""

from __future__ import annotations

import re

import httpx
import pytest
import respx
from typer.testing import CliRunner

import nexla_cli
from nexla_cli import _reorder_global_flags, helptext
from nexla_cli.errors import EXIT

from .conftest import BASE_URL

_RESOURCE_GROUPS = [
    "login",
    "sources",
    "sinks",
    "nexsets",
    "credentials",
    "flows",
    "transforms",
    "connectors",
    "probe",
    "toolsets",
    "tools",
    "mcp-servers",
    "context",
    "orgs",
    "code-containers",
    "metrics",
    "users",
    "notifications",
]

# Not-implemented-in-v1 groups: still in the command tree (so `python -m
# nexla_cli <group>` resolves and fails with a clear local message) but
# hidden from `--help`.
_HIDDEN_GROUPS = {"code-containers", "metrics", "users", "notifications"}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def test_root_help(cli_app) -> None:
    result = CliRunner().invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    for group in _RESOURCE_GROUPS:
        if group in _HIDDEN_GROUPS:
            assert group not in result.stdout
        else:
            assert group in result.stdout


def test_no_args_shows_help(cli_app) -> None:
    # `no_args_is_help=True` prints usage and exits 2 (click's convention for
    # "no subcommand given") rather than 0 — assert the help text, not a
    # specific success code.
    result = CliRunner().invoke(cli_app, [])
    assert "Usage" in result.stdout


def test_every_leaf_command_has_a_nonblank_description(cli_app) -> None:
    """Every command's one-line docstring must actually render in --help.

    Walks the real click command tree (via `typer.main.get_command`)
    instead of invoking `--help` per group and grepping text -- this
    catches a blank description regardless of terminal width/wrapping,
    and checks every leaf command in one pass rather than sampling a few
    groups by hand. A command with no docstring shows up here as an empty
    `get_short_help_str()`, exactly the bug this guards against.
    """
    import typer.main as tm

    click_app = tm.get_command(cli_app)

    def leaf_commands(cmd: object, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
        commands = getattr(cmd, "commands", None)
        if commands:
            found: list[tuple[tuple[str, ...], str]] = []
            for name, sub in commands.items():
                found.extend(leaf_commands(sub, path + (name,)))
            return found
        return [(path, cmd.get_short_help_str())]  # type: ignore[attr-defined]

    all_commands = leaf_commands(click_app)
    assert len(all_commands) >= 60, f"expected ~66 commands, found {len(all_commands)} -- tree walk broke"
    blank = [" ".join(path) for path, help_str in all_commands if not help_str.strip()]
    assert not blank, f"commands with no docstring / blank --help description: {blank}"


def test_each_group_help_exits_zero(cli_app) -> None:
    runner = CliRunner()
    for group in _RESOURCE_GROUPS:
        result = runner.invoke(cli_app, [group, "--help"])
        assert result.exit_code == 0, f"{group} --help failed: {result.stdout}"


def test_root_help_groups_commands_into_sections(cli_app) -> None:
    """Root `--help` is sectioned (gh-style), not one flat command list.

    Asserts the panel headings from `helptext.PANELS` are actually
    rendered, and that the hidden not-in-v1 groups stay out of *every*
    section.
    """
    result = CliRunner().invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    for panel in set(helptext.PANELS.values()):
        assert panel in result.stdout, f"missing help section: {panel}"
    for hidden in _HIDDEN_GROUPS:
        assert hidden not in result.stdout


def test_root_help_documents_exit_codes_and_machine_contract(cli_app) -> None:
    """The exit-code taxonomy and the agent-facing flags stay discoverable
    from root `--help` -- `errors.EXIT` is the source of truth for the
    numbers, so a new code can't silently go undocumented."""
    result = CliRunner().invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    # Rich's option highlighter colorizes `--flag` mid-token, so the raw
    # stdout has escape codes *inside* the flag names -- strip them first.
    out = _strip_ansi(result.stdout)
    for code in EXIT:
        assert f"{code.value} {code.name.lower()}" in out
    for flag in ("--fields", "--page-all", "--dry-run", "json|ndjson"):
        assert flag in out


def test_curated_commands_show_examples(cli_app) -> None:
    """A sample of leaf commands render their EXAMPLES epilog."""
    runner = CliRunner()
    for path in (["sources", "create"], ["triage", "logs"], ["schema"]):
        result = runner.invoke(cli_app, [*path, "--help"])
        assert result.exit_code == 0
        assert "EXAMPLES" in result.stdout, f"{' '.join(path)} --help has no EXAMPLES"


def test_every_examples_key_names_a_real_command(cli_app) -> None:
    """Guards against an epilog silently detaching when a command is
    renamed: every `helptext.EXAMPLES` key must resolve in the command
    tree, so a stale key fails here instead of quietly showing nothing."""
    import typer.main as tm

    click_app = tm.get_command(cli_app)
    for key in helptext.EXAMPLES:
        cmd: object | None = click_app
        for part in key.split(" "):
            cmd = getattr(cmd, "commands", {}).get(part)
            assert cmd is not None, f"helptext.EXAMPLES key names no such command: {key}"


def test_reorder_global_flags_hoists_flags_placed_after_the_subcommand() -> None:
    """`nexla-cli sources list --output json` must work, not just `nexla-cli --output json sources list`.

    Typer/Click only recognize a parent group's options before the
    subcommand name, so ``main()`` reorders argv before Typer ever sees it.
    Exercised directly here (rather than through ``CliRunner``, which calls
    the ``app`` object and bypasses ``main()``) since this is where the
    reordering actually happens.
    """
    assert _reorder_global_flags(["sources", "list", "--output", "table"]) == [
        "--output",
        "table",
        "sources",
        "list",
    ]
    assert _reorder_global_flags(["sources", "list", "-o", "json"]) == [
        "-o",
        "json",
        "sources",
        "list",
    ]
    assert _reorder_global_flags(["--output", "json", "sources", "list"]) == [
        "--output",
        "json",
        "sources",
        "list",
    ]
    assert _reorder_global_flags(
        ["sources", "list", "--page-all", "--fields", "id,name"]
    ) == ["--page-all", "--fields", "id,name", "sources", "list"]
    assert _reorder_global_flags(["sources", "list", "--output=json"]) == [
        "--output=json",
        "sources",
        "list",
    ]
    assert _reorder_global_flags(["sources", "get", "1"]) == ["sources", "get", "1"]


def test_reorder_stops_at_end_of_options_separator() -> None:
    """A token after `--` must NOT be hoisted, even if it looks like a global flag.

    `--` is the POSIX end-of-options separator; everything after it is a
    positional/value and is left in place so a resource named (or a value
    equal to) `--output` can still be passed.
    """
    # `--output` after `--` stays put; the `--` is preserved for Typer.
    assert _reorder_global_flags(["sources", "get", "--", "--output"]) == [
        "sources",
        "get",
        "--",
        "--output",
    ]
    # A real global flag *before* `--` is still hoisted; one after is not.
    assert _reorder_global_flags(
        ["sources", "list", "--output", "json", "--", "--fields", "--page-all"]
    ) == ["--output", "json", "sources", "list", "--", "--fields", "--page-all"]


def test_output_flag_and_reorder_share_one_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_output_flag_from_argv` and `_reorder_global_flags` use `_split_global_flags`.

    They must agree on the same rules: both honor `--` and both ignore a
    `--output` value that appears after the separator.
    """
    # Shared helper exists and both callers route through it.
    assert hasattr(nexla_cli, "_split_global_flags")
    front, rest = nexla_cli._split_global_flags(
        ["sources", "list", "--output", "json"]
    )
    assert front == ["--output", "json"]
    assert rest == ["sources", "list"]

    # `_output_flag_from_argv` reads the value hoisted by the shared parser.
    monkeypatch.setattr("sys.argv", ["nexla-cli", "sources", "list", "-o", "ndjson"])
    assert nexla_cli._output_flag_from_argv() == "ndjson"

    # A `--output` after `--` is a value, not the flag: not returned.
    monkeypatch.setattr(
        "sys.argv", ["nexla-cli", "sources", "get", "--", "--output", "json"]
    )
    assert nexla_cli._output_flag_from_argv() is None


def test_main_usage_error_gets_a_help_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Click-level parse error (e.g. an option that command doesn't define)

    happens before any command callback runs, so `_wrap_cli_error` can't
    catch it -- `main()` must catch it separately at the `app()` call site
    and append a hint, rather than leaving Click's bare "No such option"
    with nothing pointing toward `--help`. Calls `main()` directly (not
    `CliRunner.invoke(app, ...)`, which bypasses `main()` entirely) since
    that's the only place this hint logic lives.
    """
    monkeypatch.setattr(
        "sys.argv", ["nexla-cli", "connectors", "search", "--params", "q=s3"]
    )
    with pytest.raises(SystemExit) as exc_info:
        nexla_cli.main()
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "No such option" in captured.err
    assert "nexla-cli <command> --help" in captured.err


def test_main_no_args_shows_help_once_on_stdout_no_duplicate_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`nexla-cli` with no args is Typer's designed empty-invocation help, not a

    mistake -- it must keep printing to stdout exactly once (not stderr,
    and not a second time via `.show()`), and must NOT get the generic
    "run --help" hint appended, which would be a strange thing to show
    right after already showing the help.
    """
    monkeypatch.setattr("sys.argv", ["nexla-cli"])
    with pytest.raises(SystemExit) as exc_info:
        nexla_cli.main()
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    # Strip ANSI SGR codes: on a color-forcing terminal (GitHub Actions) Rich
    # inserts style resets between "Usage:" and the prog name, so the raw
    # substring check is brittle. We assert on the plain text.
    out = re.sub(r"\x1b\[[0-9;]*m", "", captured.out)
    assert "Usage" in out
    assert out.count("Usage: nexla-cli") == 1
    assert "nexla-cli <command> --help" not in captured.err
    assert captured.err == ""


def test_main_successful_command_still_exits_zero(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    """Sanity check the `standalone_mode=False` refactor didn't change the

    happy path for the real entrypoint (only `CliRunner`-based tests
    exercise the `app` object directly elsewhere in this suite).
    """
    monkeypatch.setenv("NEXLA_API_URL", BASE_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    monkeypatch.setattr("sys.argv", ["nexla-cli", "orgs", "list"])
    respx_mock.get(f"{BASE_URL}/nexla/orgs").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(SystemExit) as exc_info:
        nexla_cli.main()
    assert exc_info.value.code == 0
