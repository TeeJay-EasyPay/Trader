"""September 8 live XLM fill was incorrectly narrated as 'no trades'. No live I/O."""
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ai_trader.audit import AuditDatabase
from ai_trader.database import connect, HybridRow
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.cycle_runner import _summarise_orders, _summarise_proposals, _conclusion, start_cycle
from ai_trader.application.research_service import ResearchService


@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'report.db'
    initialize_foundation_schema(path)
    AuditDatabase(path, None).initialize()
    return path


def proposal(conn, ident, broker):
    conn.execute("""INSERT INTO trade_audit
        (created_at, proposal_id, event_type, broker, payload_json)
        VALUES ('2099-01-01', ?, 'agent_proposal', ?, '{}')""", (ident, broker))


def execution(conn, ident, order, decision='approved'):
    conn.execute("""INSERT INTO EXECUTION_DECISIONS
        (created_at, proposal_id, symbol, decision, order_id, payload_json)
        VALUES ('2099-01-01', ?, 'XLM', ?, ?, '{}')""", (ident, decision, order))


def test_actual_execution_counts_without_nonexistent_audit_event_and_deduplicates(db):
    with closing(connect(db)) as conn, conn:
        proposal(conn, 'xlm', 'kraken')
        proposal(conn, 'xlm', 'kraken')
        proposal(conn, 'stock', 'alpaca')
        execution(conn, 'xlm', 'filled-entry')
        execution(conn, 'xlm', 'filled-entry')
        execution(conn, 'xlm', None)
        execution(conn, 'xlm', '')
        execution(conn, 'xlm', 'rejected-id', 'rejected')
        execution(conn, 'stock', 'alpaca-order')
    result = _summarise_orders(db, '2098', 'Kraken')
    assert result.startswith('1 order(s) submitted to Kraken during this run')
    assert 'fills' in result  # submission is not proof of a fill
    cycle = start_cycle(db, scope='kraken', trigger_source='test')
    assert _conclusion(db, cycle, failed=False).startswith('1 order(s) submitted')


def test_unavailable_execution_table_is_not_reported_as_zero(tmp_path):
    assert 'Could not verify' in _summarise_orders(tmp_path / 'empty.db', '2098', 'Kraken')


def test_latest_decision_per_proposal_and_real_modal_reason_are_broker_scoped(db):
    with closing(connect(db)) as conn, conn:
        for ident in ('a', 'b', 'c', 'd'):
            proposal(conn, ident, 'kraken')
        proposal(conn, 'equity', 'alpaca')
        for ident, broker, result, reason in (
            ('a', 'kraken', 'rejected', 'old_reason'),
            ('a', 'kraken', 'approved', ''),
            ('b', 'kraken', 'rejected', 'stop_limit'),
            ('c', 'kraken', 'rejected', 'stop_limit'),
            ('d', 'kraken', 'rejected', 'newest_reason'),
            ('equity', 'alpaca', 'rejected', 'market_closed'),
        ):
            conn.execute("""INSERT INTO BROKER_DECISIONS
                (created_at, proposal_id, symbol, selected_broker, exchange,
                 broker_healthy, asset_available, market_open, result, reason)
                VALUES ('2099-01-01', ?, 'XLM', ?, '', 1, 1, 1, ?, ?)""",
                (ident, broker, result, reason))
    result = _summarise_proposals(db, '2098')
    assert '4 trade idea(s)' in result
    assert '1 passed the checks, 3 rejected' in result
    assert 'most common reason: stop limit' in result
    assert 'market closed' not in result


def test_postgres_mapping_rows_and_aggregate_only_sql(db):
    rows = [HybridRow(result='rejected', reason='stop_limit', count=12)]
    with patch('ai_trader.cycle_runner._rows', return_value=rows) as fetch:
        assert '12 rejected' in _summarise_proposals(db, '2098')
    sql = fetch.call_args.args[1].upper()
    assert 'COUNT(*)' in sql and 'GROUP BY' in sql
    assert 'PAYLOAD_JSON' not in sql and 'SELECT SYMBOL' not in sql


@pytest.mark.parametrize('include_analysis', [True, False])
def test_universe_refresh_can_skip_duplicate_research_but_default_is_compatible(include_analysis):
    service = object.__new__(ResearchService)
    service.settings = SimpleNamespace(db_path='unused', research_scheduler_interval_minutes=60)
    service._bootstrap_crypto_universe_from_kraken_permissions = Mock(return_value=['BTC'])
    service.run_crypto_analysis = Mock(return_value={'status': 'ok'})
    with patch('ai_trader.application.research_service.seed_kraken_first_universe',
               return_value={'status': 'ok', 'inserted': 1}), \
         patch('ai_trader.application.research_service.update_broker_runtime'):
        result = service.refresh_crypto_universe() if include_analysis else service.refresh_crypto_universe(include_analysis=False)
    assert service.run_crypto_analysis.call_count == int(include_analysis)
    assert ('crypto_analysis' in result) == include_analysis


@pytest.mark.parametrize('policy_cap,crypto_cap,expected', [(.05, .08, .05), (.08, .03, .03)])
def test_research_passes_stricter_stop_cap_without_an_extra_policy_read(policy_cap, crypto_cap, expected):
    service = object.__new__(ResearchService)
    service.settings = Mock()
    service.settings.auto_trade.crypto_max_stop_loss_pct = crypto_cap
    service.settings.auto_trade.crypto_risk_per_trade_pct = .01
    service.settings.openai_api_key = None
    service.audit = Mock()
    service.orchestrator = SimpleNamespace(adapters={'kraken': SimpleNamespace(configured=True)})
    service._account_context_lookup = Mock(return_value=SimpleNamespace(equity=1000))
    class ReachedGenerator(Exception):
        pass
    module = 'ai_trader.application.research_service.'
    with patch(module + 'record_operational_event'), \
         patch(module + 'load_trading_policy', return_value=SimpleNamespace(max_stop_loss_pct=policy_cap, min_ai_confidence=.70)) as policy, \
         patch(module + '_crypto_requested_notional', return_value=25), \
         patch(module + 'load_closed_trades', return_value=[]), \
         patch(module + 'propose_crypto_trades', side_effect=ReachedGenerator) as generate:
        with pytest.raises(ReachedGenerator):
            service.run_crypto_analysis(symbols=['BTC'])
    policy.assert_called_once()
    assert generate.call_args.kwargs['max_stop_loss_pct'] == expected
    assert generate.call_args.kwargs['min_confidence'] == .70
