"""Import-time smoke test for the private-Click import path.

`nexla_cli.cli` and `nexla_cli.validate` import symbols that live in either the
standalone `click` package or Typer's vendored `typer._click` fork depending
on the installed Typer version (see the import notes in those modules). If the
fallback chain ever fails to resolve, the package raises `ImportError` at
*import* time -- before any command runs -- so simply importing the package
and building its app object is enough to catch a broken floor/fallback.

This is deliberately import/build only; the min-version CI matrix belongs to
the separate CI work item.
"""

from __future__ import annotations

import importlib

from typer.testing import CliRunner


def test_package_imports() -> None:
    """Importing the package resolves the private-Click symbols."""
    # Importing the package triggers importing nexla_cli.cli, which resolves
    # the private-Click fallback for these parse-time exception types.
    importlib.import_module("nexla_cli")
    cli = importlib.import_module("nexla_cli.cli")
    assert cli.NoArgsIsHelpError is not None
    assert cli.UsageError is not None

    validate = importlib.import_module("nexla_cli.validate")
    assert validate.ParameterSource is not None


def test_app_object_builds() -> None:
    """The Typer app object is constructed at import time."""
    import typer

    from nexla_cli import app

    assert isinstance(app, typer.Typer)


def test_help_runs() -> None:
    """`nexla-cli --help` exits 0 and prints usage (proves the app is wired up)."""
    from nexla_cli import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
