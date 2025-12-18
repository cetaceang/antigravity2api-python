"""In-memory caches for reasoning/tool thought signatures (sessionId + model scoped)."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Optional


ENTRY_TTL_SECONDS = 30 * 60
CLEAN_INTERVAL_SECONDS = 10 * 60
MAX_REASONING_ENTRIES = 256
MAX_TOOL_ENTRIES = 256


@dataclass(frozen=True)
class _Entry:
    signature: str
    ts: float


_lock = RLock()
_last_cleanup_ts = 0.0

_reasoning_cache: "OrderedDict[str, _Entry]" = OrderedDict()
_tool_cache: "OrderedDict[str, _Entry]" = OrderedDict()


def _make_key(session_id: Optional[str], model: Optional[str]) -> str:
    return f"{session_id or ''}::{model or ''}"


def _prune_size(cache: "OrderedDict[str, _Entry]", max_entries: int) -> None:
    while len(cache) > max_entries:
        cache.popitem(last=False)


def _prune_expired(cache: "OrderedDict[str, _Entry]", now: float) -> None:
    expired_keys = []
    for key, entry in cache.items():
        if now - entry.ts > ENTRY_TTL_SECONDS:
            expired_keys.append(key)
    for key in expired_keys:
        cache.pop(key, None)


def _maybe_cleanup(now: float) -> None:
    global _last_cleanup_ts
    if now - _last_cleanup_ts < CLEAN_INTERVAL_SECONDS:
        return
    _prune_expired(_reasoning_cache, now)
    _prune_expired(_tool_cache, now)
    _last_cleanup_ts = now


def set_reasoning_signature(session_id: Optional[str], model: Optional[str], signature: Optional[str]) -> None:
    if not signature:
        return
    key = _make_key(session_id, model)
    now = time.time()
    with _lock:
        _maybe_cleanup(now)
        _reasoning_cache[key] = _Entry(signature=str(signature), ts=now)
        _prune_size(_reasoning_cache, MAX_REASONING_ENTRIES)


def get_reasoning_signature(session_id: Optional[str], model: Optional[str]) -> Optional[str]:
    key = _make_key(session_id, model)
    now = time.time()
    with _lock:
        _maybe_cleanup(now)
        entry = _reasoning_cache.get(key)
        if not entry:
            return None
        if now - entry.ts > ENTRY_TTL_SECONDS:
            _reasoning_cache.pop(key, None)
            return None
        return entry.signature


def set_tool_signature(session_id: Optional[str], model: Optional[str], signature: Optional[str]) -> None:
    if not signature:
        return
    key = _make_key(session_id, model)
    now = time.time()
    with _lock:
        _maybe_cleanup(now)
        _tool_cache[key] = _Entry(signature=str(signature), ts=now)
        _prune_size(_tool_cache, MAX_TOOL_ENTRIES)


def get_tool_signature(session_id: Optional[str], model: Optional[str]) -> Optional[str]:
    key = _make_key(session_id, model)
    now = time.time()
    with _lock:
        _maybe_cleanup(now)
        entry = _tool_cache.get(key)
        if not entry:
            return None
        if now - entry.ts > ENTRY_TTL_SECONDS:
            _tool_cache.pop(key, None)
            return None
        return entry.signature


def clear_signature_caches() -> None:
    with _lock:
        _reasoning_cache.clear()
        _tool_cache.clear()

