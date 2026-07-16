"""`nexla-cli orgs` — list (real) / get (501).

Mirrors the deployed ``/nexla/*`` API. ``list`` proxies a real,
working endpoint (a bare array, not a ``Page[T]`` envelope) and gets the
same full treatment as any other resource for ``--output``/``--fields``;
only ``get`` 501s.

**``--page-all`` is explicitly rejected here**, not silently ignored.
``list`` takes no ``page``/``per_page`` params and the upstream endpoint
returns a bare array with no ``items``/``next_page`` keys, so
``client.paginate()`` cannot be wired against it (it would try to read
those keys off a list and break). Following the conservative stuck-resource
policy (pick the more conservative option when forced to choose between
reject-with-error and silent-ignore), an explicit ``CliError`` is raised
instead of quietly doing the wrong thing.
"""

from __future__ import annotations

import typer

from .. import client, output
from ..errors import EXIT, CliError
from ._common import not_in_v1

app = typer.Typer(name="orgs", help="Manage Nexla orgs.", no_args_is_help=True)

_COLUMNS = ["id", "name"]


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List orgs."""
    if output.ctx_page_all(ctx):
        raise CliError(
            EXIT.VALIDATION,
            "orgs list does not support --page-all (bare-array endpoint, no next_page)",
        )
    output.emit(
        client.request("GET", "/nexla/orgs"),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
        columns=_COLUMNS,
    )


@app.command("get", hidden=True)
def get(ctx: typer.Context, org_id: int) -> None:
    """Get one org by id. (Not implemented in v1.)"""
    not_in_v1("orgs get")
