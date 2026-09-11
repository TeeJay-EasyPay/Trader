"""Bounded missing-data fallback: GET-only market-data host, no trading client."""
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import experiments as e


def missing_bars(db, settings, symbols, now, *, broker='alpaca'):
    if broker == 'kraken':
        return kraken_bars(db, symbols, now)
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


def kraken_bars(db, symbols, now):
    """At most two public GBP-pair requests/day. No authentication or order host."""
    with e.transaction(db) as conn:
        cache = e.control(conn, 'kraken_shadow_bars', {})
        if cache.get('day') == now[:10]:
            return [b for b in cache.get('bars', []) if b['symbol'] in symbols]
        e.put_control(conn, 'kraken_shadow_bars', dict(day=now[:10], status='reserved', bars=[]))
    bars, errors = [], []
    chosen = [s for s in sorted(set(symbols)) if s.isalnum() and s.endswith('GBP')][:2]
    for symbol in chosen:
        query = urlencode(dict(pair=symbol, interval=1440, since=int((e.stamp(now) - timedelta(days=14)).timestamp())))
        try:
            with urlopen(Request('https://api.kraken.com/0/public/OHLC?' + query, method='GET'), timeout=4) as response:
                body = response.read(100001)
            if len(body) > 100000:
                raise ValueError('Response budget exceeded')
            raw = json.loads(body)
            if raw.get('error'):
                raise ValueError('Kraken market data unavailable')
            series = [v for k, v in raw['result'].items() if k != 'last']
            if len(series) != 1:
                raise ValueError('Ambiguous pair response')
            for values in series[0][-15:]:
                start = datetime.fromtimestamp(int(values[0]), timezone.utc)
                end = start + timedelta(days=1)
                if end > e.stamp(now):
                    continue  # Kraken includes the current incomplete candle.
                bars.append(dict(symbol=symbol, start=start.isoformat(), end=end.isoformat(),
                    open=float(values[1]), high=float(values[2]), low=float(values[3]), close=float(values[4]),
                    source='kraken_public_exact_gbp_pair', quality='verified_unadjusted'))
        except Exception as exc:
            errors.append(dict(symbol=symbol, error_type=type(exc).__name__))
    with e.transaction(db) as conn:
        e.put_control(conn, 'kraken_shadow_bars', dict(day=now[:10], bars=bars, errors=errors,
            status='partial' if errors or len(symbols) > 2 else 'completed', requested=chosen))
    return bars
