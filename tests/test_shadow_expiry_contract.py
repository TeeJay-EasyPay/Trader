"""Partial follow-up must never be treated as completion of the holding horizon."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from ai_trader.shadow_outcomes import resolve_shadow_trades


class Connection:
    def __init__(self, candle):
        self.candle = candle
        self.rows = []
        self.updates = []

    def execute(self, sql, params=()):
        if "SELECT shadow_trade_id" in sql:
            self.rows = [(1, "2026-09-07T12:00:00+00:00", "BTC", "test", 100, 90, 120)]
        elif "SELECT UPPER(normalized_symbol)" in sql:
            self.rows = [self.candle]
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


@pytest.mark.parametrize("current_day,high,low,expected", [
    (9, 105, 95, None),
    (15, 105, 95, "expired"),
    (9, 125, 95, "target_hit"),
    (9, 105, 85, "stop_hit"),
    (9, 125, 85, "stop_hit"),
])
def test_partial_horizon_and_terminal_levels(tmp_path, current_day, high, low, expected):
    conn = Connection(("BTC", "2026-09-08T00:00:00+00:00", high, low, 102))
    with patch("ai_trader.shadow_outcomes.connect", return_value=conn):
        result = resolve_shadow_trades(tmp_path / "unused.db", now=datetime(2026, 9, current_day, tzinfo=timezone.utc))
    if expected is None:
        assert result["still_pending"] == 1
        assert conn.updates == []
    else:
        assert result["by_outcome"] == {expected: 1}
        assert conn.updates[0][0] == expected
