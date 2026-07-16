"""`nexla-cli metrics` — planned, not implemented in v1.

Hidden from the top-level help; every command fails locally via
`not_in_v1` instead of round-tripping to a guaranteed-501 route.
"""

from __future__ import annotations

import typer

from ._common import not_in_v1

app = typer.Typer(name="metrics", help="Query Nexla metrics (not implemented in v1).", no_args_is_help=True)


@app.command("catalog")
def catalog(ctx: typer.Context) -> None:
    """List available metric types. (Not implemented in v1.)"""
    not_in_v1("metrics catalog")


@app.command("for-resource")
def for_resource(ctx: typer.Context, resource_type: str, resource_id: str) -> None:
    """Get all metrics for a resource. (Not implemented in v1.)"""
    not_in_v1("metrics for-resource")


@app.command("get")
def get(ctx: typer.Context, resource_type: str, resource_id: str, metric_type: str) -> None:
    """Get one metric for a resource. (Not implemented in v1.)"""
    not_in_v1("metrics get")
