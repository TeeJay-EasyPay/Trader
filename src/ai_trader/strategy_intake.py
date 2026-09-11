"""Curated source intake. No network fetching, downloaded-code execution or orders."""
from urllib.parse import urlparse
from . import experiments as e

PREFIX = 'source_intake:'


def ingest(db, raw):
    if not isinstance(raw, dict) or len(e.dump(raw)) > 18000:
        raise ValueError('Import must be an object below 18KB')
    url = str(raw.get('url', ''))
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.tradingview.com','tradingview.com') or not parsed.path.startswith('/script/'):
        raise ValueError('A public TradingView script URL is required')
    if parsed.username or parsed.password or parsed.query:
        raise ValueError('Remove credentials and query parameters from source URL')
    title, author = str(raw.get('title','')).strip(), str(raw.get('author','')).strip()
    if not title or not author:
        raise ValueError('Title and author required')
    text = str(raw.get('source_text',''))
    permitted = raw.get('reuse_checked') is True and bool(raw.get('license_basis'))
    if text and not permitted:
        raise ValueError('Do not retain source text without checked reuse permission')
    rules = raw.get('rules') or {}
    if not isinstance(rules,dict) or not isinstance(raw.get('checks') or {},dict) or not isinstance(raw.get('external_backtest') or {},dict):
        raise ValueError('Rules, checks and external backtest must be objects')
    if raw.get('broker') not in ('alpaca','kraken'):
        raise ValueError('Select Alpaca or Kraken for the research idea')
    # Uploaded text is untrusted evidence only. It is never passed to exec/eval.
    fingerprint = e.digest(dict(url=url, text=text, rules=rules, broker=raw.get('broker'),
        checks=raw.get('checks'),license_basis=raw.get('license_basis'),purpose=raw.get('purpose'),source_version=raw.get('source_version')))
    item = dict(id=fingerprint, url=url, title=title[:200], author=author[:200],
        source_version=str(raw.get('source_version','unknown'))[:200], source_hash=e.digest(text),
        accessed_at=e.now_iso(), license_basis=str(raw.get('license_basis','unknown'))[:1000],
        reuse_checked=permitted, source_text=text, rules=rules,
        external_backtest=raw.get('external_backtest') or {'status':'unknown'},
        limitations=str(raw.get('limitations','Not independently reproduced'))[:1500],
        purpose=str(raw.get('purpose',''))[:1000], checks=raw.get('checks') or {},
        status='needs_clarification', broker=raw.get('broker'), linked_experiment=None)
    if not permitted:
        item['status']='reuse_blocked'
    elif not all(item['checks'].get(k) is True for k in ('exact_rules','no_lookahead','costs_reviewed','data_available')):
        item['status']='needs_clarification'
    elif rules.get('rule_type') not in ('minimum_target_r','replace_target_r_gate','minimum_target_move_bps'):
        item['status']='development_required'
    else:
        e.validate_spec(dict(rules, broker=item['broker'], hypothesis=item['purpose'], evidence_ids=[1]))
        item['status']='eligible_for_testing'
    with e.transaction(db) as c:
        old=e.control(c,PREFIX+fingerprint)
        if old:
            return {**old,'duplicate':True}
        if c.execute('SELECT COUNT(*) FROM EXPERIMENT_CONTROL WHERE id LIKE ?', (PREFIX+'%',)).fetchone()[0]>=50:
            raise ValueError('Curated intake limit reached (50)')
        e.put_control(c,PREFIX+fingerprint,item)
    return item


def list_sources(db):
    import json
    with e.transaction(db) as c:
        return [{k:v for k,v in json.loads(r[0]).items() if k != 'source_text'} for r in
                c.execute('SELECT payload_json FROM EXPERIMENT_CONTROL WHERE id LIKE ? ORDER BY id LIMIT 50',(PREFIX+'%',)).fetchall()]


def queue_source(db, sid):
    with e.transaction(db) as c:
        item=e.control(c,PREFIX+sid)
    if not item or item['status'] not in ('eligible_for_testing','linked_experiment'):
        raise ValueError('Source not validated for testing')
    if item.get('linked_experiment'):
        return e.detail(db,item['linked_experiment'])
    row=e.create_experiment(db,dict(item['rules'],broker=item['broker'],hypothesis=item['purpose'],
        source_intake_id=sid,evidence_ids=[]),queue=True)
    with e.transaction(db) as c:
        item.update(linked_experiment=row['id'],status='linked_experiment')
        e.put_control(c,PREFIX+sid,item)
    return row


def approve_implementation(db, sid, version):
    """Single-owner authenticated adapter records approval of immutable content.

    This authorizes an implementation task only, never code execution or trading.
    """
    with e.transaction(db) as c:
        if e.uses_postgres(): c.execute('SELECT pg_advisory_xact_lock(71911504)')
        item=e.control(c,PREFIX+sid)
        if not item or version != item['id']:
            raise ValueError('Stale source version')
        if item['status']=='implementation_approved': return item
        if item['status']!='development_required': raise ValueError('No development request awaiting approval')
        item.update(status='implementation_approved', implementation_request=dict(
            approved_at=e.now_iso(),approved_by='founder',version=version,
            requirements=item['rules'],source_url=item['url'],purpose=item['purpose'],
            acceptance_tests='Validate exact rules, leakage, data, fills, costs, risk controls and rollback. Shadow only; no live activation.',
            deployment=None,commit=None))
        e.put_control(c,PREFIX+sid,item)
        return item
