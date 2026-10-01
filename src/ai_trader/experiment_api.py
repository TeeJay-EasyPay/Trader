"""Authenticated single-owner API adapter; never trusts an owner from request JSON."""
from . import experiments as exp
import os


def get(db, path, query):
    first = lambda key: (query.get(key) or [''])[0]
    try:
        if path == '/experiments/detail':
            from .research_requests import annotate
            detail = annotate(db, exp.detail(db, first('id')))
            with exp.transaction(db) as conn:
                detail['historical_screening'] = exp.control(conn, 'historical_link:'+first('id'))
            return 200, detail
        if path == '/experiments/health':
            from .db_telemetry import report
            from .research_health import snapshot as health_snapshot
            health = health_snapshot(db)
            with exp.transaction(db) as conn:
                from .experiment_assurance import json_field
                fields = ','.join(json_field('payload_json', [k], text=False) + ' AS ' + k
                                  for k in ('day','status','failure','review_count','usage'))
                attempt = conn.execute('SELECT ' + fields + " FROM EXPERIMENT_CONTROL WHERE id='proposal_attempt'").fetchone()
                return 200, {'operational_evidence': health, 'policy': exp.control(conn, 'policy', exp.DEFAULT_POLICY),
                             'database_transfer_worker': exp.control(conn, 'db_transfer_view', {}),
                             'database_transfer_api': report(),
                             'last_tick': exp.control(conn, 'last_tick', {}),
                             'proposal_attempt': dict(attempt) if attempt else {},
                             'deployment_commit': os.getenv('RENDER_GIT_COMMIT'),
                             'live_enabled': False}
        from .strategy_intake import list_sources
        with exp.transaction(db) as conn:
            requests = exp.control(conn, 'research_requests', [])[-40:]
            from .learning_measurement import snapshot
            show_research = path == '/experiments' and first('attention') != 'true'
            measurement = snapshot(conn) if show_research else None
            historical = exp.control(conn, 'historical_screening_view', {}) if show_research else None
            founder_learning = exp.control(conn, 'founder_learning_scorecard', {}) if show_research else None
            # A deployment can add fields to the compact scorecard while today's
            # persisted snapshot still has yesterday's shape. Rebuild the read view
            # immediately; the normal daily refresh persists it on its next cycle.
            if show_research and (
                not founder_learning
                or not isinstance(founder_learning.get('brokers'), dict)
                or founder_learning.get('lesson_status') not in ('none', 'provisional', 'validated')
            ):
                from .founder_learning import build
                founder_learning = build(conn, now=exp.now_iso())
        return 200, {**exp.list_experiments(db, before=first('before'), attention=first('attention') == 'true', view=first('view')), 'source_intake':list_sources(db), 'research_requests': requests,
                     'learning_measurement':measurement, 'historical_screening':historical,
                     'founder_learning':founder_learning}
    except ValueError as exc:
        return 400, {'error': str(exc)}


def post(db, path, body):
    try:
        if body.get('confirmed') is not True:
            raise ValueError('Review and explicitly confirm this action')
        if path == '/experiments/decision':
            if body.get('action') == 'approve_source_implementation':
                from .strategy_intake import approve_implementation
                return 200, approve_implementation(db,str(body.get('source_id','')),str(body.get('version','')))
            if body.get('action') == 'queue_reference_comparison':
                spec=body.get('spec') or {}
                return 200, exp.create_experiment(db, {**spec,'rule_type':'reference_set_filter','reference_sets':None}, queue=True)
            if body.get('action') == 'import_source':
                from .strategy_intake import ingest
                return 200, ingest(db, body.get('source'))
            if body.get('action') == 'queue_source':
                from .strategy_intake import queue_source
                return 200, queue_source(db, str(body.get('source_id','')))
            return 200, exp.decide(db, str(body.get('id', '')), version=str(body.get('version', '')),
                                  revision=body.get('revision', -1), action=str(body.get('action', '')),
                                  key=str(body.get('idempotency_key', '')), scope=body.get('scope'))
        return 404, {'error': 'Unknown experiment action'}
    except (ValueError, TypeError, KeyError) as exc:
        return 409, {'error': str(exc)}
