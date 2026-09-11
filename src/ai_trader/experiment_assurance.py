"""Bounded evidence comparisons and adoption monitoring. No broker clients.

This measures simulator disagreement; it never converts estimated fees into facts.
Paper-broker agreement is not a validation of live execution.
"""
import json
import os
from datetime import timedelta
from . import experiments as e
from .database import uses_postgres


def json_field(column, path, *, text=True):
    if uses_postgres():
        return column + ('::jsonb #>> ' if text else '::jsonb #> ') + "'{" + ','.join(path) + "}'"
    return "json_extract(" + column + ", '$." + '.'.join(path) + "')"


def compare(ops, actual, *, tolerances=None):
    limits = tolerances or dict(entry_bps=50, exit_bps=50, holding_hours=24, cost_bps=25, minimum_pairs=20)
    pairs, missing, ambiguous = [], 0, 0
    for op in ops:
        sim = op['arms']['baseline']
        if sim['status'] != 'closed' or op.get('uncertain'):
            continue
        matches = actual.get(str(op['source_id']), [])
        if len(matches) != 1:
            missing += not matches
            ambiguous += len(matches) > 1
            continue
        a = matches[0]
        try:
            quantity = e.number(a['quantity'], .00000001, 1e12)
            entry = e.number(a['entry_price'], .00000001, 1e9)
            exit_price = e.number(a['exit_price'], .00000001, 1e9)
            holding = (e.stamp(a['closed_at']) - e.stamp(a['opened_at'])).total_seconds() / 3600
            simulated_holding = (e.stamp(sim['exited_at']) - e.stamp(sim['entered_at'])).total_seconds() / 3600
            # Fees must be explicitly reconciled, never canonical defaults of zero.
            fees = a.get('fees') if a.get('fees_status') == 'reconciled' else None
            cost_error = abs(sim['cost'] / (sim['quantity'] * sim['entry']) - float(fees) / (quantity * entry)) * 10000 if fees is not None else None
            differences = dict(entry_bps=abs(sim['entry'] / entry - 1) * 10000,
                exit_bps=abs(sim['exit'] / exit_price - 1) * 10000,
                holding_hours=abs(simulated_holding - holding), cost_bps=cost_error)
            passed = all(v is not None and v <= limits[k] for k, v in differences.items())
            pairs.append(dict(source_id=op['source_id'], attribution_id=a['attribution_id'],
                              differences=differences, within_tolerance=passed))
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            missing += 1
    passed = sum(p['within_tolerance'] for p in pairs)
    enough = len(pairs) >= limits['minimum_pairs']
    status = 'within_tolerance' if enough and passed / len(pairs) >= .9 and not missing and not ambiguous else 'divergent' if enough else 'insufficient_evidence'
    return dict(status=status, compared=len(pairs), within_tolerance=passed,
        missing_matches=missing, ambiguous_matches=ambiguous,
        missing_costs=sum(p['differences']['cost_bps'] is None for p in pairs),
        tolerances=limits, examples=pairs[-10:],
        scope='Matched baseline versus recorded broker outcomes; paper agreement is not live validation.')


def actual_outcomes(conn, broker, source_ids):
    """Exact proposal linkage only. Multiple closures are ambiguous, not guessed."""
    source_ids = sorted(set(str(x) for x in source_ids))[:200]
    if not source_ids:
        return {}
    fees = json_field('p.primary_factors_json', ['reconciled_fees'])
    fees_status = json_field('p.primary_factors_json', ['fees_status'])
    rows = conn.execute('SELECT p.attribution_id,p.proposal_id,p.quantity,p.entry_price,p.exit_price,p.opened_at,p.closed_at,'
        f'{fees} AS fees,{fees_status} AS fees_status,t.net_pnl,t.gross_pnl,t.terminal,t.entry_filled_quantity FROM PERFORMANCE_ATTRIBUTION p '
        'LEFT JOIN LOGICAL_TRADES t ON t.proposal_id=p.proposal_id AND t.broker=p.broker '
        'WHERE p.broker=? AND p.exit_price IS NOT NULL AND p.proposal_id IN (' + ','.join('?' for _ in source_ids) + ') ORDER BY p.attribution_id LIMIT 400',
        [broker, *source_ids]).fetchall()
    result = {}
    for r in rows:
        a = dict(r)
        if (a['terminal'] and a['net_pnl'] is not None and a['gross_pnl'] is not None
                and a['entry_filled_quantity'] is not None and a['quantity'] is not None
                and abs(float(a['entry_filled_quantity']) - float(a['quantity'])) < 1e-8):
            a['fees'] = float(a['gross_pnl']) - float(a['net_pnl'])
            a['fees_status'] = 'reconciled'
        result.setdefault(str(a['proposal_id']), []).append(a)
    return result


