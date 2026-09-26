import io
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from urllib.request import Request

import pytest
from ai_trader import ai_budget as b, experiments as e
from ai_trader.openai_transport import responses


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_TRADER_DATABASE_BACKEND', 'sqlite')
    monkeypatch.setenv('OPENAI_BUDGET_ENFORCED', '1')
    monkeypatch.delenv('RENDER', raising=False)
    monkeypatch.delenv('RENDER_SERVICE_ID', raising=False)
    monkeypatch.delenv('RENDER_INSTANCE_ID', raising=False)
    db = tmp_path / 'budget.sqlite3'
    monkeypatch.setenv('AI_TRADER_DB_PATH', str(db))
    monkeypatch.setattr(e, 'now_iso', lambda: '2026-09-26T12:00:00+00:00')
    e.migrate(db)
    with e.transaction(db) as c:
        e.put_control(c, 'openai_budget_policy', {'start_month': '2026-09', 'opening_micro_usd': 0})
    return db


def test_concurrent_reservations_cannot_exceed_shared_allowance(ledger):
    def attempt(_):
        try:
            return b.reserve('explanation', 1_000_000)
        except b.BudgetUnavailable:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = [r for r in pool.map(attempt, range(12)) if r]
    assert len(accepted) == 7
    assert b.status(ledger)['groups']['conversation']['accounted_and_reserved_usd'] == 7
    b.settle(accepted[0], 100_000)
    b.settle(accepted[0], 0)  # duplicate completion must not double-refund
    assert b.status(ledger)['accounted_and_reserved_usd'] == 6.1


def test_opening_spend_not_reset_and_month_rollover(ledger):
    with e.transaction(ledger) as c:
        e.put_control(c, 'openai_budget_policy', {'start_month': '2026-09', 'opening_micro_usd': 105_430_000})
    with pytest.raises(b.BudgetUnavailable):
        b.reserve('explanation', 100)
    receipt = b.reserve('explanation', 100, now='2026-10-01T00:00:00+00:00')
    assert receipt[0] == '2026-10'


def test_missing_policy_and_unknown_model_do_not_send(ledger):
    with e.transaction(ledger) as c:
        c.execute("DELETE FROM EXPERIMENT_CONTROL WHERE id='openai_budget_policy'")
    opener = Mock()
    request = Request('https://api.openai.com/v1/responses', data=b'{"model":"gpt-6-luna","input":"hello"}')
    with pytest.raises(b.BudgetUnavailable):
        responses(request, category='explanation', timeout=1, opener=opener)
    opener.assert_not_called()
    with pytest.raises(b.BudgetUnavailable):
        b.text_cost('unknown', 100, 100)


def test_timeout_holds_cost_and_no_retry(ledger):
    opener = Mock(side_effect=TimeoutError())
    request = Request('https://api.openai.com/v1/responses', data=b'{"model":"gpt-6-luna","input":"hello"}')
    with pytest.raises(TimeoutError):
        responses(request, category='explanation', timeout=1, opener=opener)
    assert opener.call_count == 1
    status = b.status(ledger)
    assert status['accounted_and_reserved_usd'] > 0
    assert status['unknown_bills'] == 1


def test_usage_includes_reasoning_tokens_and_receipt_settles(ledger):
    raw = {'output_text': 'Do not trade', 'usage': {'input_tokens': 100, 'output_tokens': 200,
           'output_tokens_details': {'reasoning_tokens': 150}}}
    opener = Mock(return_value=io.BytesIO(json.dumps(raw).encode()))
    request = Request('https://api.openai.com/v1/responses', data=b'{"model":"gpt-6-sol","input":"hello"}')
    assert responses(request, category='experiment_proposals', timeout=1, opener=opener) == raw
    assert b.status(ledger)['accounted_and_reserved_usd'] == b.text_cost('gpt-6-sol', 100, 200)/1e6


def test_routing_does_not_migrate_live_decisions():
    assert b.model_for('explanation', 'gpt-6-astra') == 'gpt-6-luna'
    assert b.model_for('experiment_proposals', 'gpt-4.1-mini') == 'gpt-6-sol'
    for category in ('crypto_review', 'market_forecast', 'equity_proposal', 'reference_assessment'):
        assert b.model_for(category, 'pinned-live-model') == 'pinned-live-model'


def test_db_failure_does_not_send_or_bypass_review(ledger, monkeypatch):
    monkeypatch.setattr(b, 'reserve', Mock(side_effect=RuntimeError('database down')))
    opener = Mock()
    request = Request('https://api.openai.com/v1/responses', data=b'{"model":"gpt-6-astra","input":"hello"}')
    with pytest.raises(b.BudgetUnavailable):
        responses(request, category='crypto_review', timeout=1, opener=opener)
    opener.assert_not_called()


