"""Shared USD reservations for API and worker. No prompts or trading records.

Reservations are charged before dispatch. A timeout, crash or missing usage keeps
the charge: absence of a response is not evidence of absence of a provider bill.
The policy must include an opening balance for the activation month. This is an
app allowance, not an OpenAI credit balance or an organization-wide hard limit.
"""
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
import os
from pathlib import Path
from uuid import uuid4

from . import experiments as e

MICRO = 1_000_000
LIMITS = {'trading': 18 * MICRO, 'conversation': 7 * MICRO, 'research': 5 * MICRO}
# Standard text prices per million tokens, verified 2026-09-26. Cache savings
# are deliberately not credited; reservations include a 25% input margin.
RATES = {'gpt-6-luna': ('0.10', '0.50'), 'gpt-6-sol': ('2', '10'),
         'gpt-6-astra': ('10', '50'), 'gpt-4.1-mini': ('0.40', '1.60'),
         'gpt-4.1': ('2', '8')}


class BudgetUnavailable(RuntimeError):
    """A paid request was not sent; callers must never treat this as approval."""


def db_path():
    return Path(os.environ.get('AI_TRADER_DB_PATH', 'data/audit.sqlite3'))


def enabled():
    # Production uses the shared PostgreSQL ledger. Local tests/development must
    # opt in explicitly; they must not accidentally share a production allowance.
    from .database import is_hosted_runtime
    return is_hosted_runtime() or e.uses_postgres() or os.environ.get('OPENAI_BUDGET_ENFORCED') == '1'


@contextmanager
def locked(db):
    with e.transaction(db) as conn:
        if e.uses_postgres():
            conn.execute('SELECT pg_advisory_xact_lock(71911511)')
        else:
            conn.execute('BEGIN IMMEDIATE')
        yield conn


def bucket(category):
    if category in ('explanation', 'voice', 'speech', 'transcription'):
        return 'conversation'
    if category in ('experiment_proposals', 'experiment_reviews', 'reference_assessment', 'benchmark_research'):
        return 'research'
    return 'trading'


def model_for(category, configured):
    if category == 'explanation':
        return 'gpt-6-luna'
    if category in ('experiment_proposals', 'experiment_reviews'):
        return 'gpt-6-sol'
    # Live assessments/forecasts retain their evaluated model. Never silently
    # escalate to Astra or move risk-bearing decisions to an unevaluated model.
    return configured


def text_cost(model, inputs, outputs):
    if model not in RATES:
        raise BudgetUnavailable('No verified cost bound for this model; request not sent.')
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (inputs, outputs)):
        raise ValueError('Invalid token usage')
    inp, out = map(Decimal, RATES[model])
    if inputs > 272000 and model.startswith('gpt-6-'):
        inp *= 2
        out *= Decimal('1.5')
    return int((inputs * inp * Decimal('1.25') + outputs * out).to_integral_value(rounding=ROUND_CEILING))


def _account(conn, month):
    policy = e.control(conn, 'openai_budget_policy')
    if not policy or not policy.get('start_month') or month < policy['start_month']:
        raise BudgetUnavailable('OpenAI allowance needs its opening balance confirmed; request not sent.')
    opening = int(policy.get('opening_micro_usd', -1)) if month == policy['start_month'] else 0
    if opening < 0:
        raise BudgetUnavailable('OpenAI opening spend is unknown; request not sent.')
    return e.control(conn, 'openai_budget:' + month,
                     {'charged': opening, 'opening': opening, 'groups': {}, 'pending': {}, 'unknown': 0})


def reserve(category, amount, *, db=None, now=None):
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError('A positive cost reservation is required')
    month = (now or e.now_iso())[:7]
    group = bucket(category)
    with locked(db or db_path()) as conn:
        account = _account(conn, month)
        if (account.get('bound_exceeded') or account['charged'] + amount > 30 * MICRO or
                account['groups'].get(group, 0) + amount > LIMITS[group]):
            raise BudgetUnavailable('OpenAI monthly ' + group + ' allowance reached; request not sent.')
        if len(account['pending']) >= 100:
            raise BudgetUnavailable('Unresolved OpenAI requests need accounting review; request not sent.')
        identity = uuid4().hex
        account['charged'] += amount
        account['groups'][group] = account['groups'].get(group, 0) + amount
        account['pending'][identity] = {'amount': amount, 'group': group}
        e.put_control(conn, 'openai_budget:' + month, account)
    return (month, identity)


def settle(receipt, actual=None, *, db=None):
    """Idempotent. Unknown bills retain the reservation, not an automatic refund."""
    if actual is not None and (isinstance(actual, bool) or not isinstance(actual, int) or actual < 0):
        raise ValueError('Invalid actual cost')
    month, identity = receipt
    with locked(db or db_path()) as conn:
        account = _account(conn, month)
        pending = account['pending'].pop(identity, None)
        if pending is None:
            return
        if actual is None:
            account['unknown'] += 1
        else:
            delta = actual - pending['amount']
            account['charged'] += delta
            account['groups'][pending['group']] += delta
            # An underestimated request must visibly block new calls, not hide an overrun.
            if delta > 0:
                account['bound_exceeded'] = True
        e.put_control(conn, 'openai_budget:' + month, account)


def status(db):
    month = e.now_iso()[:7]
    try:
        with e.transaction(db) as conn:
            account = _account(conn, month)
        return {'status': 'exhausted' if account['charged'] >= 30 * MICRO or account.get('bound_exceeded') else 'available',
                'month': month, 'limit_usd': 30, 'accounted_and_reserved_usd': account['charged']/MICRO,
                'remaining_usd': 0 if account.get('bound_exceeded') else max(0, 30-account['charged']/MICRO),
                'pending_requests': len(account['pending']), 'unknown_bills': account['unknown'],
                'groups': {k: {'limit_usd': v/MICRO, 'accounted_and_reserved_usd': account['groups'].get(k, 0)/MICRO}
                           for k, v in LIMITS.items()},
                'scope': 'Conservative app allowance; not provider credit balance. Excludes other apps and Anthropic.'}
    except BudgetUnavailable as exc:
        return {'status': 'needs_opening_balance', 'limit_usd': 30, 'message': str(exc)}
