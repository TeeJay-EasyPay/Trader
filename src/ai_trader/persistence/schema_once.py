from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from ..database import selected_backend

"""Shared "run this schema setup exactly once per process" helper.

Six modules (kraken_reconciliation.py, trading_intelligence.py, multi_broker.py,
operational.py, foundation.py, production_spine.py, plus always_on.py/canonical_trades.py
independently) each hand-rolled an identical pattern on 2026-08-01 to fix the same bug:
an `initialize_*_schema` function that ran its full `CREATE TABLE`/`ALTER`/seed sequence
unconditionally on *every call* instead of once per process -- the dominant, invisible
cost behind several chronic worker-job timeouts, since every job run is its own fresh
process and every one of these statements is idempotent.

This module is that pattern, written once, so no ninth copy gets hand-rolled the next
time a new schema-owning module needs it. It does not change what any schema function
creates -- only how many times it's allowed to run per process.
"""

_LOCK = threading.Lock()
_INITIALIZED: set[str] = set()


def schema_key(db_path: Path, namespace: str) -> str:
    """A per-process cache key for one schema-owning module.

    On Postgres, every job process shares the same database regardless of the
    (test-only, ignored) db_path argument, so the namespace alone is the key -- this
    matches every existing per-module `_schema_key` implementation. On SQLite, the
    resolved db_path is also part of the key so that tests using different temporary
    database files in the same process never collide with each other's cache entries.
    """

    if selected_backend() == "postgres":
        return f"postgres:{namespace}"
    return f"sqlite:{namespace}:{Path(db_path).resolve()}"


def ensure_schema_once(db_path: Path, namespace: str, init_fn: Callable[[], None]) -> None:
    """Run init_fn at most once per (namespace, backend/db_path) combination per process.

    Thread-safe via double-checked locking against a single shared lock -- schema
    initialization is infrequent enough (at most once per module per process) that one
    shared lock across every caller creates no meaningful contention, and it removes the
    need for every module to declare its own `_SCHEMA_LOCK` global.

    `namespace` should be a short, stable, unique string per calling module (e.g. the
    module name) -- it is the only thing that distinguishes one module's cache entry
    from another's.
    """

    key = schema_key(db_path, namespace)
    if key in _INITIALIZED:
        return
    with _LOCK:
        if key in _INITIALIZED:
            return
        init_fn()
        _INITIALIZED.add(key)


def reset_for_tests() -> None:
    """Clear the process-wide cache. Test-only -- production code never needs this,

    since real jobs never want a schema function to re-run after its first success in a
    given process. Tests that construct multiple temporary databases across test cases
    within the same pytest process should call this in setUp/tearDown if they rely on a
    schema function's seed-writing side effects running again for a fresh database.
    """

    with _LOCK:
        _INITIALIZED.clear()
