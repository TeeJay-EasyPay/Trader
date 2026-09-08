"""Claude as a participant in the Founder's standup, able to check claims before making them.

2026-09-07, Founder-directed: a daily standup between him, the trading AI, and Claude, with the
two AIs able to talk to each other and him able to interrupt.

THE POINT OF THIS FILE IS THE TOOL LOOP, not the model call. On 2026-09-06 the trading AI was
asked what was wrong and raised four defects; THREE were artefacts of the census handed to it
rather than real faults. It hedged them correctly -- "I cannot tell whether those inputs are
absent from the system or simply absent from the census" -- and was right to. A participant
that cannot look anything up produces confident, specific, wrong findings, and this project has
lost more time to those than to any bug.

So Claude gets the same three things Claude Code used to sort that out: search the source, read
a file, run one read-only SELECT. It can therefore answer "is that table actually read by
anything?" by going and looking, which is the difference between an opinion and a check.

WHAT IT CANNOT DO, deliberately: edit code, deploy, or write anything at all. Not because a
second Claude is more trustworthy than the first, but because the write path carries tests, a
production check and a deploy confirmation that a flowing conversation does not. See
architecture/STANDUP_CONVERSATION_SPEC_2026-09-07.md.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from .evidence_tools import TOOL_SPECS, run_tool

logger = logging.getLogger("ai_trader.api")

MODEL = "claude-opus-5"

# A conversational turn should not run away. Each iteration is a model call plus its tool
# results, so this bounds both the wait and the bill; hitting it is reported rather than
# hidden, because a truncated investigation presented as a finished one is the failure mode
# this whole file exists to prevent.
MAX_TOOL_ITERATIONS = 12
MAX_TOKENS = 8000

# ---------------------------------------------------------------------------
# COST. 2026-09-07: the Founder's first $6 of credit was gone in fifteen minutes, across four
# test questions. The console confirmed it: $5.29, one day, all Opus 5.
#
# The cause is structural, not careless use. A tool loop RESENDS THE WHOLE CONVERSATION on
# every iteration, so a question that takes 21 lookups does not pay for those tokens once --
# it pays for them again and again, and the bill grows with the square of the investigation.
#
# Three defences, in order of how much they save:
#
#   1. Prompt caching. The system prompt, the tool schemas and the conversation so far are
#      marked cacheable, so the repeated prefix is billed at a tenth of the input price
#      instead of full price. This is the fix; the other two are safety nets.
#   2. Smaller tool results. Each result sits in the history for the rest of the turn, so an
#      oversized one is paid for on every later iteration as well as its own.
#   3. A hard ceiling in POUNDS, not just in iterations. An iteration count bounds how many
#      times we look, but says nothing about how much each look costs. This is the backstop
#      that would actually have stopped the overnight burn.
# ---------------------------------------------------------------------------

CACHE_CONTROL = {"type": "ephemeral"}

# Per tool result. Chosen so a file read or a search still carries real evidence, while a
# runaway result cannot park 20k characters in the history for the rest of the turn.
MAX_TOOL_RESULT_CHARS = 10000

# Opus 5, USD per million tokens. Cache writes cost a quarter more than fresh input; cache
# reads cost a tenth. That ratio is the whole reason caching is worth the complexity here.
PRICE_PER_MTOK = {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.50}

# The stop-loss on a single turn. Deliberately low: the entire first standup, including the
# 21-lookup investigation, would have been stopped here instead of running to the end of the
# credit. Raise it knowingly, not by accident.
MAX_TURN_COST_USD = 0.60

SYSTEM_PROMPT = """You are Claude, one of two AI participants in a working standup about a live \
algorithmic trading system. The other participant is the trading intelligence that actually \
runs the account ("the trader"). The third is the Founder, who owns the system and chairs the \
conversation.

You have read-only tools: search the source, read a file, run a single read-only SELECT against \
the live database. USE THEM. This system has repeatedly lost days to confident claims that \
nobody checked, including by the trader and by Claude. If you are about to assert how the code \
behaves or what the data shows, look first.

