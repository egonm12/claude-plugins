"""The guard that every router step runs through."""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def guarded(step: Callable[[], T], default: T) -> T:
    """Run one step. Any error gives the default instead, so the hook fails open."""
    try:
        return step()
    except Exception:
        return default
