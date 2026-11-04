"""Session-scoped grants for explicitly approved external write locations."""

from __future__ import annotations

import os
import threading
from typing import Iterable, List


_LOCK = threading.RLock()
_WRITE_ROOTS = set()


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([_normalize(path), _normalize(root)]) == _normalize(root)
    except (TypeError, ValueError):
        return False


def grant_write_access(path: str, *, is_directory: bool = False) -> str:
    """Allow writes below this path until the current Agent task finishes."""
    target = _normalize(path)
    root = target if is_directory else os.path.dirname(target)
    with _LOCK:
        _WRITE_ROOTS.add(root)
    return root


def list_granted_write_roots() -> List[str]:
    with _LOCK:
        return sorted(_WRITE_ROOTS)


def revoke_write_access(roots: Iterable[str]) -> None:
    with _LOCK:
        for root in roots or []:
            _WRITE_ROOTS.discard(_normalize(root))
