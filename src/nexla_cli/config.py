"""Persistent credential store for `nexla-cli`.

Lets `login` stash the service key + a cached bearer on disk so users (and
agents) don't have to `export NEXLA_TOKEN=$(...)` every session. Stored as
JSON (stdlib, no extra dependency) at ``$XDG_CONFIG_HOME/nexla/config.json``
(falls back to ``~/.config/nexla/config.json``), file mode ``0600`` / dir
``0700`` -- it holds a secret (the service key), so it's owner-only.

The env vars (``NEXLA_API_URL`` / ``NEXLA_TOKEN``) always take precedence over
this file, so CI/agents that set them are unaffected; the file is the fallback
that makes an interactive install "just work" after a single `login`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "nexla" / "config.json"


def load() -> dict[str, Any]:
    """Return the stored config, or an empty dict if absent/unreadable."""
    try:
        with path().open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(**fields: Any) -> Path:
    """Merge ``fields`` into the stored config and write it back at 0600.

    Only the keys passed are updated; existing keys are preserved. ``None``
    values are ignored (so ``save(expires_at=None)`` won't clobber a value).
    """
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = load()
    current.update({k: v for k, v in fields.items() if v is not None})
    # Temp file + atomic replace so a crash can't leave a half-written secret,
    # created 0600 from the start (never briefly group/world-readable).
    tmp = p.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    os.replace(tmp, p)
    return p


def clear() -> bool:
    """Delete the stored config. Returns True if a file was removed."""
    try:
        path().unlink()
        return True
    except FileNotFoundError:
        return False
