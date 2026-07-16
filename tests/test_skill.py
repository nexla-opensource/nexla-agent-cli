from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner


def test_install_default_target_uses_home(
    runner: CliRunner, cli_app, monkeypatch, tmp_path: Path
) -> None:
    import nexla_cli

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = runner.invoke(cli_app, ["skill", "install"])
    assert result.exit_code == 0
    installed_dir = tmp_path / ".claude" / "skills" / "nexla-cli"
    packaged_dir = Path(nexla_cli.__file__).parent
    for name in ("SKILL.md", "AGENTS.md"):
        assert (installed_dir / name).read_text(encoding="utf-8") == (
            packaged_dir / name
        ).read_text(encoding="utf-8")


def test_install_explicit_target(runner: CliRunner, cli_app, tmp_path: Path) -> None:
    target = tmp_path / "custom"
    result = runner.invoke(cli_app, ["skill", "install", "--target", str(target)])
    assert result.exit_code == 0
    assert (target / "SKILL.md").is_file()
    assert (target / "AGENTS.md").is_file()


def test_install_lands_skill_pack_tree(runner: CliRunner, cli_app, tmp_path: Path) -> None:
    """`skill install` must land the whole vendored pack, not just the adapter."""
    import nexla_cli

    target = tmp_path / "custom"
    result = runner.invoke(cli_app, ["skill", "install", "--target", str(target)])
    assert result.exit_code == 0

    packaged_dir = Path(nexla_cli.__file__).parent

    # The manifest and a couple of files from each subdir must arrive in the
    # right subdirectories, byte-identical to the packaged copies.
    expected = [
        "skill_pack/VENDORED_FROM.md",
        "skill_pack/reference/credentials.md",
        "skill_pack/reference/cron.md",
        "skill_pack/examples/shopify-to-bigquery.md",
        "skill_pack/examples/custom-rest-flow.md",
    ]
    for rel in expected:
        installed = target / rel
        assert installed.is_file(), f"{rel} was not installed"
        assert installed.read_text(encoding="utf-8") == (
            packaged_dir / rel
        ).read_text(encoding="utf-8")

    # Whole tree lands: every packaged .md under skill_pack/ has a counterpart.
    for src in (packaged_dir / "skill_pack").rglob("*.md"):
        rel = src.relative_to(packaged_dir)
        assert (target / rel).is_file(), f"{rel} missing from install"