def evidence_coverage(db, now):
    with e.transaction(db) as conn:
        prior = e.control(conn, 'learning_evidence_coverage', {})
        if prior.get('checked_at', '')[:10] == now[:10]:
            return prior
        fees = json_field('p.primary_factors_json', ['fees_status'])
        rows = conn.execute('SELECT p.broker,COUNT(*) AS outcomes,'
            'SUM(CASE WHEN t.proposal_id IS NOT NULL THEN 1 ELSE 0 END) AS linked_decisions,'
            'SUM(CASE WHEN t.terminal=1 THEN 1 ELSE 0 END) AS canonical_closures,'
            f"SUM(CASE WHEN {fees}='reconciled' OR (t.net_pnl IS NOT NULL AND t.terminal=1 AND ABS(t.entry_filled_quantity-p.quantity)<0.00000001) THEN 1 ELSE 0 END) AS known_costs,"
            "SUM(CASE WHEN p.exit_reason IS NOT NULL AND p.exit_reason<>'' AND LOWER(p.exit_reason) NOT LIKE ? THEN 1 ELSE 0 END) AS meaningful_exit_labels "
            'FROM PERFORMANCE_ATTRIBUTION p LEFT JOIN LOGICAL_TRADES t ON t.proposal_id=p.proposal_id AND t.broker=p.broker '
            'WHERE p.exit_price IS NOT NULL GROUP BY p.broker', ('%not recorded%',)).fetchall()
        result = dict(checked_at=now, brokers=[dict(r) for r in rows],
            caveat='Exit labels are not proof of stop activation. Unrecoverable historical fees and identities remain unknown.')
        e.put_control(conn, 'learning_evidence_coverage', result)
        return result


def validate_execution(db, row, ops, now):
    with e.transaction(db) as conn:
        actual = actual_outcomes(conn, row['spec']['broker'], [o['source_id'] for o in ops])
        result = compare(ops, actual, tolerances=row['spec'].get('execution_tolerances'))
        result['checked_at'] = now
        current = e._load(conn, row['id'])
        current['state']['execution_validation'] = result
        e._save(conn, current)
    return result


def monitor_adoptions(db, now):
    """One daily compact review. Suspension blocks new variant entries, never exits."""
    with e.transaction(db) as conn:
        if uses_postgres():
            conn.execute('SELECT pg_advisory_xact_lock(71911503)')
        if e.control(conn, 'adoption_monitor_day', '') == now[:10]:
            return
        active = conn.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status='paper_active' LIMIT 2").fetchall()
        for r in active:
            row = e._load(conn, r[0])
            activation = row['state']['activation']
            version = json_field('payload_json', ['proposal', 'experiment_entry_check', 'version'])
            allowed = json_field('payload_json', ['proposal', 'experiment_entry_check', 'allowed'])
            decisions = conn.execute(f'SELECT proposal_id,{allowed} AS allowed FROM DECISION_JOURNAL '
                f"WHERE broker='alpaca' AND created_at>=? AND {version}=? ORDER BY decision_id DESC LIMIT 200",
                (activation.get('activated_at', row['created_at']), row['version'])).fetchall()
            accepted = [r['proposal_id'] for r in decisions if str(r['allowed']).lower() in ('true', '1')]
            actual = actual_outcomes(conn, 'alpaca', accepted)
            outcomes = [a for group in actual.values() for a in group]
            known = [a for a in outcomes if a['fees_status'] == 'reconciled' and a['fees'] is not None]
            net = sum((float(a['exit_price']) - float(a['entry_price'])) * float(a['quantity']) - float(a['fees']) for a in known)
            reason = None
            if e.stamp(now) >= e.stamp(activation['expires_at']):
                reason = 'Approval expired'
            elif activation.get('version') != row['version'] or row['spec']['baseline_fingerprint'] != e.baseline_fingerprint():
                reason = 'Approved version or execution baseline changed'
            elif net <= -activation.get('max_loss_usd', activation['max_notional_usd'] * .05):
                reason = 'Approved cumulative after-cost loss budget reached'
            elif outcomes and len(known) != len(outcomes):
                reason = 'Completed adoption outcomes lack reconciled costs'
            elif len(decisions) >= 200:
                reason = 'Bounded adoption review capacity reached; review before continuing'
            row['state']['adoption_monitor'] = dict(checked_at=now, decisions=len(decisions),
                accepted=len(accepted), completed=len(outcomes), verified_cost_outcomes=len(known),
                known_net_usd=net, status='suspended' if reason else 'monitoring', reason=reason,
                scope='Latest 200 decisions; accumulated loss is not a profitability claim')
            if reason:
                row['status'] = 'suspended'
                e._event(conn, row, 'automatic_suspension', {'reason': reason}, 'suspension:' + row['id'] + ':' + row['version'])
            e._save(conn, row)
        e.put_control(conn, 'adoption_monitor_day', now[:10])


