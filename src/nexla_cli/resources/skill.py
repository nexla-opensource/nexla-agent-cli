"""`nexla-cli skill install` — self-locating Claude Code skill installer.

Claude Code only discovers skills at ``~/.claude/skills/<name>/SKILL.md``
(global) or ``.claude/skills/<name>/SKILL.md`` (project-local) -- a file
merely present inside an installed package isn't picked up automatically.
Previously this required the user to figure out which install method
(``uv tool``/``pipx``/npm-wrapped binary) put ``SKILL.md`` where, and
hand-construct a glob path per method. ``importlib.resources`` already
knows exactly where this package's own files live regardless of install
method, so there's nothing to guess.

Copies rather than symlinks: a symlink would be great for `uv tool`/`pipx`
installs (auto-picks up future upgrades), but is useless for the
PyInstaller-compiled binary (npm distribution), where the source path is
an ephemeral extraction directory that's gone once the process exits. One
behavior for every install method is simpler than branching on which one
is in play; the tradeoff is re-running this command after an upgrade to
pick up skill content changes.
"""

from __future__ import annotations

import importlib.resources
import shutil
from importlib.resources.abc import Traversable
from pathlib import Path

import typer

app = typer.Typer(name="skill", help="Manage this CLI's Claude Code skill install.", no_args_is_help=True)


@app.command("install")
def install(
    target: Path | None = typer.Option(
        None,
        help="Install directory. Default is the global ~/.claude/skills/nexla-cli; "
        "pass .claude/skills/nexla-cli for a project-local install instead",
    ),
) -> None:
    """Copy this package's SKILL.md, AGENTS.md, and the vendored skill_pack/.

    SKILL.md + AGENTS.md are the thin CLI adapter; ``skill_pack/`` is the
    canonical Nexla domain reference/examples (vendored from express-code)
    that SKILL.md points at. All three are needed for the installed skill
    to be complete -- SKILL.md references both AGENTS.md and the pack, so
    installing without them leaves dangling references.
    """
    if target is None:
        target = Path.home() / ".claude" / "skills" / "nexla-cli"
    target.mkdir(parents=True, exist_ok=True)
    root = importlib.resources.files("nexla_cli")
    for name in ("SKILL.md", "AGENTS.md"):
        # Explicit utf-8 on both ends: these files contain non-ASCII
        # (em dashes) and the platform-default encoding read_text/
        # write_text otherwise fall back to is cp1252 on Windows, which
        # would raise or mangle bytes on that build.
        (target / name).write_text((root / name).read_text(encoding="utf-8"), encoding="utf-8")
    # Clear any previously-installed pack first so files dropped/renamed in a
    # newer version don't linger next to the current ones.
    pack_dest = target / "skill_pack"
    if pack_dest.is_dir():
        shutil.rmtree(pack_dest)
    _copy_tree(root / "skill_pack", pack_dest)
    typer.echo(f"Installed skill to {target}")
    typer.echo("Restart Claude Code (or start a new session) to pick it up.")


def _copy_tree(src: Traversable, dest: Path) -> None:
    """Recursively copy a package resource tree to a filesystem directory.

    Uses ``importlib.resources`` traversal (``.iterdir()``/``.is_dir()``)
    rather than ``shutil.copytree`` so it works both from a normal pip/uv
    install (where the resource is a real directory) and from the
    PyInstaller ``--onefile`` binary (where it's an extracted temp tree).
    Everything under ``skill_pack/`` is text markdown, so read/write goes
    through explicit utf-8 for the same Windows-cp1252 reason as above.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        child = dest / entry.name
        if entry.is_dir():
            _copy_tree(entry, child)
        else:
            child.write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
