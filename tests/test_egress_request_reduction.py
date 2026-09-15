from pathlib import Path

from ai_trader import foundation, portfolio_intelligence
from ai_trader.models import AutoTradeConfig, GuardrailConfig


class TracedConnection:
    def __init__(self, connection, statements):
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "_statements", statements)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __setattr__(self, name, value):
        setattr(self._connection, name, value)

    def execute(self, statement, parameters=()):
        self._statements.append(" ".join(statement.split()))
        return self._connection.execute(statement, parameters)

    def close(self):
        return self._connection.close()

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, *args):
        return self._connection.__exit__(*args)


def test_policy_snapshot_uses_one_select_instead_of_five(tmp_path, monkeypatch):
    db = tmp_path / "policy.db"
    foundation.initialize_foundation_schema(db)
    statements = []
    real_connect = foundation.connect

    def traced(path):
        return TracedConnection(real_connect(path), statements)

    monkeypatch.setattr(foundation, "connect", traced)
    foundation.load_trading_policy(
        db, auto_trade=AutoTradeConfig(), guardrails=GuardrailConfig()
    )
    policy_reads = [
        sql for sql in statements
        if sql.upper().startswith("SELECT") and "_POLICIES" in sql.upper()
    ]
    assert len(policy_reads) == 1
    assert "UNION ALL" in policy_reads[0]


def test_portfolio_metadata_reads_only_held_symbols(tmp_path, monkeypatch):
    db = tmp_path / "portfolio.db"
    portfolio_intelligence.initialize_portfolio_intelligence_schema(db)
    with portfolio_intelligence.connect(db) as conn:
        with conn:
            for symbol in ("AAA", "BBB", "UNHELD"):
                conn.execute(
                    "INSERT INTO ASSET_METADATA(created_at,symbol,asset_class,underlying_risk_factors_json,source,confidence) "
                    "VALUES (?,?,?,?,?,?)",
                    ("2026-09-15", symbol, "equity", "[]", "test", "1.0"),
                )

    statements = []
    real_connect = portfolio_intelligence.connect

    def traced(path):
        return TracedConnection(real_connect(path), statements)

    monkeypatch.setattr(portfolio_intelligence, "connect", traced)
    rows = portfolio_intelligence._metadata_by_symbol(db, {"aaa", "BBB"})
    assert set(rows) == {"AAA", "BBB"}
    read = next(sql for sql in statements if sql.upper().startswith("SELECT * FROM ASSET_METADATA"))
    assert "UPPER(symbol) IN (?,?)" in read

    statements.clear()
    assert portfolio_intelligence._metadata_by_symbol(db, set()) == {}
    assert statements == []
