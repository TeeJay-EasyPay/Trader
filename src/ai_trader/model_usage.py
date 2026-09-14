"""Small daily aggregates, not prompts or per-token event logs."""
import hashlib
from pathlib import Path
from . import experiments as e


def record(category, model, usage):
    if not e.uses_postgres():
        return
    identity = e.now_iso()[:10]+':'+hashlib.sha256((category+'|'+model).encode()).hexdigest()[:20]
    with e.transaction(Path('data/audit.sqlite3')) as c:
        c.execute('SELECT pg_advisory_xact_lock(71911510)')
        prior=e.control(c,'model_usage:'+identity,dict(day=e.now_iso()[:10],category=category,model=model,
                         calls=0,input_tokens=0,output_tokens=0,cached_tokens=0,unknown_usage=0))
        prior['calls']+=1
        if usage.get('input_tokens') is None or usage.get('output_tokens') is None:
            prior['unknown_usage']+=1
        for name in ('input_tokens','output_tokens'):
            prior[name]+=int(usage.get(name) or 0)
        prior['cached_tokens']+=int((usage.get('input_tokens_details') or {}).get('cached_tokens') or 0)
        e.put_control(c,'model_usage:'+identity,prior)
