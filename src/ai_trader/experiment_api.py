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
        return 200, exp.list_experiments(db, before=first('before'), attention=first('attention') == 'true')
    except ValueError as exc:
        return 400, {'error': str(exc)}


def post(db, path, body):
    try:
        if body.get('confirmed') is not True:
            raise ValueError('Review and explicitly confirm this action')
        if path == '/experiments/decision':
            return 200, exp.decide(db, str(body.get('id', '')), version=str(body.get('version', '')),
                                  revision=body.get('revision', -1), action=str(body.get('action', '')),
                                  key=str(body.get('idempotency_key', '')), scope=body.get('scope'))
        return 404, {'error': 'Unknown experiment action'}
    except (ValueError, TypeError, KeyError) as exc:
        return 409, {'error': str(exc)}
