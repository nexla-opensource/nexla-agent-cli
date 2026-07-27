"""Curated ``--help`` text: root epilog, command-group panels, EXAMPLES.

Data only — `cli.py` wires it in. Two mechanisms, both native to Typer, so
there is no custom Click formatter to maintain:

* ``PANELS`` maps a command-group name to the ``rich_help_panel`` it is
  registered under, which splits the root help's one flat COMMANDS list
  into gh-style sections.
* ``EXAMPLES`` maps ``"<group> <command>"`` (or just ``"<name>"`` for a
  root-level command) to that command's epilog.

Typer collapses *single* newlines inside an epilog into spaces and renders
a *double* newline as one line break, so every block here is written as
paragraphs joined by blank lines and `_block` does the joining. Square
brackets are avoided throughout: the epilog is rendered through Rich, which
would read ``[...]`` as console markup.

Every example is copied from the command's real signature. When a flag is
added, removed, or renamed, update the example here in the same change --
a stale example is worse than no example.
"""

from __future__ import annotations

from .errors import EXIT


def _block(title: str, lines: list[str]) -> str:
    """Render an epilog section: a heading then one line per entry."""
    return "\n\n".join([title, *lines])


def _examples(lines: list[str]) -> str:
    return _block("EXAMPLES", [f"$ {line}" for line in lines])


# Root help: which section each command group is listed under. A group
# missing from this map falls back to Typer's default "Commands" panel.
# Typer renders the panels in *alphabetical* order, not registration order,
# so the names are chosen to sort into reading order: Core, Discovery,
# Monitoring, Setup.
PANELS: dict[str, str] = {
    "sources": "Core resources",
    "sinks": "Core resources",
    "nexsets": "Core resources",
    "credentials": "Core resources",
    "flows": "Core resources",
    "transforms": "Core resources",
    "connectors": "Discovery & tooling",
    "probe": "Discovery & tooling",
    "toolsets": "Discovery & tooling",
    "tools": "Discovery & tooling",
    "mcp-servers": "Discovery & tooling",
    "triage": "Monitoring & triage",
    "login": "Setup & meta",
    "context": "Setup & meta",
    "orgs": "Setup & meta",
    "schema": "Setup & meta",
    "skill": "Setup & meta",
}

_EXIT_NOTES: dict[EXIT, str] = {
    EXIT.ERROR: "generic or unexpected failure",
    EXIT.VALIDATION: "bad local input, including a failed --dry-run",
    EXIT.CONFIG: "NEXLA_API_URL / NEXLA_TOKEN missing",
    EXIT.AUTH: "401 or 403 from the API",
    EXIT.NOT_FOUND: "404 from the API",
    EXIT.UPSTREAM: "5xx from the API",
}

# Generated from `errors.EXIT` so a new code can't be added without also
# showing up here. One code per line: Rich hard-wraps the epilog at
# terminal width, and a wrapped `6 upstream` is both ugly and ungreppable.
_EXIT_CODES = _block(
    "EXIT CODES",
    [
        f"{code.value} {code.name.lower()}{'   ' + _EXIT_NOTES[code] if code in _EXIT_NOTES else ''}"
        for code in EXIT
    ],
)

_MACHINE_CONTRACT = _block(
    "MACHINE CONTRACT",
    [
        "-o json|ndjson   force the output format (default: table on a TTY, json otherwise)",
        "--fields id,name   restrict every emitted record to these fields",
        "--page-all   stream every page as NDJSON instead of one page",
        "--dry-run   validate locally and fire no mutating call",
        "These four may appear anywhere in the command line. "
        "Errors go to stderr, results to stdout.",
    ],
)

# A *quadruple* newline is what survives Typer's collapsing as a blank
# line between sections (a triple newline degrades to a single break).
ROOT_EPILOG = "\n\n\n\n".join(
    [
        _examples(
            [
                "export NEXLA_TOKEN=$(nexla-cli login --service-key <your-service-key>)",
                "nexla-cli connectors search shopify",
                "nexla-cli sources list",
                "nexla-cli triage errors --from-date 2026-07-01",
            ]
        ),
        _EXIT_CODES,
        _MACHINE_CONTRACT,
        _block(
            "LEARN MORE",
            [
                "nexla-cli <group> --help    commands in a group",
                "nexla-cli <group> <command> --help    a command's flags and examples",
                "nexla-cli schema    machine-readable signatures for every command",
            ],
        ),
    ]
)