What you can see is limited and you should say so when it matters: the deployed container holds \
src/, governance/ and knowledge/ only -- no tests, no design documents, no git history. So you \
can read the code as it runs, but not why a line was written.

You cannot change anything. No edits, no deployments. When work needs doing, describe it \
precisely enough that it can be implemented and verified, and let the Founder decide.

How to be useful here:
- Check before you claim. An answer with a query behind it beats a plausible one.
- Say "I cannot tell from what I can see" rather than filling the gap. That sentence has \
already been more valuable than several confident answers.
- Disagree with the trader when you have evidence. Disagreement that names its evidence is the \
most useful thing that can happen in this conversation.
- Be brief and specific. The Founder has asked repeatedly for short, plain English, no jargon. \
He does not read code.
"""


def is_configured() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def _plain_refusal(error: Exception) -> str:
    """Say why Claude could not answer, in words the Founder can act on.

    2026-09-07, caught by looking at the actual screen rather than the logs. The credit ran out
    and the bubble showed him this:

        Anthropic rejected the request: Error code: 400 - {'type': 'error', 'error':
        {'type': 'invalid_request_error', 'message': 'Your credit balance is too low...

    He has asked repeatedly for short plain English and no jargon. A raw API payload in a
    conversation bubble is the opposite of that, and it buries the one sentence that tells him
    what to do about it.
    """

    detail = str(error).lower()
    if "credit balance is too low" in detail or "insufficient" in detail:
        return ("Claude has run out of credit, so it cannot answer. Add funds to the Anthropic "
                "account and it will work again straight away.")
    if "rate limit" in detail or "429" in detail:
        return ("Claude is being rate limited right now. Waiting a minute and asking again "
                "usually clears it.")
    if "overloaded" in detail or "529" in detail:
        return "Anthropic's service is overloaded at the moment. Worth trying again shortly."
    if "max_tokens" in detail or "too long" in detail or "context" in detail:
        return ("That was too long for Claude to take in one go. A narrower question, or "
                "ending the conversation and starting a fresh one, will get past it.")
    # Anything unrecognised: say plainly that it was refused and keep the technical detail
    # short, rather than pasting a JSON payload into the conversation.
    return f"Claude could not answer: the request was refused ({type(error).__name__})."


def _client() -> Any:
    import anthropic

    return anthropic.Anthropic()


def _tool_definitions() -> list[dict[str, Any]]:
    """The evidence tools, in the Messages API shape.

    Built from the same TOOL_SPECS the dispatcher uses, so a description can never advertise a
    tool that does not exist or promise behaviour the function does not have.

    The last one carries a cache breakpoint, which caches the whole tool block. The schemas are
    identical on every iteration of a turn, so paying for them twelve times is pure waste.
    """

    tools = [
        {"name": spec["name"], "description": spec["description"], "input_schema": spec["input_schema"]}
        for spec in TOOL_SPECS
    ]
    if tools:
        tools[-1] = {**tools[-1], "cache_control": CACHE_CONTROL}
    return tools


def _system_blocks(system: str) -> list[dict[str, Any]]:
    """The system prompt as a cacheable block. It never changes within a turn."""

    return [{"type": "text", "text": system, "cache_control": CACHE_CONTROL}]


def _with_cache_breakpoint(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark the end of the conversation so far as cacheable.

    The breakpoint moves forward each iteration. What it caches is everything BEFORE the newest
    exchange -- which is precisely the part that would otherwise be re-sent at full price on
    every single lookup.

    Returns the history unchanged if the last message cannot be marked safely. A missed cache
    hit costs money; a malformed request costs the whole turn.
    """

    if not history:
        return history

    marked = list(history)
    last = dict(marked[-1])
    content = last.get("content")

    if isinstance(content, str):
        if not content:
            return history
        last["content"] = [{"type": "text", "text": content, "cache_control": CACHE_CONTROL}]
    elif isinstance(content, list) and content:
        blocks = list(content)
        tail = blocks[-1]
        if isinstance(tail, dict):
            blocks[-1] = {**tail, "cache_control": CACHE_CONTROL}
        elif hasattr(tail, "model_dump"):
            # An SDK block object (the assistant's own content). Converting it to a plain dict
            # is the only way to attach cache_control without mutating the SDK's object.
            blocks[-1] = {**tail.model_dump(exclude_none=True), "cache_control": CACHE_CONTROL}
        else:
            return history
        last["content"] = blocks
    else:
        return history

    marked[-1] = last
    return marked


def _add_usage(totals: dict[str, int], usage: Any) -> None:
    """Accumulate one response's tokens, keeping cached and uncached input apart.

    They are priced an order of magnitude apart, so a total that merges them cannot tell the
    Founder whether the caching is working.
    """

    totals["input"] += int(getattr(usage, "input_tokens", 0) or 0)
    totals["output"] += int(getattr(usage, "output_tokens", 0) or 0)
    totals["cache_write"] += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    totals["cache_read"] += int(getattr(usage, "cache_read_input_tokens", 0) or 0)


def _cost_usd(totals: dict[str, int]) -> float:
    return sum(totals.get(kind, 0) / 1_000_000 * price for kind, price in PRICE_PER_MTOK.items())


def ask_claude(
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    db_path: Path | None = None,
    max_iterations: int = MAX_TOOL_ITERATIONS,
    max_cost_usd: float | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """One Claude turn, with tool use resolved before returning.

    `messages` is the conversation so far in Messages API shape. The caller owns the history --
    including the trader's contributions, which are passed in as user-role context so Claude can
    respond to them. That is what lets the two of them actually talk to each other rather than
    answering the Founder in parallel.

    Returns the text, plus the tool calls made. The tool calls are returned rather than only
    logged so the Founder can see WHAT WAS CHECKED, which is the difference between trusting the
    answer and being able to audit it.

    `on_progress` is called as the turn goes: which stage it is at, how many lookups it has
    spent, and what it last reached for. 2026-09-08, Founder-reported -- a turn that takes two
    to four minutes behind a motionless spinner is indistinguishable from a hang, and he stopped
    one that was working. Saying "reading the code, lookup 6 of 12" costs nothing and is the
    difference between waiting and giving up.
    """

    if not is_configured():
        return {
            "status": "not_configured",
            "answer": "Claude is not configured on this deployment: ANTHROPIC_API_KEY is not set.",
            "tool_calls": [],
        }

    try:
        import anthropic
    except ImportError:
        return {
            "status": "sdk_missing",
            "answer": "The anthropic package is not installed on this deployment.",
            "tool_calls": [],
        }

    client = _client()
    history = [dict(message) for message in messages]
    tool_calls: list[dict[str, Any]] = []
    totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    ceiling = float(max_cost_usd if max_cost_usd is not None else MAX_TURN_COST_USD)
    stopped_on_cost = False

    def _progress(**update: Any) -> None:
        # Never allowed to break the turn it is describing. A progress line is a courtesy; the
        # answer is what he is paying for.
        if on_progress is None:
            return
        try:
            on_progress({"lookups": len(tool_calls), "max_lookups": max(1, int(max_iterations)),
                         **update})
        except Exception:  # noqa: BLE001
            logger.debug("Progress callback failed.", exc_info=True)

    def _spent() -> dict[str, Any]:
        """What this turn has cost so far, in the shape the app and the tests both read."""
        return {
            "input_tokens": totals["input"],
            "output_tokens": totals["output"],
            "cache_write_tokens": totals["cache_write"],
            "cache_read_tokens": totals["cache_read"],
            "cost_usd": round(_cost_usd(totals), 4),
        }

    for iteration in range(max(1, int(max_iterations))):
        _progress(stage="thinking")
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_system_blocks(system or SYSTEM_PROMPT),
                # Adaptive thinking: this is judgement work over real evidence, not lookup.
                thinking={"type": "adaptive"},
                tools=_tool_definitions(),
                messages=_with_cache_breakpoint(history),
            )
        except anthropic.AuthenticationError:
            return {"status": "auth_failed", "answer": "The Anthropic API key was rejected.",
                    "tool_calls": tool_calls, "usage": _spent()}
        except anthropic.BadRequestError as exc:
            # Includes "credit balance is too low", which is the Founder's to fix -- so it is
            # translated into a sentence he can act on. The raw payload goes to the log, where
            # it belongs, and never into a conversation bubble.
            logger.warning("Anthropic refused the request: %s", exc)
            return {"status": "rejected", "answer": _plain_refusal(exc),
                    "tool_calls": tool_calls, "usage": _spent()}
        except Exception as exc:  # noqa: BLE001 - a failed turn must not end the standup
            logger.exception("Claude turn failed.")
            return {"status": "failed", "answer": _plain_refusal(exc),
                    "tool_calls": tool_calls, "usage": _spent()}

        _add_usage(totals, response.usage)

        if response.stop_reason != "tool_use":
            text = "".join(block.text for block in response.content if block.type == "text")
            return {
                "status": "answered",
                "answer": text.strip(),
                "tool_calls": tool_calls,
                "model": response.model,
                "usage": _spent(),
            }

        # The stop-loss. An iteration count bounds how MANY times we look; it says nothing
        # about what each look costs, and it was the missing guard when four test questions
        # emptied the credit overnight. Checked here rather than at the top of the loop so a
        # turn that has already gone over still gets to summarise what it found.
        if _cost_usd(totals) >= ceiling:
            stopped_on_cost = True
            history.append({"role": "assistant", "content": response.content})
            history.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps({"status": "refused", "reason": "spend ceiling reached"}),
                "is_error": True,
            } for block in response.content if block.type == "tool_use"]})
            break

        # Claude wants evidence. Run every requested tool and return ALL results in ONE user
        # message -- splitting them across messages teaches the model to stop asking for things
        # in parallel, which would make every investigation slower and dearer.
        history.append({"role": "assistant", "content": response.content})
        results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            _progress(stage="looking", last_tool=block.name)
            outcome = run_tool(block.name, dict(block.input or {}))
            tool_calls.append({"tool": block.name, "input": dict(block.input or {}),
                               "status": outcome.get("status")})
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                # Truncated because this result stays in the history for the rest of the turn:
                # an oversized one is paid for on every LATER iteration too, not just its own.
                "content": json.dumps(outcome, default=str)[:MAX_TOOL_RESULT_CHARS],
                # A refused or failed lookup is marked as an error so Claude treats it as a dead
                # end and tries something else, rather than reading the refusal text as data.
                "is_error": outcome.get("status") in {"refused", "failed", "bad_pattern", "unreadable"},
            })
        history.append({"role": "user", "content": results})

    # 2026-09-07, caught on the first real standup: Claude made TWENTY-ONE lookups on a broad
    # opening question, hit the ceiling, and returned a canned apology. All that evidence was
    # gathered and then thrown away, which is worse than not looking at all -- it costs the
    # money and produces nothing.
    #
    # So the ceiling now means "stop looking", not "give up". One final call with NO TOOLS
    # offered, asking for the best answer from what was found. The model cannot request more
    # evidence, so it must either answer or say plainly what is still missing -- and either of
    # those is worth having.
    _progress(stage="summarising")
    history.append({
        "role": "user",
        "content": (
            "You have used all the lookups available for this turn. Do not ask for more. "
            "Answer now from what you have already found, and say plainly which part you could "
            "not establish and what would settle it."
        ),
    })
    try:
        final = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_blocks(system or SYSTEM_PROMPT),
            thinking={"type": "adaptive"},
            messages=_with_cache_breakpoint(history),
        )
        _add_usage(totals, final.usage)
        text = "".join(block.text for block in final.content if block.type == "text").strip()
    except Exception as exc:  # noqa: BLE001 - the fallback must never be worse than the failure
        logger.exception("Claude could not summarise after reaching the lookup limit.")
        text = ""
    return {
        # Two different stops, reported differently, because they mean different things to the
        # Founder: one says the question was too broad, the other says it was too expensive.
        "status": "answered_at_cost_limit" if stopped_on_cost else "answered_at_lookup_limit",
        "answer": text or (
            "I ran out of lookups before reaching an answer. That usually means the question "
            "needs narrowing, or that what I need is not in the code and data I can see."
        ),
        "tool_calls": tool_calls,
        "usage": _spent(),
    }