def test_settlement_failure_preserves_received_veto(ledger, monkeypatch):
    monkeypatch.setattr(b, 'settle', Mock(side_effect=RuntimeError('database down')))
    raw = {'output_text': 'veto', 'usage': {'input_tokens': 10, 'output_tokens': 10}}
    request = Request('https://api.openai.com/v1/responses', data=b'{"model":"gpt-6-astra","input":"hello"}')
    assert responses(request, category='crypto_review', timeout=1,
                     opener=lambda *a, **k: io.BytesIO(json.dumps(raw).encode())) == raw
    assert b.status(ledger)['pending_requests'] == 1


def test_agreement_and_failed_peer_stop():
    from ai_trader.standup import substantive_reply, DEFAULT_EXCHANGE_BUDGET
    assert DEFAULT_EXCHANGE_BUDGET == 0
    assert not substantive_reply('Agreed — nothing to add.', 'answered')
    assert not substantive_reply('The trader could not answer', 'failed')
    assert substantive_reply('The fee total conflicts with the recorded fills.', 'answered')


def test_voice_reply_reserves_shared_allowance_before_dispatch(ledger):
    import threading
    from ai_trader import trader_voice as v
    socket = Mock()
    state = {'db': ledger, 'stop': threading.Event(), 'awaiting': False,
             'remaining': 9_000_000, 'ws': socket}
    v._respond(state)
    assert b.status(ledger)['accounted_and_reserved_usd'] == 1.1
    assert state['budget_receipt']
    assert socket.send.call_count == 1
    b.settle(state['budget_receipt'], 50_000)
    b.reserve('explanation', 6_950_000)
    state['awaiting'] = False
    v._respond(state)
    assert state['stop'].is_set()
    assert socket.send.call_count == 1


def test_speech_and_recording_use_shared_allowance(ledger, monkeypatch):
    import wave
    from ai_trader.ai import OpenAISpeaker, OpenAITranscriber
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b'\0' * 16000)
    calls = []
    def opened(req, **kwargs):
        calls.append(req.full_url)
        return io.BytesIO(b'{"text":"hello"}' if 'transcriptions' in req.full_url else b'mp3')
    monkeypatch.setattr('ai_trader.ai.urlopen', opened)
    assert OpenAISpeaker('fake').speak('Hello') == b'mp3'
    assert OpenAITranscriber('fake').transcribe(audio.getvalue(), filename='a.wav') == 'hello'
    assert len(calls) == 2
    assert b.status(ledger)['groups']['conversation']['accounted_and_reserved_usd'] > 0
    with pytest.raises(b.BudgetUnavailable):
        OpenAITranscriber('fake').transcribe(b'not a recording')
    assert len(calls) == 2


def test_chat_cache_keeps_current_evidence_outside_instruction_prefix(ledger):
    from ai_trader.ai import OpenAIReadOnlyExplainer
    from unittest.mock import patch
    requests = []
    def opened(req, **kwargs):
        requests.append(json.loads(req.data))
        return io.BytesIO(b'{"output_text":"No proof yet","usage":{"input_tokens":100,"output_tokens":10}}')
    with patch('ai_trader.ai.urlopen', side_effect=opened):
        OpenAIReadOnlyExplainer('fake', 'gpt-6-astra').answer('Am I improving?', {'closed_trades': 120, 'proof': None})
    sent = requests[0]
    assert sent['input'][0]['role'] == 'developer'
    assert sent['input'][0]['content'][0]['prompt_cache_breakpoint'] == {'mode': 'explicit'}
    assert json.loads(sent['input'][1]['content'])['context'] == {'closed_trades': 120, 'proof': None}


def test_hosted_search_cannot_make_unbounded_tool_calls(ledger):
    seen = []
    def opened(req, **kwargs):
        seen.append(json.loads(req.data))
        return io.BytesIO(b'{"usage":{"input_tokens":100,"output_tokens":10}}')
    payload = {'model': 'gpt-4.1-mini', 'input': 'Find evidence', 'tools': [{'type': 'web_search_preview'}]}
    responses(Request('https://api.openai.com/v1/responses', data=json.dumps(payload).encode()),
              category='benchmark_research', timeout=1, opener=opened)
    assert seen[0]['max_tool_calls'] == 1
    assert b.status(ledger)['groups']['research']['accounted_and_reserved_usd'] > .05
