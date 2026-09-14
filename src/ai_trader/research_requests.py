"""Bounded, durable research intake. No orders, live activation or paid calls.

Chat and scheduled proposals share the existing worker and its daily reservation.
Ideas are not experiments until create_experiment returns a persisted ID.
"""
from uuid import uuid4
import json
from contextvars import ContextVar
from contextlib import contextmanager

CHAT_RESEARCH_ENABLED = ContextVar('chat_research_enabled', default=False)


@contextmanager
def chat_scope(enabled):
    token = CHAT_RESEARCH_ENABLED.set(enabled)
    try:
        yield
    finally:
        CHAT_RESEARCH_ENABLED.reset(token)
from . import experiments as e

OBJECTIVE = (
    'Aim to become the most effective trader possible through evidence-based learning: '
    'improve sustainable returns after costs within approved risk and spending limits. '
    'Protect capital; choosing not to trade is valid. Distinguish observations, hypotheses, '
    'tested findings and activated changes. Never claim an edge or improvement without '
    'supporting outcomes. Study failures as well as successes. Propose falsifiable, supported '
    'shadow tests, retain their evidence, and use only approved changes in trading. '
    'This objective does not permit increased risk, arbitrary code, live activation or extra paid calls.'
)


def enqueue(db, idea, *, source='user_chat', broker=None, now=None):
    idea = str(idea or '').strip()
    if not 15 <= len(idea) <= 1500:
        raise ValueError('Describe a testable research question in 15 to 1500 characters')
    if source not in ('user_chat', 'trader_ai', 'application_rule'):
        raise ValueError('Invalid research source')
    if broker not in (None, 'alpaca', 'kraken'):
        raise ValueError('Unsupported broker')
    now = now or e.now_iso()
    with e.transaction(db) as c:
        if e.uses_postgres():
            c.execute('SELECT pg_advisory_xact_lock(71911501)')
        queue = e.control(c, 'research_requests', [])
        fingerprint = e.digest(dict(idea=idea.casefold(), broker=broker))
        duplicate = next((x for x in queue if x['fingerprint'] == fingerprint), None)
        if duplicate:
            return duplicate
        if sum(x['status'] == 'pending' for x in queue) >= 20:
            raise ValueError('Research queue full; review pending requests first')
        request = dict(id=str(uuid4()), idea=idea, source=source, broker=broker,
                       created_at=now, fingerprint=fingerprint, status='pending',
                       message='Queued for the next eligible daily research batch; not a running experiment.')
        # Keep pending work plus a bounded recent history, never discard pending work.
        pending = [x for x in queue if x['status'] == 'pending']
        history = [x for x in queue if x['status'] != 'pending'][-20:]
        e.put_control(c, 'research_requests', history + pending + [request])
        return request


def snapshot(conn):
    return [dict(id=x['id'], idea=x['idea'], source=x['source'], broker=x['broker'])
            for x in e.control(conn, 'research_requests', []) if x['status'] == 'pending'][:20]


def finish(conn, requests, result, now):
    ids = {r['id'] for r in requests}
    queue = e.control(conn, 'research_requests', [])
    for item in queue:
        if item['id'] in ids and item['status'] == 'pending':
            linked = [eid for eid, request_ids in result.get('request_links', {}).items() if item['id'] in request_ids]
            item.update(status='linked_experiment' if linked else 'needs_review', reviewed_at=now,
                        batch_status=result['status'], experiment_ids=linked,
                        message=('Registered experiment IDs: '+', '.join(linked)) if linked else
                        'No experiment registered for this request. '+str(result.get('reason') or 'No supported proposal was linked; review evidence and simulator support.'))
    e.put_control(conn, 'research_requests', queue)


def provenance(conn, eid, requests, now):
    e.put_control(conn, 'experiment_origin:' + eid, dict(
        proposed_by='Trader AI', trigger='daily_review_with_chat_requests' if requests else 'daily_evidence_review',
        request_ids=[r['id'] for r in requests], recorded_at=now))


def annotate(db, row):
    with e.transaction(db) as c:
        row['origin'] = e.control(c, 'experiment_origin:' + row['id'],
                                  {'proposed_by': 'Not recorded in this version', 'trigger': 'unknown'})
    return row


def chat_context(db):
    from .model_usage import summary
    from .trader_voice import budget
    usage = summary(db)
    voice = budget(db)
    usage['voice_allowance'] = {k: voice[k] for k in ('month', 'spent_usd', 'allowance_usd', 'remaining_micro')}
    with e.transaction(db) as c:
        rows = c.execute('SELECT id,status,spec_json,report_json FROM RULE_EXPERIMENTS ORDER BY created_at DESC LIMIT 10').fetchall()
        summaries = []
        for r in rows:
            spec, report = json.loads(r[2]), json.loads(r[3])
            summaries.append(dict(id=r[0], status=r[1], hypothesis=spec['hypothesis'], broker=spec['broker'],
                                  observations=report.get('observations'), closed_trades=report.get('closed_trades'),
                                  verdict=report.get('verdict'), reason=report.get('reason')))
        return dict(objective=OBJECTIVE, model_usage=usage, experiments=summaries, requests=e.control(c, 'research_requests', [])[-20:],
                    daily_batch=e.control(c, 'proposal_attempt', {}),
                    capabilities='May submit research requests, not broker orders or live changes. Pending is not running.')


def interpret_reply(db, raw):
    """Single existing chat response can request research; no second model call.

The only mutation is a bounded research request. Never execute model code, SQL,
broker commands or arbitrary tool names. The app supplies the resulting receipt.
"""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return str(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get('answer'), str):
        return str(raw)
    text = payload['answer']
    request = payload.get('research_request')
    if isinstance(request, dict):
        try:
            receipt = enqueue(db, request.get('idea'), source='trader_ai', broker=request.get('broker'))
            text += '\n\nResearch request ' + receipt['id'] + ': ' + receipt['message']
        except ValueError as exc:
            text += '\n\nResearch request was not registered: ' + str(exc)
    return text


CHAT_FORMAT = (
    '\nReturn JSON with answer (a natural conversational reply) and optionally research_request '
    '{idea, broker}, where broker is alpaca, kraken or null. A research_request is only a suggestion '
    'for the app to register after this response, not an action already completed. Do not say it '
    'was saved, started or created: the app appends its receipt. Submit only a specific justified '
    'new question or one the Founder requested, not a duplicate of pending or running work. '
    'Unsupported tests should explicitly be described as needing implementation; do not pretend '
    'the simulator supports them. Do not include a research_request for ordinary questions.'
)
