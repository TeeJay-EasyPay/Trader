"""Small, read-only period evidence shared by the UI and Trader.

No dossiers or raw fills leave the database. Recorded stops/reasons are evidence,
not proof that an order was active at the broker or that an exit label is verified.
"""
from contextlib import closing
from datetime import datetime, timezone
import sqlite3

from .database import connect, uses_postgres


def _epoch(column):
    if uses_postgres():
        return f"""CASE WHEN {column} ~ '^[0-9]+([.][0-9]+)?$'
          THEN CAST({column} AS DOUBLE PRECISION)
          WHEN pg_input_is_valid({column}, 'timestamp with time zone')
          THEN EXTRACT(EPOCH FROM CAST({column} AS TIMESTAMPTZ)) END"""
    return f"(julianday({column}, 'auto') - 2440587.5) * 86400.0"


def completed_trade_evidence(db, *, now_epoch=None):
    now = datetime.now(timezone.utc).timestamp() if now_epoch is None else float(now_epoch)
    result = {'generated_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
              'windows': 'rolling 24 hours, 7 days, 30 days', 'brokers': {}}
    for broker, currency in (('kraken', 'GBP'), ('alpaca', 'USD')):
        if broker == 'kraken':
            source = f"""SELECT {_epoch('exit_time')} AS closed_epoch,
              net_pnl AS pnl, gross_pnl AS gross,
              exchange_fee + broker_fee AS fees,
              COALESCE(holding_seconds, {_epoch('exit_time')}-{_epoch('entry_time')}) AS holding,
              proposal_id, original_stop AS stop
              FROM KRAKEN_RECONCILED_RESULTS WHERE status='closed'"""
        else:
            source = f"""SELECT {_epoch('closed_at')} AS closed_epoch,
              profit_loss AS pnl, profit_loss AS gross, CAST(NULL AS DOUBLE PRECISION) AS fees,
              COALESCE(holding_period_seconds, {_epoch('closed_at')}-{_epoch('opened_at')}) AS holding,
              proposal_id, CAST(NULL AS DOUBLE PRECISION) AS stop
              FROM PERFORMANCE_ATTRIBUTION WHERE broker='alpaca'
              AND exit_price IS NOT NULL"""
        item = {'currency': currency,
                'pnl_basis': 'net_after_recorded_fees' if broker == 'kraken' else 'before_unreconciled_fees',
                'periods': {}}
        for name, days in (('day', 1), ('week', 7), ('month', 30)):
            try:
                with closing(connect(db)) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(f"""WITH outcomes AS ({source})
                      SELECT COUNT(*) AS total,
                      SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) AS successful,
                      SUM(CASE WHEN pnl<0 THEN 1 ELSE 0 END) AS unsuccessful,
                      SUM(CASE WHEN pnl=0 THEN 1 ELSE 0 END) AS breakeven,
                      COUNT(pnl) AS pnl_known, SUM(pnl) AS recorded_pnl,
                      COUNT(gross) AS gross_known, SUM(gross) AS gross_pnl,
                      COUNT(fees) AS fees_known, SUM(fees) AS recorded_fees,
                      SUM(CASE WHEN gross IS NOT NULL AND fees IS NOT NULL AND pnl IS NOT NULL
                        AND ABS(gross-fees-pnl)>0.01 THEN 1 ELSE 0 END) AS accounting_mismatches,
                      COUNT(CASE WHEN holding>=0 THEN 1 END) AS holding_known,
                      AVG(CASE WHEN holding>=0 THEN holding END) AS average_holding_seconds,
                      SUM(CASE WHEN proposal_id IS NULL OR proposal_id='' THEN 1 ELSE 0 END) AS missing_proposal_links,
                      COUNT(stop) AS recorded_stop_count
                      FROM outcomes WHERE closed_epoch>=? AND closed_epoch<=?""",
                      (now-days*86400, now)).fetchone()
                    bucket = dict(row)
                    for field in ('successful', 'unsuccessful', 'breakeven', 'accounting_mismatches', 'missing_proposal_links'):
                        bucket[field] = bucket[field] or 0
                    total = bucket['total']
                    bucket['unknown'] = total-bucket['pnl_known']
                    bucket['win_rate'] = bucket['successful']/bucket['pnl_known'] if bucket['pnl_known'] else None
                    # Partial sums must not masquerade as complete period totals.
                    for field, coverage in (('gross_pnl', 'gross_known'), ('recorded_fees', 'fees_known'), ('recorded_pnl', 'pnl_known')):
                        if not total or bucket[coverage] != total:
                            bucket[field] = None
                    bucket['net_pnl'] = bucket['recorded_pnl'] if broker == 'kraken' else None
                    bucket['available'] = True
                    item['periods'][name] = bucket
            except Exception:
                item['periods'][name] = {'available': False, 'reason': 'Completed-trade evidence unavailable; not zero trades.'}
        try:
            with closing(connect(db)) as conn:
                conn.row_factory = sqlite3.Row
                # Attribution is a separate source, not a guessed join to settlement rows.
                rows = conn.execute(f"""SELECT COALESCE(NULLIF(exit_reason,''),'unknown') AS reason,
                    COUNT(*) AS records FROM PERFORMANCE_ATTRIBUTION
                    WHERE broker=? AND {_epoch('closed_at')}>=? AND {_epoch('closed_at')}<=?
                    GROUP BY COALESCE(NULLIF(exit_reason,''),'unknown')
                    ORDER BY records DESC LIMIT 12""", (broker, now-30*86400, now)).fetchall()
                item['recorded_exit_reasons_30d'] = [dict(row) for row in rows]
                item['exit_reason_basis'] = 'Attribution labels, not independently verified execution triggers; top 12 groups.'
        except Exception:
            item['recorded_exit_reasons_30d'] = None
        result['brokers'][broker] = item
    result['limitations'] = [
        'Alpaca results are before unreconciled fees; never add USD to GBP.',
        'Recorded holding times and stops do not prove a five-percent policy was applied or a broker stop was active.',
        'Proposal linkage gaps must not be repaired by guessing. Counts describe source records, not verified unique round trips.',
    ]
    return result
