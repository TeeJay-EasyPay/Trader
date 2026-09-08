"""Offline reproductions for the independent Kraken review; no production writes."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ai_trader.shadow_outcomes import resolve_shadow_trades


class MemoryConnection:
    def __init__(self):
        self.rows = []
        self.updates = []

    def execute(self, sql, params=()):
        if "SELECT shadow_trade_id" in sql:
            self.rows = [(1, "2026-09-07T12:00:00+00:00", "BTC", "test", 100, 90, 120)]
        elif "SELECT UPPER(normalized_symbol)" in sql:
            self.rows = [("BTC", "2026-09-08T00:00:00+00:00", 105, 95, 102)]
        elif "UPDATE SHADOW_TRADES" in sql:
            self.updates.append(params)
        else:
            raise AssertionError(sql)
        return self

    def fetchall(self):
        return self.rows

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


conn = MemoryConnection()
with patch("ai_trader.shadow_outcomes.connect", return_value=conn):
    result = resolve_shadow_trades(
        Path("unused-audit-placeholder"), now=datetime(2026, 9, 9, tzinfo=timezone.utc)
    )
assert result["by_outcome"] == {}, result
assert result["still_pending"] == 1, result
assert conn.updates == [], conn.updates
print("VERIFIED FIX: a 36-hour-old candidate with neither stop nor target reached stays pending through its seven-day horizon.")
print("All database operations in this reproduction were replaced by an in-memory stub.")
