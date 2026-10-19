from ai_trader.reference_policy import eligibility
from ai_trader.reference_sets import review_context


def check(meta, start='2026-09-01', end='2026-09-30'):
    return eligibility(meta,start=start,end=end,reviewed_at='2026-10-19')


def test_general_guidance_due_date_warns_not_expires():
    state=check({'reference_kind':'general_guidance','review_due':'2026-10-11'})
    assert state['usable'] and state['warning']=='maintenance_review_due'


def test_mixed_and_unclassified_never_assumed_timeless():
    for kind in ('mixed','unclassified','typo'):
        assert not check({'reference_kind':kind,'review_due':'2099-01-01'})['usable']


def test_historical_fee_schedule_requires_verified_entire_interval():
    meta={'reference_kind':'dated_fact','effective_from':'2026-09-01',
          'effective_until':'2026-09-30','verified_through':'2026-09-30','review_due':'2026-10-11'}
    assert check(meta)['usable']
    assert not check(meta,end='2026-10-01')['usable']
    assert not check(meta,start='2026-08-31')['usable']
    assert not check({**meta,'verified_through':'unknown'})['usable']


def test_frozen_passages_retained_not_reloaded_or_mutated():
    frozen={'version':'original','scope':'explanation_only','passages':[
        {'document':'old','text':'old guidance','metadata':{'reference_kind':'general_guidance'}},
        {'document':'fee','text':'unverified rate','metadata':{'reference_kind':'dated_fact'}}]}
    result=review_context(frozen,start='2026-09-01',end='2026-09-30',now='2030-01-01')
    assert result['version']=='original'
    assert [p['text'] for p in result['passages']]==['old guidance']
    assert result['excluded'][0]['reason']=='dated_fact_interval_unverified'
    assert len(frozen['passages'])==2


def test_unreadable_optional_notes_do_not_block_recorded_results(monkeypatch):
    from ai_trader import reference_sets
    def unavailable(*args):
        raise OSError('unreadable local file')
    monkeypatch.setattr(reference_sets,'load_knowledge_index',unavailable)
    frozen=reference_sets.review_snapshot('stock',now='2026-10-19')
    assert frozen['passages']==[]
    result=review_context(frozen,start='2026-09-01',end='2026-09-30',now='2026-10-19')
    assert result['warnings'][0]['reason']=='reference_capture_unavailable'
