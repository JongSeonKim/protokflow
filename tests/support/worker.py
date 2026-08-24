"""Helpers for identifying the current pytest-xdist process."""

from __future__ import annotations

import os


def worker_id() -> str:
    """Return the pytest-xdist worker id, or ``master`` without xdist."""
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


def worker_index() -> int:
    """Return a stable numeric index (master=0, gw0=1, gw1=2, ...)."""
    wid = worker_id()
    return 0 if wid == "master" else int(wid.removeprefix("gw")) + 1
