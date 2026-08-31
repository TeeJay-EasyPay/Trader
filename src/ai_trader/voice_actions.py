"""The small set of things the Founder can ask AI Trader to DO, by voice or text.

2026-08-31, Founder-directed. He asked to interact with the app the way he interacts with
me, and chose "speak, plus run safe actions" -- explicitly not full control.

WHAT COUNTS AS SAFE, and the one honest caveat:

Nothing here moves a threshold, changes a guardrail, enables or disables trading, or places
an order directly. What running a cycle CAN do is place an order at the end of it, and that
deserves saying plainly rather than being filed under "safe": the cycle is the same one the
worker runs hourly on its own. Triggering it by voice changes WHEN it runs, not WHAT it is
allowed to do. Every gate -- confidence, the Shariah screen, fees, position limits -- applies
exactly as it would at 3am with nobody watching. So this adds no new authority, only timing.

Anything that would add authority (approve a trade, move the confidence bar, change the
allocation) is deliberately absent, and the fall-through below sends it to the read-only
answer instead of guessing.

WHY PHRASE MATCHING RATHER THAN AN LLM:

An LLM classifier would handle more phrasings, and would also occasionally decide that "what
happens if I run a cycle" is a request to run one. Voice makes commands casual -- half-formed
sentences, thinking out loud, background speech picked up by an open mic -- which is exactly
when a confident misreading is most likely. So an action fires only on an unambiguous
imperative, and everything else falls through to being answered rather than acted on. A
missed command costs a repeat; a hallucinated one spends real money's worth of API calls and,
at the end of a cycle, can transact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class VoiceAction:
    key: str
    # Spoken back before the work starts, so the Founder knows he was understood. Written to
    # be read ALOUD -- short, no jargon, no numbers he cannot hold in his head.
    acknowledgement: str
    run: Callable[[Any], dict[str, Any]]


def _run_cycle(service: Any, scope: str) -> dict[str, Any]:
    return service.start_cycle_from_voice(scope=scope)


# Ordered: the most specific patterns first, so "run a crypto cycle" is not swallowed by the
# general "run a cycle". Each pattern requires an imperative verb -- "run", "start", "check" --
# so a question ABOUT an action ("should I run a cycle?", "what does running a cycle do")
# does not trigger one.
_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(run|start|do|kick off|trigger)\b.{0,20}\b(crypto)\b.{0,15}\b(cycle|research|scan)\b", "cycle_crypto"),
    (r"\b(run|start|do|kick off|trigger)\b.{0,20}\b(cycle|research cycle|full cycle|everything)\b", "cycle_all"),
    (r"\b(check|verify|reconcile)\b.{0,25}\b(positions?|holdings?|what we (actually )?hold)\b", "reconcile"),
    (r"\brefresh\b.{0,25}\b(prices?|market|data|coins?)\b", "refresh"),
)


def detect_action(question: str) -> str | None:
    """The action key this sentence unambiguously asks for, or None to answer instead."""
    text = " ".join(str(question or "").lower().split())
    if not text:
        return None
    # A request rescues an otherwise question-shaped sentence: "can you run a cycle?" is a
    # real instruction and people say it constantly.
    if re.match(r"^(can|could|would|will) (you|we)\b|^please\b", text):
        pass
    # Otherwise this is a question if it is punctuated as one OR opens with an interrogative.
    #
    # The interrogative check is not belt-and-braces, it is the load-bearing half: Whisper
    # frequently returns speech without a question mark, so relying on punctuation alone let
    # "why did it not run a cycle" -- a question about the PAST -- start a new cycle. Voice
    # input is exactly where sentences arrive unpunctuated, which makes this the common case
    # rather than the edge one.
    elif text.endswith("?") or re.match(
        r"^(why|what|when|where|who|which|how|did|does|do|is|are|was|were|has|have|had|should|shall)\b",
        text,
    ):
        return None
    for pattern, key in _PATTERNS:
        if re.search(pattern, text):
            return key
    return None


def build_actions(service: Any) -> dict[str, VoiceAction]:
    return {
        "cycle_all": VoiceAction(
            key="cycle_all",
            acknowledgement="Starting a full cycle now. I'll check crypto and shares, and tell you what happens.",
            run=lambda svc: _run_cycle(svc, "all"),
        ),
        "cycle_crypto": VoiceAction(
            key="cycle_crypto",
            acknowledgement="Starting a crypto cycle now. It takes a few minutes.",
            run=lambda svc: _run_cycle(svc, "crypto"),
        ),
        "reconcile": VoiceAction(
            key="reconcile",
            acknowledgement="Checking what we actually hold against Kraken.",
            run=lambda svc: svc.reconcile_open_positions(broker="kraken"),
        ),
        "refresh": VoiceAction(
            key="refresh",
            acknowledgement="Refreshing prices and market data.",
            run=lambda svc: svc.refresh_crypto_candle_history(),
        ),
    }


def _describe_reconcile(result: dict[str, Any]) -> str:
    if result.get("status") == "skipped":
        return str(result.get("message") or "I could not read the balances, so nothing was changed.")
    closed = result.get("closed") or []
    kept = result.get("kept") or []
    if closed:
        names = ", ".join(str(c.get("symbol")) for c in closed[:3])
        return (f"I closed {len(closed)} position we do not actually hold, {names}. "
                f"{len(kept)} confirmed real.")
    if kept:
        return f"All {len(kept)} open positions are confirmed real. Nothing needed changing."
    return "There are no open positions to check."


def _describe_cycle(result: dict[str, Any]) -> str:
    if result.get("status") == "already_running":
        return "A cycle is already running, so I'll let that one finish rather than start another."
    return ("The cycle is running now. Open the Run a Cycle screen to watch each step, "
            "or ask me again in a few minutes and I'll tell you how it went.")


def run_action(service: Any, key: str) -> dict[str, Any]:
    """Execute one action and describe the outcome in a sentence meant to be heard.

    Never raises. A voice reply that ends in silence is indistinguishable from the app being
    broken, so a failure has to come back as a spoken sentence like anything else.
    """
    actions = build_actions(service)
    action = actions.get(key)
    if action is None:
        return {"status": "unknown_action", "answer": "I did not recognise that as something I can do."}
    try:
        outcome = action.run(service) or {}
    except Exception as exc:  # noqa: BLE001 - must always answer out loud
        return {
            "status": "failed",
            "action": key,
            "answer": f"I could not do that. {str(exc)[:160]}",
        }
    if key == "reconcile":
        spoken = _describe_reconcile(outcome)
    elif key.startswith("cycle"):
        spoken = _describe_cycle(outcome)
    else:
        spoken = "Done. Prices and market data are refreshed."
    return {
        "status": "action_taken",
        "action": key,
        "answer": f"{action.acknowledgement} {spoken}",
        "result": outcome,
    }
