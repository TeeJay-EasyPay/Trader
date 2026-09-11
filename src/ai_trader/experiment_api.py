"""Authenticated single-owner API adapter; never trusts an owner from request JSON."""
from . import experiments as exp
import os


def get(db, path, query):
    first = lambda key: (query.get(key) or [''])[0]
    try:
        if path == '/experiments/detail':
            return 200, exp.detail(db, first('id'))
        if path == '/experiments/health':
            with exp.transaction(db) as conn:
                return 200, {'policy': exp.control(conn, 'policy', exp.DEFAULT_POLICY),
                             'last_tick': exp.control(conn, 'last_tick', {}),
                             'proposal_attempt': exp.control(conn, 'proposal_attempt', {}),
                             'deployment_commit': os.getenv('RENDER_GIT_COMMIT'),
                             'live_enabled': False}
        from .strategy_intake import list_sources
        return 200, {**exp.list_experiments(db, before=first('before'), attention=first('attention') == 'true', view=first('view')), 'source_intake':list_sources(db)}
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
