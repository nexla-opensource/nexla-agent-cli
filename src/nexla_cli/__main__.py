"""Enable ``python -m nexla_cli`` to run the same entrypoint as the
installed ``nexla-cli`` console script.

The console script (``nexla-cli = "nexla_cli:main"``) and this module both
call :func:`nexla_cli.main`, so subprocess-level contract tests can drive
the real ``main()`` (argv reordering, stdio wiring, exit-code mapping)
without depending on the console script being on PATH.
"""

from __future__ import annotations

from . import main

if __name__ == "__main__":
    main()
