"""Guard: no internal/staging Nexla deployment hostnames in the tracked repo.

Deployment hosts look like ``<subdomain>.nexla.com`` / ``<subdomain>.nexla.io``
used as a URL host (e.g. the old ``dev-api-express-code.nexla.com`` and
``veda-ai.nexla.io`` endpoints). Those must never ship in the package; docs use
generic placeholders (``https://<your-deployed-api>``,
``https://<your-nexla-monitoring-host>/monitoring/``) instead.

The pattern deliberately requires a ``://<label>.nexla.(com|io)`` shape so it
does NOT flag the legitimate references we keep: the bare marketing link
``https://nexla.com`` (no subdomain), ``@nexla.com`` email addresses, and
``github.com/nexla/...`` repo links.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Matches a deployment host: a subdomain label immediately under nexla.com/io
# appearing as a URL host. Excludes bare nexla.com, emails, and github refs.
INTERNAL_HOST_RE = r"://[A-Za-z0-9-]+\.nexla\.(com|io)"


def test_no_internal_nexla_deployment_hosts() -> None:
    result = subprocess.run(
        ["git", "grep", "-nIE", INTERNAL_HOST_RE],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # git grep exits 1 when there are no matches (the desired state);
    # exit 0 means an internal hostname reappeared somewhere.
    assert result.returncode == 1, (
        "Internal Nexla deployment hostname(s) found in tracked files; "
        "replace with a generic placeholder:\n" + result.stdout
    )
