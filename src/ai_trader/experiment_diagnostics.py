"""Explain evidence gaps without changing experiment rules or verdicts."""
import json


def diagnose(report):
    def number(key):
        value = report.get(key)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError, OverflowError):
            return None
    observations = number('observations')
    informative = number('informative_completed')
    differences = number('decision_differences')
    closed = report.get('closed_trades') or {}
    if isinstance(closed, str):
        try:
            closed = json.loads(closed)
        except ValueError:
            closed = {}
    if not isinstance(closed, dict):
        closed = {}
    if observations is None or informative is None:
        status = 'diagnostic_evidence_unavailable'
    elif not observations:
        status = 'no_observations'
    elif informative == 0 and number('both_skipped') == observations:
        status = 'all_opportunities_blocked'
    elif closed.get('candidate') == 0 and (informative or 0)>0:
        status = 'candidate_has_no_closed_trades'
    elif differences == 0 and (informative or 0)>0:
        status = 'no_entry_selection_difference_observed'
    elif differences is None:
        status = 'diagnostic_evidence_unavailable'
    else:
        status = 'collecting_comparisons'
    shortfalls = {}
    for observed, required in (('informative_completed','minimum_opportunities'),
                               ('day_clusters','minimum_independent_days'),
                               ('symbol_days','minimum_symbol_days')):
        have, need = number(observed), number(required)
        shortfalls[observed] = max(0,need-have) if have is not None and need is not None else None
    return dict(status=status, decision_differences=differences, frozen_sample_shortfalls=shortfalls,
        candidate_closed=closed.get('candidate'),
        note='Diagnostic only: equal selections do not prove equal sizing/exits or a software fault. Zero trades is not profitability.')