# Keyed by "<group> <command>", or a bare name for a root-level command.
EXAMPLES: dict[str, str] = {
    "login": _examples(
        [
            "nexla-cli login --service-key <your-service-key>",
            "export NEXLA_TOKEN=$(nexla-cli login --service-key <your-service-key>)",
            "nexla-cli login --service-key <your-service-key> --api-url https://<your-deployed-api>",
        ]
    ),
    "schema": _examples(
        [
            "nexla-cli schema",
            "nexla-cli schema sources.create",
            "nexla-cli schema triage.logs",
        ]
    ),
    "sources create": _examples(
        [
            "nexla-cli sources create --name orders --connector shopify_api "
            "--credential-id 7 --endpoint shopify_api.get_orders",
            "nexla-cli sources create --name events --connector s3 "
            "--credential-id 3 --config '{\"path\":\"/data\"}'",
            "nexla-cli sources create --name orders --connector s3 --credential-id 3 --dry-run",
        ]
    ),
    "sources list": _examples(
        [
            "nexla-cli sources list",
            "nexla-cli sources list --connector shopify_api",
            "nexla-cli sources list --access-role owner --per-page 100",
            "nexla-cli sources list --page-all",
        ]
    ),
    "sources get": _examples(
        [
            "nexla-cli sources get 42",
            "nexla-cli sources get 42 --wait-until source_nexset_id",
            "nexla-cli sources get 42 --wait-until status=ACTIVE --wait-timeout 120",
        ]
    ),
    "sources delete": _examples(
        [
            "nexla-cli sources pause 42",
            "nexla-cli sources delete 42",
            "nexla-cli sources delete 42 --dry-run",
        ]
    ),
    "sinks create": _examples(
        [
            "nexla-cli sinks create --name warehouse --nexset-id 5 --credential-id 8 "
            "--connector bigquery --config '{\"table\":\"orders\"}'",
            "nexla-cli sinks create --name warehouse --nexset-id 5 --credential-id 8 "
            "--connector bigquery --config '{\"table\":\"orders\"}' --dry-run",
            "nexla-cli sinks create --name supa --nexset-id 5 --credential-id 8 "
            "--connector supabase --config '{\"table\":\"orders\"}' --skip-table-check",
        ]
    ),
    "sinks list": _examples(
        [
            "nexla-cli sinks list",
            "nexla-cli sinks list --connector bigquery",
            "nexla-cli sinks list --per-page 100 --page 2",
        ]
    ),
    "nexsets list": _examples(
        [
            "nexla-cli nexsets list",
            "nexla-cli nexsets list --flow-id 3",
            "nexla-cli nexsets list --parent-id 100 --page-all",
        ]
    ),
    "credentials list": _examples(
        [
            "nexla-cli credentials list",
            "nexla-cli credentials list --connector shopify_api",
            "nexla-cli credentials list --kind s3 --per-page 100",
        ]
    ),
    "credentials get": _examples(
        [
            "nexla-cli credentials get 7",
            "nexla-cli credentials get 7 -o json",
            "nexla-cli credentials get 7 --fields id,name",
        ]
    ),
    "flows list": _examples(
        [
            "nexla-cli flows list",
            "nexla-cli flows list --status ACTIVE",
            "nexla-cli flows list --q orders --per-page 100",
        ]
    ),
    "triage errors": _examples(
        [
            "nexla-cli triage errors",
            "nexla-cli triage errors --from-date 2026-07-01 --limit 20",
            "nexla-cli triage errors --from-date 2026-07-01 --to-date 2026-07-08 -o json",
        ]
    ),
    "triage status": _examples(
        [
            "nexla-cli triage status 631618",
            "nexla-cli triage status 631618 --run-id 12345",
            "nexla-cli triage status 631618 --dry-run",
        ]
    ),
    "triage logs": _examples(
        [
            "nexla-cli triage logs 631618 --severity ERROR",
            "nexla-cli triage logs 631618 --run-id 12345 --size 100",
            "nexla-cli triage logs 631618 --search timeout --from-date 2026-07-01",
        ]
    ),
}
