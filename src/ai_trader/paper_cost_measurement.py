"""Aggregate paper estimates without broker calls or canonical fee backfills."""
from datetime import datetime, timedelta, timezone
from .database import row_values

MODEL = 'alpaca-regulatory-estimate-2026-04-v1'


def estimate_query():
    def cents(value):
        return f'(CAST({value} AS BIGINT) + CASE WHEN {value} - CAST({value} AS BIGINT) > 1e-12 THEN 1 ELSE 0 END) / 100.0'
    return f"""WITH inputs AS (
      SELECT gross_pnl,net_pnl,closed_at,exit_filled_quantity,
        CASE WHEN side='buy' THEN average_exit_price*exit_filled_quantity
             WHEN side='sell' THEN average_entry_price*exit_filled_quantity END AS sell_notional,
        CASE WHEN EXISTS (SELECT 1 FROM CLOSED_LOOP_LEARNING_RUNS l
          WHERE l.logical_trade_id=t.logical_trade_id AND l.status='completed'
            AND l.experience_id IS NOT NULL AND l.review_id IS NOT NULL)
          THEN 1 ELSE 0 END AS reviewed
      FROM LOGICAL_TRADES t WHERE broker='alpaca' AND terminal=1
    ), costs AS (
      SELECT *, CASE WHEN net_pnl IS NULL AND gross_pnl BETWEEN -1e12 AND 1e12
        AND sell_notional > 0 AND sell_notional < 1e12
        AND exit_filled_quantity > 0 AND exit_filled_quantity < 1e12
        THEN {cents('sell_notional * 0.002060')} + CASE WHEN exit_filled_quantity * 0.0195>=979
          THEN 9.79 ELSE {cents('exit_filled_quantity * 0.0195')} END
        END AS estimated_cost FROM inputs
    ), windows AS (
      SELECT 'all_recorded' AS period, * FROM costs
      UNION ALL SELECT 'last_7_days' AS period, * FROM costs WHERE closed_at>=? AND closed_at<=?
      UNION ALL SELECT 'selected_period' AS period, * FROM costs WHERE closed_at>=? AND closed_at<=?
    ) SELECT period,COUNT(*) AS closed,COUNT(net_pnl) AS verified_net_count,
      SUM(net_pnl) AS verified_net_sum,COUNT(gross_pnl) AS gross_known,
      SUM(gross_pnl) AS gross_all_known,SUM(reviewed) AS reviewed,
      COUNT(estimated_cost) AS estimated_count,
      SUM(CASE WHEN estimated_cost IS NOT NULL THEN gross_pnl END) AS estimated_gross,
      SUM(estimated_cost) AS estimated_cost,
      SUM(CASE WHEN estimated_cost IS NOT NULL THEN gross_pnl-estimated_cost END) AS estimated_net,
      SUM(CASE WHEN estimated_cost IS NOT NULL AND gross_pnl-estimated_cost>0 THEN 1 ELSE 0 END) AS wins,
      SUM(CASE WHEN estimated_cost IS NOT NULL AND gross_pnl-estimated_cost<0 THEN 1 ELSE 0 END) AS losses,
      MIN(closed_at) AS first_close,MAX(closed_at) AS last_close
    FROM windows GROUP BY period"""


def measure(conn, now=None, *, since=None, placeholder='?'):
    now = now or datetime.now(timezone.utc)
    if placeholder not in ('?', '%s'):
        raise ValueError('Unsupported SQL placeholder')
    if since is not None:
        since = datetime.fromisoformat(since.replace('Z', '+00:00'))
        if since.tzinfo is None or since > now:
            raise ValueError('Period start must be timezone-aware and no later than report time')
        since = since.astimezone(timezone.utc).isoformat()
    rows = conn.execute(estimate_query().replace('?', placeholder),
        ((now-timedelta(days=7)).isoformat(), now.isoformat(), since, now.isoformat())).fetchall()
    columns = ('period','closed','verified_net_count','verified_net_sum','gross_known',
        'gross_all_known','reviewed','estimated_count','estimated_gross','estimated_cost',
        'estimated_net','wins','losses','first_close','last_close')
    periods = {}
    for row in rows:
        item = dict(zip(columns, row_values(row)))
        for key in ('verified_net_sum','gross_all_known','estimated_gross','estimated_cost','estimated_net'):
            item[key] = round(float(item[key]), 6) if item[key] is not None else None
        item['unmeasured_count'] = item['closed']-item['verified_net_count']-item['estimated_count']
        item['status'] = 'partial' if item['unmeasured_count'] else 'covered_actual_or_estimated'
        periods[item.pop('period')] = item
    empty = dict(closed=0,verified_net_count=0,verified_net_sum=None,gross_known=0,
        gross_all_known=None,reviewed=0,estimated_count=0,estimated_gross=None,
        estimated_cost=None,estimated_net=None,wins=0,losses=0,first_close=None,
        last_close=None,unmeasured_count=0,status='no_closed_outcomes')
    for key in ('all_recorded','last_7_days'):
        periods.setdefault(key, dict(empty))
    if since is not None:
        periods.setdefault('selected_period', dict(empty))
        periods['selected_period'].update(since=since,until=now.isoformat())
    a = periods['all_recorded']
    return dict(status='estimated_not_broker_attributed' if a['estimated_count'] else
        'inputs_incomplete' if a['unmeasured_count'] else 'no_missing_net_estimates',
        individual_results_estimated=a['estimated_count'],wins=a['wins'],losses=a['losses'],
        gross_pnl=a['estimated_gross'],estimated_regulatory_costs=a['estimated_cost'],
        estimated_net_pnl=a['estimated_net'],currency='USD',actual_costs_known=False,
        model_version=MODEL,periods=periods,generated_at=now.isoformat(),
        cost_basis='Frozen regulatory estimate, rounded once per canonical round trip; not actual fill fees',
        excludes=['account FEE allocation','additional spread/slippage stress','per-fill rounding differences'],
        learning_use='Provisional closed-trade comparison independent of reviews; not total portfolio or verified actual profit',
        acceptance='Estimates never satisfy actual-cost verification or alter frozen experiment acceptance')
