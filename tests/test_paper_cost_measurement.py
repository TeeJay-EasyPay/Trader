import sqlite3
from datetime import datetime, timezone
import pytest
from ai_trader.paper_cost_measurement import measure
from ai_trader.alpaca_costs import estimate_alpaca_round_trip_cost
from ai_trader.experiment_diagnostics import diagnose

NOW = datetime(2026,10,6,tzinfo=timezone.utc)


@pytest.fixture
def conn():
    c = sqlite3.connect(':memory:')
    c.executescript('''CREATE TABLE LOGICAL_TRADES(logical_trade_id TEXT,broker TEXT,
      terminal INTEGER,side TEXT,gross_pnl REAL,net_pnl REAL,closed_at TEXT,
      average_entry_price REAL,average_exit_price REAL,exit_filled_quantity REAL);
      CREATE TABLE CLOSED_LOOP_LEARNING_RUNS(logical_trade_id TEXT,status TEXT,
      experience_id INTEGER,review_id INTEGER);''')
    yield c
    c.close()


def add(c, id='a', **kwargs):
    row = dict(logical_trade_id=id,broker='alpaca',terminal=1,side='buy',gross_pnl=3,
        net_pnl=None,closed_at='2026-10-05T10:00:00+00:00',average_entry_price=99,
        average_exit_price=100,exit_filled_quantity=3)
    row.update(kwargs)
    c.execute('INSERT INTO LOGICAL_TRADES VALUES (?,?,?,?,?,?,?,?,?,?)',tuple(row.values()))


def test_unreviewed_trades_are_measured_without_fabricating_actual_fees(conn):
    add(conn)
    report=measure(conn,NOW)
    period=report['periods']['last_7_days']
    assert period['reviewed']==0
    assert period['estimated_count']==1
    assert period['verified_net_count']==0
    assert period['estimated_net']==2.98
    assert conn.execute('SELECT net_pnl FROM LOGICAL_TRADES').fetchone()[0] is None


def test_coverage_no_double_count_and_no_200_row_truncation(conn):
    for i in range(205): add(conn,str(i))
    conn.executemany('INSERT INTO CLOSED_LOOP_LEARNING_RUNS VALUES (?,?,?,?)', [('0','completed',1,1)]*2)
    add(conn,'actual',net_pnl=2.9)
    add(conn,'missing',average_exit_price=None)
    add(conn,'kraken',broker='kraken')
    add(conn,'open',terminal=0)
    p=measure(conn,NOW)['periods']['all_recorded']
    assert (p['closed'],p['estimated_count'],p['verified_net_count'],p['unmeasured_count'])==(207,205,1,1)
    assert p['reviewed']==1
    assert p['verified_net_sum']==2.9


@pytest.mark.parametrize('price,qty',[(100,1),(1000,100),(12.34,0.1234),(2,100000)])
def test_frozen_estimate_matches_existing_cost_model(conn,price,qty):
    add(conn,average_exit_price=price,exit_filled_quantity=qty)
    expected=estimate_alpaca_round_trip_cost(sell_notional=price*qty,quantity=qty)['estimated_round_trip_fee_usd']
    assert measure(conn,NOW)['estimated_regulatory_costs']==expected


def test_short_uses_entry_sell_notional_and_periods_do_not_mix(conn):
    add(conn,side='sell',average_entry_price=1000,average_exit_price=10,exit_filled_quantity=10,
        closed_at='2026-09-01T00:00:00+00:00')
    r=measure(conn,NOW)
    assert r['estimated_regulatory_costs']==.22
    assert r['periods']['last_7_days']['status']=='no_closed_outcomes'
    assert r['periods']['last_7_days']['estimated_net'] is None


@pytest.mark.parametrize('value',[None,-1,0,float('inf'),float('nan')])
def test_invalid_inputs_are_missing_not_zero_cost(conn,value):
    add(conn,exit_filled_quantity=value)
    r=measure(conn,NOW)
    assert r['individual_results_estimated']==0
    assert r['periods']['all_recorded']['unmeasured_count']==1
    assert r['estimated_net_pnl'] is None


def test_diagnostics_distinguish_skips_and_identical_entries():
    assert diagnose({})['status']=='diagnostic_evidence_unavailable'
    assert diagnose(dict(observations=5,informative_completed=0,both_skipped=5))['status']=='all_opportunities_blocked'
    assert diagnose(dict(observations=5,informative_completed=3,decision_differences=3,closed_trades={'candidate':0}))['status']=='candidate_has_no_closed_trades'
    assert diagnose(dict(observations=5,informative_completed=3,decision_differences=0,closed_trades={'candidate':3}))['status']=='no_entry_selection_difference_observed'


def test_selected_period_and_dict_rows(conn):
    add(conn)
    add(conn,'old',closed_at='2026-09-15T00:00:00+00:00')
    conn.row_factory=lambda c,row: dict(zip([d[0] for d in c.description],row))
    r=measure(conn,NOW,since='2026-10-02T21:02:00Z')
    assert r['periods']['selected_period']['closed']==1
    assert r['periods']['all_recorded']['closed']==2
    with pytest.raises(ValueError): measure(conn,NOW,since='2026-10-07T00:00:00Z')
    with pytest.raises(ValueError): measure(conn,NOW,since='2026-10-02')


def test_empty_database_is_not_reported_as_zero_profit(conn):
    r=measure(conn,NOW)
    assert r['estimated_net_pnl'] is None
    assert r['periods']['all_recorded']['status']=='no_closed_outcomes'


def test_diagnostic_discloses_frozen_evidence_shortfall_without_lowering_gate():
    report=dict(observations=30,informative_completed=14,minimum_opportunities=60,
        day_clusters=6,minimum_independent_days=21,symbol_days=14,minimum_symbol_days=40)
    r=diagnose(report)
    assert r['frozen_sample_shortfalls']==dict(informative_completed=46,day_clusters=15,symbol_days=26)
    assert report['minimum_independent_days']==21
