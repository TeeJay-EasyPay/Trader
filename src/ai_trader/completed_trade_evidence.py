"""Small, read-only period evidence shared by the UI and Trader.

No dossiers or raw fills leave the database. Recorded stops/reasons are evidence,
not proof that an order was active at the broker or that an exit label is verified.
"""
from contextlib import closing
from datetime import datetime, timezone
import sqlite3

from .database import connect, row_values, uses_postgres
from .alpaca_costs import alpaca_fee_periods


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
            # Alpaca's attribution table has no stop column. The previous census therefore
            # hard-coded NULL here and told Trader there were zero recorded stops, even when
            # the proposal-linked canonical trade retained the original stop. Use only the
            # retained identity; old outcomes with no canonical record remain unknown.
            source = f"""SELECT {_epoch('pa.closed_at')} AS closed_epoch,
              pa.profit_loss AS pnl, pa.profit_loss AS gross,
              CAST(NULL AS DOUBLE PRECISION) AS fees,
              COALESCE(pa.holding_period_seconds,
                {_epoch('pa.closed_at')}-{_epoch('pa.opened_at')}) AS holding,
              pa.proposal_id,
              (SELECT MAX(lt.original_stop) FROM LOGICAL_TRADES lt
               WHERE lt.broker='alpaca' AND lt.proposal_id=pa.proposal_id) AS stop
              FROM PERFORMANCE_ATTRIBUTION pa WHERE pa.broker='alpaca'
              AND pa.exit_price IS NOT NULL"""
        item = {'currency': currency,
                'pnl_basis': 'net_after_recorded_fees' if broker == 'kraken' else 'gross_trades_with_account_fees_reconciled_separately',
                'periods': {}}
        fee_periods = {}
        if broker == 'alpaca':
            try:
                fee_periods = alpaca_fee_periods(db, now_epoch=now)
            except Exception:
                fee_periods = {}
        try:
            # One aggregate read for all windows, not three separate remote
            # connections. LEFT JOIN retains an honest empty bucket for each period.
            with closing(connect(db)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(f"""WITH outcomes AS ({source}),
                      windows(period, start_epoch) AS (VALUES ('day', ?), ('week', ?), ('month', ?))
                      SELECT windows.period, COUNT(outcomes.closed_epoch) AS total,
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
                      SUM(CASE WHEN outcomes.closed_epoch IS NOT NULL AND (proposal_id IS NULL OR proposal_id='') THEN 1 ELSE 0 END) AS missing_proposal_links,
                      COUNT(stop) AS recorded_stop_count
                      FROM windows LEFT JOIN outcomes ON closed_epoch>=windows.start_epoch AND closed_epoch<=?
                      GROUP BY windows.period""",
                      (now-86400, now-7*86400, now-30*86400, now)).fetchall()
                for row in rows:
                    bucket = dict(row)
                    name = bucket.pop('period')
                    for field in ('successful', 'unsuccessful', 'breakeven', 'accounting_mismatches', 'missing_proposal_links'):
                        bucket[field] = bucket[field] or 0
                    total = bucket['total']
                    bucket['unknown'] = total-bucket['pnl_known']
                    bucket['win_rate'] = bucket['successful']/bucket['pnl_known'] if bucket['pnl_known'] else None
                    # Partial sums must not masquerade as complete period totals.
                    for field, coverage in (('gross_pnl', 'gross_known'), ('recorded_fees', 'fees_known'), ('recorded_pnl', 'pnl_known')):
                        if not total or bucket[coverage] != total:
                            bucket[field] = None
                    if broker == 'kraken':
                        bucket['net_pnl'] = bucket['recorded_pnl']
                    else:
                        fee = fee_periods.get(name)
                        bucket['recorded_account_fees'] = fee.get('recorded_account_fees') if fee else None
                        bucket['account_fee_source'] = fee.get('source') if fee else None
                        bucket['net_pnl'] = (
                            round(float(bucket['gross_pnl']) - float(bucket['recorded_account_fees']), 6)
                            if bucket['gross_pnl'] is not None and bucket['recorded_account_fees'] is not None
                            else None
                        )
                    bucket['available'] = True
                    item['periods'][name] = bucket
        except Exception:
            for name in ('day', 'week', 'month'):
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

                if broker == 'alpaca':
                    # Reconciliation retains the closing fill's order id and recorded order
                    # type. This verifies the exit type, not uninterrupted protection from
                    # entry until exit.
                    order_type = (
                        "primary_factors_json::jsonb #>> '{exit_evidence,order_type}'"
                        if uses_postgres()
                        else "json_extract(primary_factors_json, '$.exit_evidence.order_type')"
                    )
                    protection = conn.execute(f"""SELECT COUNT(*) AS outcomes,
                        SUM(CASE WHEN {order_type} IS NOT NULL THEN 1 ELSE 0 END) AS verified_exit_order_types,
                        SUM(CASE WHEN {order_type} IN ('stop','stop_limit','trailing_stop')
                            THEN 1 ELSE 0 END) AS verified_stop_fills,
                        SUM(CASE WHEN EXISTS (
                            SELECT 1 FROM LOGICAL_TRADES lt
                            WHERE lt.broker='alpaca' AND lt.proposal_id=pa.proposal_id
                              AND lt.original_stop IS NOT NULL
                        ) THEN 1 ELSE 0 END) AS outcomes_linked_to_planned_stop
                        FROM PERFORMANCE_ATTRIBUTION pa
                        WHERE pa.broker='alpaca' AND {_epoch('pa.closed_at')}>=?
                          AND {_epoch('pa.closed_at')}<=?""",
                        (now-30*86400, now)).fetchone()
                    values = row_values(protection) if protection else (0, 0, 0, 0)
                    item['protection_evidence_30d'] = {
                        'outcomes': values[0] or 0,
                        'verified_exit_order_types': values[1] or 0,
                        'verified_stop_fills': values[2] or 0,
                        'outcomes_linked_to_planned_stop': values[3] or 0,
                        'basis': ('Closing fill matched to a recorded broker order type; planned stop '
                                  'linked through proposal identity. This does not prove continuous '
                                  'broker protection between entry and exit.'),
                    }
        except Exception:
            item['recorded_exit_reasons_30d'] = None
            if broker == 'alpaca':
                item['protection_evidence_30d'] = {
                    'available': False,
                    'reason': 'Alpaca protection evidence unavailable; not zero protection.',
                }
        result['brokers'][broker] = item
    result['limitations'] = [
        'Alpaca account FEE ledger charges are deducted at period level and are not guessed onto individual trades; never add USD to GBP.',
        'Continuous protection is evidenced only for AI-managed positions whose broker order identity can be correlated.',
        'Proposal linkage gaps must not be repaired by guessing. Counts describe source records, not verified unique round trips.',
    ]
    return result
