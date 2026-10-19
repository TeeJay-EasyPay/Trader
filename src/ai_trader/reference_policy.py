"""Pure reference eligibility. Review dates are not factual effective dates."""
from datetime import date


def day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def eligibility(metadata, *, start, end, reviewed_at):
    kind = metadata.get('reference_kind', 'unclassified')
    due, today = day(metadata.get('review_due')), day(reviewed_at)
    warning = 'maintenance_review_due' if not due or not today or due < today else None
    if kind == 'general_guidance':
        return {'usable': True, 'basis': 'methodology_not_verified_costs', 'warning': warning}
    # Mixed/unclassified documents are never silently treated as timeless facts.
    if kind != 'dated_fact':
        return {'usable': False, 'basis': 'classification_required', 'warning': warning}
    first, last = day(start), day(end)
    effective, until = day(metadata.get('effective_from')), day(metadata.get('effective_until'))
    verified = day(metadata.get('verified_through'))
    valid = (first and last and effective and until and verified and
             effective <= first <= last <= until and last <= verified)
    return {'usable': bool(valid), 'basis': 'historical_fact_in_verified_interval' if valid
            else 'dated_fact_interval_unverified', 'warning': warning}
