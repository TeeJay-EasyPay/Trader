"""Read-only conversation projections; never run learning maintenance from chat."""
from contextlib import closing
from datetime import datetime, timedelta, timezone

from .database import connect


def daily_summary(db, day=None):
    day = day or datetime.now(timezone.utc).date().isoformat()
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    with closing(connect(db)) as conn:
        rows = conn.execute("""SELECT broker,COUNT(*) AS outcomes,
            SUM(profit_loss) AS recorded_pnl,
            SUM(CASE WHEN profit_loss>0 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN profit_loss<0 THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN profit_loss IS NULL THEN 1 ELSE 0 END) AS unknown
            FROM PERFORMANCE_ATTRIBUTION WHERE created_at>=? AND created_at<?
            GROUP BY broker ORDER BY broker""", (start.isoformat(), (start+timedelta(days=1)).isoformat())).fetchall()
    results = []
    for row in rows:
        broker, outcomes, pnl, wins, losses, unknown = (
            (row[k] for k in ('broker','outcomes','recorded_pnl','wins','losses','unknown'))
            if hasattr(row, 'keys') else row)
        results.append(dict(broker=broker, currency={'kraken':'GBP','alpaca':'USD'}.get(broker),
            cost_basis={'kraken':'recorded_net','alpaca':'gross_before_unverified_costs'}.get(broker,'unknown'),
            recorded_outcomes=outcomes, recorded_pnl=pnl, wins=wins, losses=losses, unknown=unknown))
    return dict(date=day, read_only=True, by_broker=results, total_profit_loss=None,
                period_basis='UTC attribution recording date, not necessarily trade closing date',
                note='Broker currencies and gross/net bases are not pooled. Reviews may exist while verified net outcomes are missing. Maintenance runs separately.')
