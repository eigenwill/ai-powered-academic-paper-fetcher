"""Rich-backed logging configuration.

Call `configure_logging(verbose)` once at CLI startup. All modules use
`logging.getLogger(__name__)` and get the same handler.
"""
from __future__ import annotations

import logging

from rich.logging import RichHandler


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = RichHandler(
        rich_tracebacks=True,
        markup=False,
        show_time=False,
        show_path=verbose,
    )
    # Wipe any previous handlers so re-runs inside the same interpreter
    # (tests, REPL) don't accumulate duplicates.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    logging.basicConfig(level=level, handlers=[handler], format="%(message)s")

    # Quiet noisy third parties unless the user explicitly asked for verbose.
    if not verbose:
        for name in ("urllib3", "httpx", "httpcore", "LiteLLM", "playwright"):
            logging.getLogger(name).setLevel(logging.WARNING)
