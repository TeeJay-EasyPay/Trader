import io
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from ai_trader.ai import OpenAIReadOnlyExplainer
from ai_trader.api import LocalApiService
from ai_trader import standup_turns


def test_disconnected_client_can_find_existing_work_without_restarting():
    standup_turns.reset_for_tests()
    release = threading.Event()
    calls = []
    saved_history = []
    def work(report):
        calls.append(1)
        release.wait(5)
        saved_history.append('completed answer')
        return {'turns': saved_history}
    turn_id = standup_turns.start_turn(work, conversation_id='recovery-test')
    try:
        assert standup_turns.turn_state('', conversation_id='recovery-test')['turn_id'] == turn_id
        assert standup_turns.turn_state('', conversation_id='different')['status'] == 'idle'
        release.set()
        deadline = time.monotonic() + 5
        while standup_turns.turn_state(turn_id)['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.01)
        assert saved_history == ['completed answer']
        assert calls == [1]
        assert standup_turns.turn_state('', conversation_id='recovery-test')['status'] == 'idle'
    finally:
        release.set()


def test_trader_uses_separate_bounded_budget_without_retry():
    service = SimpleNamespace(settings=SimpleNamespace(db_path='unused', openai_api_key='test', openai_reasoning_model='test-model'))
    progress = []
    with patch('ai_trader.api.input_inventory', return_value={}), patch('ai_trader.api.OpenAIReadOnlyExplainer') as explainer:
        explainer.return_value.answer.side_effect = TimeoutError()
        result = LocalApiService._trader_turn(service, [], 'question', progress.append)
        explainer.assert_called_once_with('test', 'test-model', timeout_seconds=180, max_output_tokens=6000)
        assert explainer.return_value.answer.call_count == 1
    assert result['status'] == 'failed'
    assert 'No answer was received' in result['text']
    assert progress[0]['budget_seconds'] == 180
    assert OpenAIReadOnlyExplainer('test', 'test-model').timeout_seconds == 35


def test_output_cap_reaches_provider_and_partial_answer_is_labelled():
    requests = []
    def respond(request, timeout):
        requests.append((json.loads(request.data), timeout))
        return io.BytesIO(json.dumps({'status': 'incomplete', 'output_text': 'Partial evidence'}).encode())
    with patch('ai_trader.ai.urlopen', side_effect=respond):
        answer = OpenAIReadOnlyExplainer('test', 'test-model', timeout_seconds=180, max_output_tokens=6000).answer('question', {})
    assert len(requests) == 1
    assert requests[0][0]['max_output_tokens'] == 6000
    assert requests[0][1] == 180
    assert 'Partial evidence' in answer
    assert 'stopped before completion' in answer
