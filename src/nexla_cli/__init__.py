"""`nexla` — CLI client for the `/nexla/*` agent API.

Set ``NEXLA_API_URL`` and ``NEXLA_TOKEN`` in the environment (or run
``nexla-cli login --service-key ...`` to obtain a token first).

The application itself is assembled in :mod:`nexla_cli.cli`; this module
just re-exports the stable entry points (``app``, ``main``) and the argv
helpers the tests and console script depend on.
"""

from __future__ import annotations

from .cli import (
    _output_flag_from_argv,
    _reorder_global_flags,
    _split_global_flags,
    app,
    main,
)

__all__ = [
    "app",
    "main",
    "_reorder_global_flags",
    "_output_flag_from_argv",
    "_split_global_flags",
]
