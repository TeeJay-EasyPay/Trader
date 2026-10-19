from unittest.mock import Mock

from ai_trader.broker_learning_packet import _simulation_evidence


def test_broker_totals_are_not_per_experiment_acceptance_evidence():
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = []
    result = _simulation_evidence(conn, 'alpaca', 'stock', 'USD')
    assert result['eligible_for_per_experiment_threshold_comparison'] is False
    assert 'not unique independent' in result['modern_count_scope']
    assert 'never compare their sum' in result['plain_english']
