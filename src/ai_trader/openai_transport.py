"""One budget gate for paid Responses requests; no automatic retries/fallbacks."""
import json
from . import ai_budget as budget


def responses(request, *, category, timeout, opener):
    payload = json.loads(request.data)
    model = payload['model']
    web_search = payload.get('tools') == [{'type': 'web_search_preview'}]
    if web_search:
        payload['max_tool_calls'] = 1
    payload.setdefault('max_output_tokens', 6000)
    payload['service_tier'] = 'default'
    if model in ('gpt-6-luna', 'gpt-6-sol'):
        payload['reasoning'] = {'effort': 'none' if category == 'explanation' else 'medium'}
    if category == 'explanation' and model == 'gpt-6-luna' and isinstance(payload.get('input'), str):
        try:
            prompt = json.loads(payload['input'])
        except (ValueError, TypeError):
            prompt = None
        # Only the common instruction prefix is explicitly cached. Variable
        # evidence/history remains intact and is never mistaken for instructions.
        if isinstance(prompt, dict) and isinstance(prompt.get('instruction'), str):
            instruction = prompt.pop('instruction')
            payload['input'] = [
                {'role': 'developer', 'content': [{'type': 'input_text', 'text': instruction,
                  'prompt_cache_breakpoint': {'mode': 'explicit'}}]},
                {'role': 'user', 'content': json.dumps(prompt, separators=(',', ':'))}]
            payload['prompt_cache_options'] = {'mode': 'explicit', 'ttl': '30m'}
    request.data = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    receipt = None
    if budget.enabled():
        if (payload.get('tools') and not web_search) or payload.get('previous_response_id'):
            raise budget.BudgetUnavailable('This request has no bounded tool/context cost accounting.')
        inputs = len(request.data) + 2048  # UTF-8 bytes upper-bound text tokens plus protocol margin.
        if web_search:
            # One tool call can expand input context. Reserve above the complete
            # 1M-token model context, then settle usage plus a conservative tool fee.
            inputs = max(inputs, 2_000_000)
        try:
            receipt = budget.reserve(category, budget.text_cost(model, inputs, payload['max_output_tokens'])
                                     + (50_000 if web_search else 0))
        except budget.BudgetUnavailable:
            raise
        except Exception as exc:
            raise budget.BudgetUnavailable('OpenAI allowance could not be verified; request not sent.') from exc
    try:
        with opener(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode('utf-8'))
        if receipt:
            usage = raw.get('usage') or {}
            cost = None
            if isinstance(usage.get('input_tokens'), int) and isinstance(usage.get('output_tokens'), int):
                try:
                    cost = budget.text_cost(model, usage['input_tokens'], usage['output_tokens']) + (50_000 if web_search else 0)
                except ValueError:
                    pass
            try:
                budget.settle(receipt, cost)
            except Exception:
                # Keep the full reservation. Never discard a received veto because
                # accounting is temporarily unavailable.
                pass
        if category == 'crypto_review' and raw.get('status') == 'incomplete':
            raise budget.BudgetUnavailable('AI review stopped at its generation limit; candidate not approved.')
        return raw
    except Exception as exc:
        from .provider_errors import details
        failure = details(exc)
        # Persist only compact error codes. A successful scheduler return must
        # not hide repeated provider failures behind a generic fallback.
        if budget.enabled():
            try:
                from . import experiments as e
                with e.transaction(budget.db_path()) as conn:
                    e.put_control(conn, 'openai_failure:' + category,
                                  {'at': e.now_iso(), 'model': model, **failure})
            except Exception:
                pass
        exc.provider_failure = failure
        if receipt:
            try:
                budget.settle(receipt)  # timeout/error may still have incurred a provider charge
            except Exception:
                pass  # the durable upfront charge remains held
        raise
