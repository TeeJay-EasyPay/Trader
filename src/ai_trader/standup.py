"""Who speaks next in a three-way standup, and when the two AIs stop talking to each other.

2026-09-07, Founder-directed:

  "the conversation should basically be free flowing.... there may be times I explore a topic
   or item in the conversation with Claude for example while chatgpt listens after which it
   also joins in if asked and likewise for me with chatgpt"
  "yes but also happy for Claude and chatgpt to speak to each other as well"

Two participants, one chair. The trader knows what the account is doing; Claude can read the
code and the database. The Founder directs, and can interrupt.

Only the DECISIONS live here -- who is being addressed, whether the other should reply, when an
exchange has run long enough. They are pure functions so they can be tested without spending
money on a model call, which is the same reason lib/spokenReply.js exists on the mobile side.

THE RULE THAT MATTERS MOST is the exchange budget. Two agreeable models will happily ping-pong
("Good point." "Yes, and building on that...") until someone stops them, and every turn is a
real bill. So an exchange between the two is bounded, and the floor returns to the Founder.
"""

from __future__ import annotations

import re
from typing import Any

CLAUDE = "claude"
TRADER = "trader"
BOTH = "both"

# How many AI turns one Founder message may produce before the floor returns to him. Four is
# two each: enough to disagree and answer the disagreement, not enough to hold a seminar.
DEFAULT_EXCHANGE_BUDGET = 4

# What each participant answers to. "gpt" and "chatgpt" are the Founder's own words for the
# trading AI; "trader" is what the system calls it. All of them route to the same place, because
# a router that is fussy about names is a router that drops half the conversation.
_NAMES: tuple[tuple[str, str], ...] = (
    (CLAUDE, r"claude"),
    (TRADER, r"chat\s*gpt|chatgpt|gpt|the\s+trader|trader"),
)


def _named_in(text: str, pattern: str) -> re.Match[str] | None:
    return re.search(r"\b(?:" + pattern + r")\b", text, re.IGNORECASE)


def detect_addressee(
    text: str,
    *,
    mode: str = BOTH,
    last_ai_speaker: str | None = None,
) -> str:
    """Who the Founder is talking to.

    A leading vocative wins outright -- "Claude, why is that slow?" is unambiguous and is how
    people actually address someone in a room.

    Otherwise, exactly one name mentioned anywhere routes to that one. This is what lets him
    explore a topic with one while the other listens: "what did the trader mean by that?" is a
    question FOR Claude that happens to mention the trader... which the vocative check above
    already handled, and which is why the vocative is checked first and separately.

    Naming both, or neither, goes to whoever was last speaking -- conversations have
    continuity, and asking both to answer every unaddressed remark doubles the noise and the
    bill. With nobody yet speaking, it opens to both.
    """

    said = " ".join(str(text or "").split())
    if mode in (CLAUDE, TRADER):
        return mode  # a one-to-one conversation has nobody else to route to
    if not said:
        return last_ai_speaker or BOTH

    for who, pattern in _NAMES:
        if re.match(r"^\s*(?:hey\s+|ok\s+|okay\s+|so\s+)?(?:" + pattern + r")\b\s*[,:!?-]", said, re.IGNORECASE):
            return who

    mentioned = [who for who, pattern in _NAMES if _named_in(said, pattern)]
    if len(mentioned) == 1:
        return mentioned[0]
    return last_ai_speaker or BOTH


def should_reply_to_peer(
    *,
    mode: str,
    turns_used: int,
    budget: int = DEFAULT_EXCHANGE_BUDGET,
    peer_said_something: bool,
) -> bool:
    """Whether the other AI gets to answer what its counterpart just said.

    Only in a standup -- a one-to-one conversation has no peer. Only when the peer actually
    said something. And only while the budget holds, because the failure mode here is not a
    wrong answer, it is two models being endlessly agreeable at a pound a go while the Founder
    watches.
    """

    if mode != BOTH:
        return False
    if not peer_said_something:
        return False
    return turns_used < max(0, int(budget))


def other_speaker(speaker: str) -> str:
    return TRADER if speaker == CLAUDE else CLAUDE


# Given to both participants during a standup. The stop rule is the important half: without it
# a model asked "anything to add?" will always find something to add.
PEER_EXCHANGE_INSTRUCTION = (
    "You are in a standup with the Founder and the other AI. You have just been shown what the "
    "other one said.\n\n"
    "Reply ONLY if you have something substantive: evidence that supports it, evidence that "
    "contradicts it, or a specific question that would settle a disagreement. Check before you "
    "contradict -- you have read-only tools, use them.\n\n"
    "If you agree, say so in one line and stop. Do not restate their point back to them, do not "
    "add colour, and do not find something to add for the sake of replying. A short "
    "'agreed, and my check confirms it' is a good turn. Silence dressed up as contribution "
    "wastes the Founder's time and his money."
)


def transcript_for(speaker: str, turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The conversation as one participant should see it.

    BOTH participants see everything, including each other's answers -- that is what lets one
    listen while the other is being explored, and join in later with the context to be useful.
    What differs is only WHOSE VOICE is whose: a participant's own turns are its assistant
    turns, and everything else arrives as user-role context, labelled.

    Labelling matters. Without it a model reads the peer's answer as its own earlier words and
    agrees with itself.
    """

    out: list[dict[str, Any]] = []
    for turn in turns:
        role = str(turn.get("speaker") or "")
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        if role == speaker:
            out.append({"role": "assistant", "content": text})
        elif role == "founder":
            out.append({"role": "user", "content": text})
        else:
            label = "The trader said" if role == TRADER else "Claude said"
            out.append({"role": "user", "content": f"[{label}]\n{text}"})
    return _merge_adjacent(out)


def _merge_adjacent(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold consecutive same-role messages into one.

    The Messages API accepts consecutive user turns, but two separate ones read as two separate
    remarks. Merging keeps "the Founder asked X" and "the trader answered Y" as the single piece
    of context they actually are.
    """

    merged: list[dict[str, Any]] = []
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1] = {"role": message["role"], "content": merged[-1]["content"] + "\n\n" + message["content"]}
            continue
        merged.append(dict(message))
    return merged
