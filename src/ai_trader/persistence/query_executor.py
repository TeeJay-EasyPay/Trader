from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from ..database import connect

_COUNTABLE_TABLES = {
    "INVESTMENT_WATCHLIST",
    "MARKET_THEMES",
    "BENCHMARK_TRADERS",
    "trade_audit",
    "CRYPTO_ASSET_MASTER",
    "BENCHMARK_DAILY_RESEARCH",
    "CRYPTO_MASTER",
    "DUE_DILIGENCE_ASSESSMENTS",
}


class QueryExecutor:
    """Injected, explicit-composition replacement for LocalApiService's own
    _connect/_row/_rows/_scalar/_count methods (architecture/AI_TRADER_MODULARISATION_
    ARCHITECTURE_2026-08-02.md Phase 2). Callers hold a QueryExecutor instance and call
    its methods explicitly -- not a mixin, no inheritance.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def row(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with closing(self.connect()) as conn:
            return conn.execute(sql, params).fetchone()

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return list(conn.execute(sql, params))

    def scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        row = self.row(sql, params)
        return None if row is None else row[0]

    def count(self, table: str, where: str | None = None) -> int:
        if table not in _COUNTABLE_TABLES:
            raise ValueError(f"Unsupported count table: {table}")
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return int(self.scalar(sql) or 0)
