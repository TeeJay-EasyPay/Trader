"""One bounded model call can supply several independently validated hypotheses."""
import json
from datetime import timedelta
from . import experiments as e
from .database import uses_postgres


def propose_batch(db, settings, now, policy, answer=None):
    if not policy.get('model_enabled'):
        return 'model_disabled'
    with e.transaction(db) as conn:
        if uses_postgres():
            conn.execute('SELECT pg_advisory_xact_lock(71911501)')
        attempt = e.control(conn, 'proposal_attempt', {})
        budget_used = attempt.get('day') == now[:10]
        specs = [json.loads(r[0]) for r in conn.execute("SELECT spec_json FROM RULE_EXPERIMENTS WHERE status IN ('queued','shadow_running') LIMIT 24").fetchall()]
        history=[]
        for r in conn.execute('SELECT status,spec_json,report_json FROM RULE_EXPERIMENTS ORDER BY created_at DESC LIMIT 24').fetchall():
            spec,report=json.loads(r[1]),json.loads(r[2])
            history.append(dict(broker=spec['broker'],rule_type=spec['rule_type'],threshold=spec['threshold'],
                hypothesis=spec['hypothesis'][:250],evidence_ids=spec['evidence_ids'],status=r[0],
                usable=report.get('usable'),mean_difference=report.get('paired_mean_usd'),verdict=report.get('verdict')))
        evidence, eligibility = {}, {}
        for broker in ('alpaca', 'kraken'):
            slots = max(0, 5 - sum(s['broker'] == broker for s in specs))
            rows = conn.execute('SELECT DISTINCT p.attribution_id,p.symbol,p.closed_at,p.profit_loss,p.holding_period_seconds,'
                't.intended_entry_price,t.original_stop,t.intended_target FROM PERFORMANCE_ATTRIBUTION p '
                'JOIN LOGICAL_TRADES t ON t.proposal_id=p.proposal_id AND t.broker=p.broker '
                'WHERE p.broker=? AND p.exit_price IS NOT NULL ORDER BY p.attribution_id DESC LIMIT 30', (broker,)).fetchall()
            records = [dict(r) for r in rows]
            watermark = e.control(conn, 'proposal_watermark:' + broker)
            if watermark is None:
                # Early releases recorded source IDs but no watermark. Do not
                # count those already-used outcomes as new after this upgrade.
                watermark=max((i for h in history if h['broker']==broker for i in h['evidence_ids']),default=0)
            new = len({r['attribution_id'] for r in records if r['attribution_id'] > watermark})
            reason = 'eligible' if slots and new >= policy['min_new_outcomes'] else 'slots_full' if not slots else 'insufficient_new_linked_outcomes'
            eligibility[broker] = dict(slots=slots, new_outcomes=new, reason=reason)
            if reason == 'eligible':
                evidence[broker] = records
        e.put_control(conn, 'proposal_eligibility', dict(at=now, brokers=eligibility))
        if budget_used:
            return 'daily_model_budget_reached'
        if not evidence:
            return 'no_eligible_broker'
        context = dict(brokers=evidence, capacity=eligibility,
            previous_experiments=history,
            existing=[{k:s.get(k) for k in ('broker','rule_type','threshold','hypothesis')} for s in specs])
        from .reference_sets import snapshot
        try:
            context['methodology'] = snapshot('stock',candidate=True,topics=['experiment_design'])
        except ValueError:
            e.put_control(conn,'proposal_eligibility',dict(at=now,brokers=eligibility,reason='reference_refresh_required'))
            return 'reference_refresh_required'
        # Remove oldest records evenly until the compact context fits. Retain
        # the minimum evidence gate for each included broker.
        while len(e.dump(context)) > 22000:
            largest=max(evidence,key=lambda b:len(evidence[b]))
            if len(evidence[largest])<=policy['min_new_outcomes']:
                return 'input_budget_exceeded'
            evidence[largest].pop()
        next_at = (e.stamp(now).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
        e.put_control(conn, 'proposal_attempt', dict(day=now[:10], status='reserved', next_eligible_at=next_at, max_output_tokens=2500))
    result = dict(status='batch_completed', accepted=[], rejected=[], next_eligible_at=next_at,
        reference_provenance=context['methodology'])
    try:
        from .experiment_worker import QUESTION
        if answer is None:
            from .ai import OpenAIReadOnlyExplainer
            answer = OpenAIReadOnlyExplainer(settings.openai_api_key, settings.openai_model,
                timeout_seconds=20, max_output_tokens=2500).answer
        question = QUESTION.replace('Propose at most one falsifiable shadow experiment for the supplied broker',
            'Propose a batch of distinct falsifiable shadow experiments for the supplied brokers')
        question += '\nBatch response overrides the single-object format: return {"proposals":[objects including broker],"no_change":"optional explanation"}. Respect capacity per broker. Do not fill slots with near-duplicate thresholds. Include risks and evaluation criteria in each hypothesis explanation. Reference no outcome outside that broker supplied evidence.'
        question += '\nAlso supported: minimum_target_move_bps, threshold 1..5000, filters planned percentage target distance in basis points rather than target/risk ratio. This is NOT expected return. Do not propose reference_set_filter automatically: separate paired inference budget is required.'
        question += '\nUse prior results including failures; do not recycle rejected hypotheses without identifying new supporting evidence.'
        raw = answer(question, context).strip()
        if len(raw) > 20000:
            raise ValueError('output_budget')
        if raw.startswith('```'):
            raw = raw.split('\n',1)[1].rsplit('```',1)[0]
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not ('proposals' in payload or 'no_change' in payload):
            raise ValueError('invalid_response_schema')
        candidates = payload.get('proposals', [])
        if not isinstance(candidates, list) or len(candidates) > 10:
            raise ValueError('invalid_batch')
        accepted_specs = list(specs)
        for candidate in candidates:
            try:
                broker = candidate.get('broker')
                if broker not in evidence:
                    raise ValueError('broker_not_eligible')
                ids = candidate.get('evidence_ids', [])
                if not ids or not set(ids).issubset({r['attribution_id'] for r in evidence[broker]}):
                    raise ValueError('unsupported_evidence')
                if sum(s['broker'] == broker for s in accepted_specs) >= 5:
                    raise ValueError('broker_capacity')
                validated = e.validate_spec(candidate)
                if any(s['broker'] == broker and s['rule_type'] == validated['rule_type'] and
                       abs(s['threshold'] - validated['threshold']) < (25 if validated['rule_type']=='minimum_target_move_bps' else .25) for s in accepted_specs):
                    raise ValueError('near_duplicate')
                row = e.create_experiment(db, candidate, now=now, queue=True)
                result['accepted'].append(row['id'])
                accepted_specs.append(validated)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                result['rejected'].append(dict(reason=str(exc)[:200], broker=candidate.get('broker') if isinstance(candidate,dict) else None))
        if not candidates:
            result.update(status='no_justified_change', reason=str(payload.get('no_change','No proposal supplied'))[:500])
        with e.transaction(db) as conn:
            for broker, records in evidence.items():
                e.put_control(conn, 'proposal_watermark:' + broker, max(r['attribution_id'] for r in records))
    except Exception as exc:
        result.update(status='proposal_failed', error_type=type(exc).__name__, reason='No automatic retry; daily budget remains reserved.')
    result['usage'] = getattr(getattr(answer, '__self__', None), 'last_usage', None)
    with e.transaction(db) as conn:
        e.put_control(conn, 'proposal_attempt', dict(day=now[:10], **result))
    return result