def refresh_review_validation(db, now):
    """Late broker evidence can resolve an ended test's validation gap."""
    with e.transaction(db) as conn:
        if e.control(conn, 'review_validation_day', '') == now[:10]:
            return
        rows = conn.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status IN ('recommended','library_approved','ready_for_activation') ORDER BY created_at LIMIT 2").fetchall()
        e.put_control(conn, 'review_validation_day', now[:10])
    for record in rows:
        with e.transaction(db) as conn:
            row = e._load(conn, record[0])
            ops = [json.loads(r[0]) for r in conn.execute('SELECT payload_json FROM EXPERIMENT_OPPORTUNITIES WHERE experiment_id=? ORDER BY created_at LIMIT 1200', (row['id'],)).fetchall()]
        validate_execution(db, row, ops, now)


def start_queued(db, now):
    """Freeze a fresh prospective start only when a slot is available."""
    with e.transaction(db) as conn:
        if uses_postgres():
            conn.execute('SELECT pg_advisory_xact_lock(71911502)')
        policy = e.control(conn, 'policy', e.DEFAULT_POLICY)
        active = conn.execute("SELECT spec_json FROM RULE_EXPERIMENTS WHERE status='shadow_running'").fetchall()
        slots = min(10, policy['max_active']) - len(active)
        broker_counts = {b: sum(json.loads(r[0])['broker'] == b for r in active) for b in ('alpaca', 'kraken')}
        rows = [e._load(conn, r[0]) for r in conn.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status='queued' ORDER BY created_at LIMIT 24").fetchall()]
        for row in sorted(rows, key=lambda r: (r['spec'].get('priority', 3), r['created_at'])):
            if slots <= 0:
                break
            broker = row['spec']['broker']
            if broker_counts[broker] >= 5:
                continue
            queued_at = row['created_at']
            row['spec'].update(frozen_at=now, baseline_fingerprint=e.baseline_fingerprint(),
                               baseline_deployment=os.getenv('RENDER_GIT_COMMIT', 'unverified'))
            row['version'] = e.digest(row['spec'])
            row['state']['cursor'] = conn.execute('SELECT COALESCE(MAX(decision_id),0) FROM DECISION_JOURNAL').fetchone()[0]
            row['state']['queued_at'] = queued_at
            row['state']['started_at'] = now
            row['created_at'] = now
            row['status'] = 'shadow_running'
            conn.execute('UPDATE RULE_EXPERIMENTS SET created_at=?,version=?,spec_json=? WHERE id=?',
                         (now, row['version'], e.dump(row['spec']), row['id']))
            e._event(conn, row, 'shadow_started', {'queued_at': queued_at}, 'started:' + row['id'])
            e._save(conn, row)
            slots -= 1
            broker_counts[broker] += 1
