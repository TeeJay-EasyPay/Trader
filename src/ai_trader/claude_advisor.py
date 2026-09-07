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
from typing import Any

from .evidence_tools import TOOL_SPECS, run_tool

logger = logging.getLogger("ai_trader.api")

MODEL = "claude-opus-5"

# A conversational turn should not run away. Each iteration is a model call plus its tool
# results, so this bounds both the wait and the bill; hitting it is reported rather than
# hidden, because a truncated investigation presented as a finished one is the failure mode
# this whole file exists to prevent.
MAX_TOOL_ITERATIONS = 12
MAX_TOKENS = 8000

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


def _client() -> Any:
    import anthropic

    return anthropic.Anthropic()


def _tool_definitions() -> list[dict[str, Any]]:
    """The evidence tools, in the Messages API shape.

    Built from the same TOOL_SPECS the dispatcher uses, so a description can never advertise a
    tool that does not exist or promise behaviour the function does not have.
    """

    return [
        {"name": spec["name"], "description": spec["description"], "input_schema": spec["input_schema"]}
        for spec in TOOL_SPECS
    ]


def ask_claude(
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    db_path: Path | None = None,
    max_iterations: int = MAX_TOOL_ITERATIONS,
) -> dict[str, Any]:
    """One Claude turn, with tool use resolved before returning.

    `messages` is the conversation so far in Messages API shape. The caller owns the history --
    including the trader's contributions, which are passed in as user-role context so Claude can
    respond to them. That is what lets the two of them actually talk to each other rather than
    answering the Founder in parallel.

    Returns the text, plus the tool calls made. The tool calls are returned rather than only
    logged so the Founder can see WHAT WAS CHECKED, which is the difference between trusting the
    answer and being able to audit it.
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

    for iteration in range(max(1, int(max_iterations))):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system or SYSTEM_PROMPT,
                # Adaptive thinking: this is judgement work over real evidence, not lookup.
                thinking={"type": "adaptive"},
                tools=_tool_definitions(),
                messages=history,
            )
        except anthropic.AuthenticationError:
            return {"status": "auth_failed", "answer": "The Anthropic API key was rejected.", "tool_calls": tool_calls}
        except anthropic.BadRequestError as exc:
            # Includes "credit balance is too low", which is the Founder's problem to fix and
            # must say so plainly rather than surfacing as a generic failure.
            return {"status": "rejected", "answer": f"Anthropic rejected the request: {exc}", "tool_calls": tool_calls}
        except Exception as exc:  # noqa: BLE001 - a failed turn must not end the standup
            logger.exception("Claude turn failed.")
            return {"status": "failed", "answer": f"Claude could not answer: {type(exc).__name__}", "tool_calls": tool_calls}

        if response.stop_reason != "tool_use":
            text = "".join(block.text for block in response.content if block.type == "text")
            return {
                "status": "answered",
                "answer": text.strip(),
                "tool_calls": tool_calls,
                "model": response.model,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            }

        # Claude wants evidence. Run every requested tool and return ALL results in ONE user
        # message -- splitting them across messages teaches the model to stop asking for things
        # in parallel, which would make every investigation slower and dearer.
        history.append({"role": "assistant", "content": response.content})
        results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            outcome = run_tool(block.name, dict(block.input or {}))
            tool_calls.append({"tool": block.name, "input": dict(block.input or {}),
                               "status": outcome.get("status")})
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(outcome, default=str)[:20000],
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
            system=system or SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            messages=history,
        )
        text = "".join(block.text for block in final.content if block.type == "text").strip()
    except Exception as exc:  # noqa: BLE001 - the fallback must never be worse than the failure
        logger.exception("Claude could not summarise after reaching the lookup limit.")
        text = ""
    return {
        "status": "answered_at_lookup_limit",
        "answer": text or (
            "I ran out of lookups before reaching an answer. That usually means the question "
            "needs narrowing, or that what I need is not in the code and data I can see."
        ),
        "tool_calls": tool_calls,
    }
