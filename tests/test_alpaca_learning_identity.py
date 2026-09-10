from ai_trader.canonical_trades import register_execution_intent, link_broker_order, canonical_trade
from ai_trader.sprint6 import normalize_broker_events, process_learning_outbox
from test_sprint6_institutional_spine import proposal


def test_bracket_activity_fills_close_one_governed_trade_once(tmp_path):
    db = tmp_path / 'learning.db'
    p = proposal()
    logical = register_execution_intent(db, proposal=p, broker='alpaca', decision_context={
        'proposal': p.to_dict(), 'guardrails': {'passed': True},
        'intelligence': {'committee': {'strongest_argument_for': 'Trend', 'strongest_argument_against': 'Volatility'}},
    })
    link_broker_order(db, logical_trade_id=logical, broker_order_id='entry', order_role='entry', payload={
        'id': 'entry', 'side': 'buy', 'status': 'accepted',
        'legs': [{'id':'stop','side':'sell','status':'held'}, {'id':'target','side':'sell','status':'held'}],
    })
    def event(fill, order, side, price, qty):
        return {'id':fill,'order_id':order,'symbol':'AAPL','side':side,'type':'fill', 'qty':qty,'price':price,
                'transaction_time':'2026-09-09T12:00:00Z', 'broker_fee':0, 'exchange_fee':0}
    entry = event('entry-fill','entry','buy',100,0.1)
    partial = event('partial-exit','target','sell',105,0.04)
    closing = event('last-exit','target','sell',105,0.06)
    normal = lambda events: normalize_broker_events(db,broker='alpaca',events=events,source_endpoint='test')
    normal([entry, {'id':'entry','symbol':'AAPL','side':'buy','status':'filled','filled_qty':0.1,'filled_avg_price':100}])
    assert canonical_trade(db,logical)['entry_filled_quantity'] == 0.1
    assert not normal([partial])['terminal_learning']
    result=normal([closing])
    assert len(result['terminal_learning']) == 1
    assert canonical_trade(db,logical)['terminal'] == 1
    assert canonical_trade(db,logical)['proposal_id'] == p.proposal_id
    normal([entry,partial,closing])
    assert canonical_trade(db,logical)['exit_filled_quantity'] == 0.1
    learned = process_learning_outbox(db, worker_id='test-worker')
    assert learned['processed'] == 1
    assert learned['failed'] == 0
    assert process_learning_outbox(db, worker_id='test-worker')['processed'] == 0
    from ai_trader.learning_monitor import learning_health_snapshot
    health = learning_health_snapshot(db)
    assert health['brokers'][0]['terminal_trades'] == 1
    assert health['brokers'][0]['corrected_reviews'] == 1
    assert health['improvement_status'] == 'not_established'


def test_unlinked_same_symbol_exit_is_not_assumed_to_close_governed_trade(tmp_path):
    db = tmp_path / 'learning.db'
    p = proposal()
    logical=register_execution_intent(db,proposal=p,broker='alpaca',decision_context={'proposal':p.to_dict()})
    result=normalize_broker_events(db,broker='alpaca',events=[{'id':'manual-fill','order_id':'manual','symbol':'AAPL','side':'sell','type':'fill','qty':1,'price':105}],source_endpoint='test')
    assert not result['terminal_learning']
    assert canonical_trade(db,logical)['terminal'] == 0


def test_health_aggregates_have_unique_postgres_column_names_and_bound_patterns(tmp_path):
    import sqlite3
    from ai_trader.database import HybridRow
    from ai_trader.learning_monitor import learning_health_snapshot
    test_bracket_activity_fills_close_one_governed_trade_once(tmp_path)
    class Connection:
        def __init__(self, path):
            self.conn=sqlite3.connect(path)
        def execute(self, sql, params=()):
            assert '%' not in sql  # LIKE patterns must be bound, not psycopg format tokens.
            cursor=self.conn.execute(sql,params)
            names=[column[0] for column in cursor.description]
            assert len(names)==len(set(names))
            class Result:
                def fetchall(self):
                    return [HybridRow(dict(zip(names,row))) for row in cursor.fetchall()]
            return Result()
        def close(self):
            self.conn.close()
    result=learning_health_snapshot(tmp_path/'learning.db',connection_factory=Connection)
    assert result['all_run_stages'][0]['completed_missing_experience']==0
    assert result['experience_coverage'][0]['reporting_reviews_not_canonical_closures']==0


def test_polled_bracket_child_recovers_explicit_parent_link_without_symbol_pairing(tmp_path):
    db = tmp_path / 'learning.db'
    p = proposal()
    logical=register_execution_intent(db,proposal=p,broker='alpaca',decision_context={'proposal':p.to_dict()})
    link_broker_order(db,logical_trade_id=logical,broker_order_id='parent',payload={'id':'parent','status':'accepted','side':'buy'})
    # A previous poll knew the child existed but did not yet know its parent.
    normalize_broker_events(db,broker='alpaca',events=[
        {'id':'child','symbol':'AAPL','side':'sell','status':'held'},
    ],source_endpoint='test')
    result=normalize_broker_events(db,broker='alpaca',events=[
        {'id':'child','parent_order_id':'parent','symbol':'AAPL','side':'sell','status':'held'},
        {'id':'entryfill','order_id':'parent','symbol':'AAPL','side':'buy','type':'fill','qty':0.1,'price':100},
        {'id':'exitfill','order_id':'child','symbol':'AAPL','side':'sell','type':'fill','qty':0.1,'price':105},
    ],source_endpoint='test')
    assert len(result['terminal_learning']) == 1
    assert canonical_trade(db,logical)['net_pnl'] is None  # Unknown fees are not zero.
