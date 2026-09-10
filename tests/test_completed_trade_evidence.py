import sqlite3
from unittest.mock import patch

from ai_trader.completed_trade_evidence import completed_trade_evidence


def test_shared_periods_keep_currencies_and_missing_costs_separate(tmp_path):
    db = tmp_path / 'evidence.sqlite'
    with sqlite3.connect(db) as c:
        c.executescript('''
        CREATE TABLE KRAKEN_RECONCILED_RESULTS(status,exit_time,net_pnl,gross_pnl,
          exchange_fee,broker_fee,holding_seconds,proposal_id,original_stop,entry_time);
        CREATE TABLE PERFORMANCE_ATTRIBUTION(broker,closed_at,profit_loss,
          holding_period_seconds,proposal_id,exit_price,exit_reason,opened_at);
        INSERT INTO KRAKEN_RECONCILED_RESULTS VALUES
          ('closed','2026-09-10T10:00:00+00:00',-2,3,5,0,7200,'p1',95,NULL),
          ('closed','2026-09-05T10:00:00+00:00',-4,NULL,NULL,0,NULL,NULL,NULL,NULL),
          ('closed','bad-date',999,999,0,0,1,'bad',10,NULL);
        INSERT INTO PERFORMANCE_ATTRIBUTION VALUES
          ('alpaca','2026-09-10T10:00:00+00:00',20,3600,NULL,12,'target',NULL);
        ''')
    with patch('ai_trader.completed_trade_evidence.uses_postgres', return_value=False), \
         patch('ai_trader.completed_trade_evidence.connect', side_effect=lambda _: sqlite3.connect(db)) as connections:
        result = completed_trade_evidence(db, now_epoch=1789041600)
    assert connections.call_count == 4  # two period reads and two exit-reason reads
    kraken = result['brokers']['kraken']['periods']
    assert kraken['day']['total'] == 1
    assert kraken['day']['gross_pnl'] == 3
    assert kraken['day']['recorded_fees'] == 5
    assert kraken['day']['net_pnl'] == -2
    assert kraken['day']['average_holding_seconds'] == 7200
    assert kraken['week']['gross_pnl'] is None
    assert kraken['week']['missing_proposal_links'] == 1
    alpaca = result['brokers']['alpaca']
    assert alpaca['periods']['day']['gross_pnl'] == 20
    assert alpaca['periods']['day']['net_pnl'] is None
    assert alpaca['recorded_exit_reasons_30d'][0]['reason'] == 'target'


def test_empty_windows_preserve_zero_counts_and_unknown_amounts(tmp_path):
    db = tmp_path / 'empty.sqlite'
    with sqlite3.connect(db) as c:
        c.execute('''CREATE TABLE KRAKEN_RECONCILED_RESULTS(status,exit_time,net_pnl,gross_pnl,
          exchange_fee,broker_fee,holding_seconds,proposal_id,original_stop,entry_time)''')
    c.close()
    with patch('ai_trader.completed_trade_evidence.uses_postgres', return_value=False), \
         patch('ai_trader.completed_trade_evidence.connect', side_effect=lambda _: sqlite3.connect(db)):
        result = completed_trade_evidence(db, now_epoch=1789041600)
    for bucket in result['brokers']['kraken']['periods'].values():
        assert bucket['available'] is True
        assert bucket['total'] == bucket['missing_proposal_links'] == 0
        assert bucket['net_pnl'] is None


def test_missing_tables_are_unavailable_not_zero(tmp_path):
    with patch('ai_trader.completed_trade_evidence.connect', side_effect=lambda _: sqlite3.connect(':memory:')):
        result = completed_trade_evidence(tmp_path / 'none')
    assert result['brokers']['kraken']['periods']['day']['available'] is False


def test_epoch_holding_times_reach_reconciliation():
    from ai_trader.kraken_reconciliation import _elapsed_seconds
    assert _elapsed_seconds('1789041600', '1789045200') == 3600
    assert _elapsed_seconds('1789045200', '1789041600') is None
    assert _elapsed_seconds('bad', '1789045200') is None


def test_review_does_not_call_gross_profit_net():
    from ai_trader.experience_engine import _what_happened
    text = _what_happened({'symbol': 'TEST', 'profit_loss': 20,
        'gross_realized_pnl': 20, 'net_realized_pnl': 19, 'fees_status': 'unavailable'})
    assert 'before-fee result 20.00' in text
    assert 'net after recorded fees unavailable' in text
