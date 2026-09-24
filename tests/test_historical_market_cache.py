from pathlib import Path
from types import SimpleNamespace

from ai_trader import historical_market_cache as cache


def settings():
    return SimpleNamespace(alpaca_api_key='key', alpaca_secret_key='secret',
                           alpaca_data_base_url='https://data.example')


def test_alpaca_backfill_is_cached_and_same_day_does_not_download(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_TRADER_RESEARCH_CACHE_DIR', str(tmp_path / 'cache'))
    calls = []
    monkeypatch.setattr(cache, '_fetch_alpaca', lambda *_args: calls.append(_args) or [
        {'t':'2026-09-15T00:00:00+00:00','o':100,'h':110,'l':90,'c':105},
    ])
    first = cache.refresh(tmp_path / 'db.sqlite3', settings(), 'alpaca', ['MSFT'],
                          '2026-09-17T01:00:00+00:00')
    second = cache.refresh(tmp_path / 'db.sqlite3', settings(), 'alpaca', ['MSFT'],
                           '2026-09-17T12:00:00+00:00')
    assert first['downloaded'] == 1 and len(first['bars']) == 1
    assert second['downloaded'] == 0 and second['bars'] == first['bars']
    assert len(calls) == 1 and first['supabase_rows_written'] == 0


def test_kraken_cache_keeps_old_bars_when_one_refresh_fails(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_TRADER_RESEARCH_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setattr(cache, 'fetch_kraken_ohlc', lambda *_args, **_kw: [
        {'observation_time':'2026-09-15T00:00:00+00:00','open':1,'high':2,'low':.5,'close':1.5},
    ])
    first = cache.refresh(tmp_path / 'db.sqlite3', settings(), 'kraken', ['XRPGBP'],
                          '2026-09-17T01:00:00+00:00')
    monkeypatch.setattr(cache, 'fetch_kraken_ohlc', lambda *_args, **_kw: (_ for _ in ()).throw(TimeoutError()))
    later = cache.refresh(tmp_path / 'db.sqlite3', settings(), 'kraken', ['XRPGBP'],
                          '2026-09-18T01:00:00+00:00')
    assert len(first['bars']) == len(later['bars']) == 1
    assert later['status'] == 'partial' and later['errors'][0]['error_type'] == 'TimeoutError'


def test_cached_bars_returns_only_verified_matching_equity_history(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_TRADER_RESEARCH_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setattr(cache, '_fetch_alpaca', lambda *_args: [
        {'t':'2026-09-15T00:00:00+00:00','o':100,'h':110,'l':90,'c':105},
    ])
    cache.refresh(tmp_path / 'db.sqlite3', settings(), 'alpaca', ['MSFT'],
                  '2026-09-17T01:00:00+00:00')
    bars = cache.cached_bars(tmp_path / 'db.sqlite3', 'alpaca', ['MSFT'])
    assert len(bars) == 1
    assert bars[0]['symbol'] == 'MSFT' and bars[0]['quality'] == 'verified_unadjusted'

