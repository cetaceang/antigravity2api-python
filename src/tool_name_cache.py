"""In-memory tool name mappings (sessionId + model + safeName scoped)."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Optional


ENTRY_TTL_SECONDS = 30 * 60
CLEAN_INTERVAL_SECONDS = 10 * 60
MAX_ENTRIES = 512


@dataclass(frozen=True)
class _Entry:
    original_name: str
    ts: float


_lock = RLock()
_last_cleanup_ts = 0.0

_cache: "OrderedDict[str, _Entry]" = OrderedDict()


def _make_key(session_id: Optional[str], model: Optional[str], safe_name: Optional[str]) -> str:
    return f"{session_id or ''}::{model or ''}::{safe_name or ''}"


def _prune_size() -> None:
    while len(_cache) > MAX_ENTRIES:
        _cache.popitem(last=False)


def _prune_expired(now: float) -> None:
    expired_keys = []
    for key, entry in _cache.items():
        if now - entry.ts > ENTRY_TTL_SECONDS:
            expired_keys.append(key)
    for key in expired_keys:
        _cache.pop(key, None)


def _maybe_cleanup(now: float) -> None:
    global _last_cleanup_ts
    if now - _last_cleanup_ts < CLEAN_INTERVAL_SECONDS:
        return
    _prune_expired(now)
    _last_cleanup_ts = now


def set_tool_name_mapping(
    session_id: Optional[str],
    model: Optional[str],
    safe_name: Optional[str],
    original_name: Optional[str],
) -> None:
    if not safe_name or not original_name or safe_name == original_name:
        return
    key = _make_key(session_id, model, safe_name)
    now = time.time()
    with _lock:
        _maybe_cleanup(now)
        _cache[key] = _Entry(original_name=str(original_name), ts=now)
        _prune_size()


def get_original_tool_name(
    session_id: Optional[str],
    model: Optional[str],
    safe_name: Optional[str],
) -> Optional[str]:
    if not safe_name:
        return None
    key = _make_key(session_id, model, safe_name)
    now = time.time()
    with _lock:
        _maybe_cleanup(now)
        entry = _cache.get(key)
        if not entry:
            return None
        if now - entry.ts > ENTRY_TTL_SECONDS:
            _cache.pop(key, None)
            return None
        return entry.original_name


def clear_tool_name_mappings() -> None:
    with _lock:
        _cache.clear()

