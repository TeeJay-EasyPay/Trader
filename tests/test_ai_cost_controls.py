import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ai_trader.ai import _symbol_market
from ai_trader.forecasting import generate_market_forecast


def test_research_cadence_does_not_slow_candle_refresh(tmp_path):
    from test_benchmark_research_refresh import settings_for
    from ai_trader.cli import _due_worker_jobs
    settings = settings_for(str(tmp_path), worker_research_enabled=True,
                            research_scheduler_interval_minutes=60, external_intelligence_enabled=False)
    first = dict(_due_worker_jobs(settings, datetime(2026, 9, 11, 14, 5, tzinfo=timezone.utc)))
    next_hour = dict(_due_worker_jobs(settings, datetime(2026, 9, 11, 15, 5, tzinfo=timezone.utc)))
    later = dict(_due_worker_jobs(settings, datetime(2026, 9, 11, 16, 5, tzinfo=timezone.utc)))
    for job in ('crypto-research', 'market-open-equity'):
        assert first[job] == next_hour[job]
        assert first[job] != later[job]
    assert first['crypto-candle-refresh'] != next_hour['crypto-candle-refresh']


def test_symbol_payload_preserves_own_history_and_shared_context():
    market = {'bars': {'MSFT': {'c': 100}, 'AAPL': {'c': 200}},
              'history': {'MSFT': [{'close': 99}], 'AAPL': [{'close': 199}]},
              'feed': 'iex', 'market_regime': 'uncertain'}
    before = deepcopy(market)
    result = _symbol_market('MSFT', market)
    assert result['bars'] == {'MSFT': {'c': 100}}
    assert result['history'] == {'MSFT': [{'close': 99}]}
    assert result['market_regime'] == 'uncertain'
    assert market == before
    assert _symbol_market('MSFT', {'bars': []}) == {'bars': []}


def test_forecast_reuse_is_exact_and_bounded():
    from types import SimpleNamespace
    evidence = {'daily': {'candles_available': 30, 'latest_close': 5}}
    current = datetime.now(timezone.utc).isoformat()
    previous = {'forecast_id': 12, 'asset_type': 'stock', 'generated_by': 'same',
                'created_at': current, 'expires_at': '2099-01-01T00:00:00+00:00',
                'evidence_json': json.dumps({'evidence': evidence})}
    calls = []
    analyzer = SimpleNamespace(model='same', forecast=lambda **kw: calls.append(kw))
    with patch('ai_trader.forecasting.build_forecast_evidence', return_value=evidence), \
         patch('ai_trader.forecasting.latest_forecast', return_value=previous):
        def run():
            return generate_market_forecast(Path('unused'), analyzer=analyzer, symbol='MSFT', asset_type='stock')
        assert run()['status'] == 'reused_unchanged'
        assert not calls
        previous['created_at'] = '2020-01-01T00:00:00+00:00'
        assert run()['status'] == 'no_usable_forecast'
        previous['created_at'] = current
        previous['generated_by'] = 'other'
        assert run()['status'] == 'no_usable_forecast'
        previous['generated_by'] = 'same'
        previous['expires_at'] = '2020-01-01T00:00:00+00:00'
        assert run()['status'] == 'no_usable_forecast'
        previous['expires_at'] = '2099-01-01T00:00:00+00:00'
        evidence['daily']['latest_close'] = 6
        assert run()['status'] == 'no_usable_forecast'
        assert len(calls) == 4
