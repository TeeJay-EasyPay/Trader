"""Bounded missing-data fallback: GET-only market-data host, no trading client."""
import json
from datetime import timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import experiments as e


def missing_bars(db, settings, symbols, now):
    if not symbols or not getattr(settings, 'alpaca_api_key', None) or not getattr(settings, 'alpaca_secret_key', None):
        return []
    with e.transaction(db) as conn:
        cache = e.control(conn, 'market_data_cache', {})
        if cache.get('day') == now[:10]:
            return [b for b in cache.get('bars', []) if b['symbol'] in symbols]
        # Reserve before network call; timeouts cannot cause a retry storm.
        e.put_control(conn, 'market_data_cache', {'day': now[:10], 'status': 'reserved', 'bars': []})
    chosen = sorted(set(symbols))[:20]
    query = urlencode(dict(symbols=','.join(chosen), timeframe='1Day', feed='iex', adjustment='raw',
                           start=(e.stamp(now) - timedelta(days=14)).date().isoformat(),
                           end=e.stamp(now).date().isoformat(), limit=1000))
    request = Request('https://data.alpaca.markets/v2/stocks/bars?' + query, method='GET',
                      headers={'APCA-API-KEY-ID': settings.alpaca_api_key,
                               'APCA-API-SECRET-KEY': settings.alpaca_secret_key})
    try:
        with urlopen(request, timeout=8) as response:
            body = response.read(500001)
        if len(body) > 500000:
            raise ValueError('Market-data response budget exceeded')
        raw = json.loads(body)
        bars = []
        for symbol, values in (raw.get('bars') or {}).items():
            if symbol not in chosen:
                continue
            for b in values[:14]:
                start = e.stamp(b['t'])
                end = start + timedelta(days=1)
                if end <= e.stamp(now):
                    bars.append(dict(symbol=symbol, start=start.isoformat(), end=end.isoformat(),
                                     open=b['o'], high=b['h'], low=b['l'], close=b['c'],
                                     quality='verified_unadjusted', source='alpaca_raw_iex_daily'))
        cache = dict(day=now[:10], status='partial' if raw.get('next_page_token') else 'completed',
                     bars=bars, symbols=chosen, response_bytes=len(body))
    except Exception as exc:
        cache = dict(day=now[:10], status='unavailable', bars=[], error_type=type(exc).__name__)
    with e.transaction(db) as conn:
        e.put_control(conn, 'market_data_cache', cache)
    return cache['bars']
