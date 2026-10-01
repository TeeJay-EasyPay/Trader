"""Read-only operational evidence, distinct from profitable learning."""
from datetime import timedelta
import json
from . import experiments as e
from .experiment_assurance import json_field


def snapshot(db, now=None):
    now = now or e.now_iso()
    result = {'at': now, 'strategy_improvement': 'not_established', 'issues': []}
    try:
        with e.transaction(db) as c:
            screening = e.control(c, 'historical_screening_view', {})
            trials = screening.get('trials', [])
            invalid = sum(t.get('status') == 'invalid' for t in trials)
            status = screening.get('status', 'unavailable')
            if trials and invalid == len(trials):
                status = 'failed'
            result['historical'] = {'at': screening.get('at'), 'status': status,
                'trials': len(trials), 'invalid': invalid,
                'evaluated': sum(t.get('status') in ('promising','not_supported') for t in trials),
                'reasons': sorted({t.get('reason', '') for t in trials if t.get('status') == 'invalid'})[:3]}
            if status in ('failed','partial','unavailable','reserved'):
                result['issues'].append('historical_screening_' + status)
            result['historical']['cache'] = screening.get('cache', {})
            if screening.get('cache', {}).get('status') == 'attention_required':
                result['issues'].append('research_cache_nearing_capacity')
            if not screening.get('at') or e.stamp(now)-e.stamp(screening['at']) > timedelta(hours=36):
                result['issues'].append('historical_screening_stale')
            if trials and all(t.get('status') in ('data_required','unsupported') for t in trials):
                result['issues'].append('historical_evidence_insufficient')
            score = e.control(c, 'founder_learning_scorecard', {})
            if score.get('trading_better'):
                result['strategy_improvement'] = 'supported_comparison_recorded_not_live_profitability'
            tick = e.control(c, 'last_tick', {})
            result['forward_worker'] = {k:tick.get(k) for k in ('at','status','processed','invalid')}
            if not tick.get('at') or e.stamp(now)-e.stamp(tick['at']) > timedelta(hours=1):
                result['issues'].append('forward_worker_stale')
            elif tick.get('status') != 'completed':
                result['issues'].append('forward_worker_' + str(tick.get('status')))
            attempt = e.control(c, 'proposal_attempt', {})
            result['model_review'] = {k:attempt.get(k) for k in ('day','status','failure')}
            if str(attempt.get('status','')).endswith('failed'):
                result['issues'].append('model_review_failed')
            fields = ','.join(json_field('report_json',[k]) + ' AS ' + k
                              for k in ('observations','informative_completed','verdict'))
            rows = c.execute('SELECT id,' + fields + " FROM RULE_EXPERIMENTS WHERE status='shadow_running' LIMIT 10").fetchall()
            result['forward_experiments'] = [dict(r) for r in rows]
            result['forward_evidence_note'] = 'Counts across experiments may share opportunities; do not add them as independent trades.'
    except Exception as exc:
        result['issues'].append('research_evidence_unavailable:' + type(exc).__name__)
    try:
        with e.transaction(db) as c:
            fees = c.execute("SELECT broker,COUNT(*) AS closed,COUNT(net_pnl) AS verified_net "
                             "FROM LOGICAL_TRADES WHERE terminal=1 GROUP BY broker").fetchall()
            result['trade_cost_coverage'] = [dict(r) for r in fees]
            if any(r['closed'] != r['verified_net'] for r in fees):
                result['issues'].append('individual_net_outcomes_unverified')
            result['cost_limitation'] = ('Account-level fees without order/trade identity cannot be allocated as verified individual costs. '
                                        'Estimated results remain provisional; unknown net is not zero.')
    except Exception:
        result['issues'].append('trade_cost_coverage_unavailable')
    try:
        with e.transaction(db) as c:
            cutoff = (e.stamp(now)-timedelta(days=1)).isoformat()
            rows = c.execute("SELECT job_name,status,COUNT(*) AS count,MAX(completed_at) AS latest FROM SCHEDULED_JOB_RUNS "
                "WHERE COALESCE(started_at,scheduled_for)>=? AND started_at IS NOT NULL "
                "AND status IN ('failed','timed_out') GROUP BY job_name,status", (cutoff,)).fetchall()
            result['failed_jobs_24h'] = [dict(r) for r in rows]
            if rows:
                result['issues'].append('failed_or_timed_out_jobs')
            assessment = c.execute('SELECT created_at,status FROM AI_SELF_ASSESSMENTS ORDER BY created_at DESC LIMIT 1').fetchone()
            result['self_assessment'] = dict(assessment) if assessment else None
            if not assessment or assessment['status'] == 'evidence_fallback':
                result['issues'].append('self_assessment_not_model_verified')
    except Exception as exc:
        result['issues'].append('job_evidence_unavailable:' + type(exc).__name__)
    result['status'] = 'attention_required' if result['issues'] else 'operational_checks_passed'
    return result
