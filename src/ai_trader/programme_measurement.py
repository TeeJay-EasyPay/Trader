"""Compare cached programme snapshots without network calls or profit inference."""
from decimal import Decimal, InvalidOperation


def difference(current, previous):
    if current is None or previous is None:
        return None
    try:
        a, b = Decimal(str(current)), Decimal(str(previous))
        return float(a - b) if a.is_finite() and b.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def compare(current, previous):
    old = {r['id']: r for r in previous.get('experiments', [])}
    pairs = []
    for row in current.get('experiments', []):
        prior = old.get(row['id'])
        if not prior:
            continue
        compatible = all(row.get(k) == prior.get(k) and row.get(k) is not None
                         for k in ('version', 'broker', 'currency'))
        item = dict(id=row['id'], broker=row.get('broker'), currency=row.get('currency'),
                    status='stored_marks_only' if compatible else 'incomparable_version_or_scope')
        if compatible:
            baseline = difference(row.get('baseline_equity'), prior.get('baseline_equity'))
            candidate = difference(row.get('candidate_equity'), prior.get('candidate_equity'))
            item.update(baseline_equity_change=baseline, candidate_equity_change=candidate,
                        relative_change=difference(candidate, baseline),
                        new_informative=difference(row.get('informative', row.get('informative_completed')),
                                                  prior.get('informative', prior.get('informative_completed'))))
            if item['new_informative'] is not None and item['new_informative'] < 0:
                item['status'] = 'counter_regression_requires_investigation'
        pairs.append(item)
    accounts = []
    by_broker = {r['broker']: r for r in previous.get('accounts', [])}
    for row in current.get('accounts', []):
        prior = by_broker.get(row['broker'])
        compatible = prior and all(row.get(k) == prior.get(k) and row.get(k) is not None
                                   for k in ('account_mode', 'currency'))
        accounts.append(dict(broker=row['broker'], currency=row.get('currency'),
            observed_equity_change=difference(row.get('portfolio_value'), prior.get('portfolio_value')) if compatible else None,
            verified_strategy_net_profit=None,
            status='cash_flows_costs_and_strategy_attribution_not_verified'))
    return dict(at=current.get('at'), since=previous.get('at'), experiments=pairs,
                accounts=accounts, profitability='not_established',
                caveat='Stored marks are not verified current valuations. Do not sum overlapping experiments or currencies.')
