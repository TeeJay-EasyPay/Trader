"""Why the AI said no -- Founder-requested 2026-08-20.

*"AIs decline reasoning should be available but in a short easy to understand answers."*

The reviewer has been actively changing real trading outcomes since Phase 5 shipped -- it
vetoes candidates that already cleared every mechanical gate, and it has done so on named
symbols on live production runs. But its reasoning was written to
`execution_events.payload_json` and exposed by NO endpoint, so the Founder could see that a
trade did not happen but never why. `/crypto-rejections-explained` gives the mechanical
reason (`duplicate_open_position`, `entry_too_extended`); this gives the judgment.

Deliberately short. The Founder asked for "short easy to understand answers", and this
screen already suffers from the opposite problem: the curated knowledge-base text is dumped
verbatim into every recommendation's reasoning, raw markdown and all, burying the sections
that actually matter. So the reviewer's reasoning is trimmed to its first sentence or two
and any raw markdown is stripped before it ever reaches the app.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect


# Only the outcomes where the AI's own judgment was the deciding factor. A trade blocked by
# a mechanical gate is already explained by /crypto-rejections-explained, and repeating it
# here would pad the card with things the reviewer never actually judged.
_JUDGMENT_REASONS = {
    "ai_review_declined": "Declined",
    "ai_review_lowered_confidence_below_minimum": "Not confident enough",
}

_MARKDOWN = re.compile(r"[*_`#>]+")
_WHITESPACE = re.compile(r"\s+")


def shorten(text: str, *, max_sentences: int = 2, max_chars: int = 170) -> str:
    """Trim reviewer prose to a couple of plain sentences with no raw markdown.

    Markdown is stripped rather than rendered because the mobile card shows plain Text --
    the existing recommendation cards display literal '###' and '**' to the Founder today,
    which is exactly the outcome this avoids.
    """
    cleaned = _WHITESPACE.sub(" ", _MARKDOWN.sub("", str(text or ""))).strip()
    if not cleaned:
        return ""
    # Split on sentence ends only, never on the decimal point in a figure like "0.75".
    parts = re.split(r"(?<!\d)(?<=[.!?])\s+", cleaned)
    kept = " ".join(parts[:max_sentences]).strip()
    if len(kept) > max_chars:
        # Cut at a word boundary, not mid-word. Plain "..." rather than the single-character
        # ellipsis: the payload crosses JSON, an HTTP layer and React Native Text, and a
        # non-ASCII character there is one more thing that can arrive mangled for no benefit.
        clipped = kept[:max_chars]
        space = clipped.rfind(" ")
        if space > max_chars // 2:
            clipped = clipped[:space]
        kept = clipped.rstrip(" ,;:.") + "..."
    return kept


def summarize_decline(payload: dict[str, Any]) -> dict[str, Any] | None:
    """One Founder-readable decline, or None when this event is not a judgment call."""
    if not isinstance(payload, dict):
        return None
    label = _JUDGMENT_REASONS.get(str(payload.get("reason") or ""))
    if label is None:
        return None
    review = payload.get("review")
    if not isinstance(review, dict):
        return None
    reasoning = shorten(review.get("reasoning"))
    if not reasoning:
        return None
    concerns = review.get("concerns")
    concern = ""
    if isinstance(concerns, list) and concerns:
        concern = shorten(concerns[0], max_sentences=1, max_chars=140)
    # For a DECLINE, the concern is the actual answer to "why not?". The reviewer's
    # reasoning field characteristically opens with the bullish case before pivoting, so
    # leading with it answers the opposite question -- live example: a declined BTC trade
    # whose reasoning began "strong momentum and a bullish bias" while the real reason,
    # "weekly trend weakness undermines daily bullish signals", sat in `concerns`.
    headline = concern or reasoning
    confidence = review.get("confidence")
    try:
        confidence_value = None if confidence is None else round(float(confidence), 2)
    except (TypeError, ValueError):
        confidence_value = None
    return {
        "symbol": str(payload.get("symbol") or "").upper() or None,
        "outcome": label,
        "why": headline,
        # Kept alongside so the fuller assessment is still available, but never the headline.
        "assessment": reasoning if concern else None,
        "main_concern": concern or None,
        "confidence": confidence_value,
    }


def recent_decline_reasons(db_path: Path, *, limit: int = 8) -> dict[str, Any]:
    """The most recent judgment-based declines, newest first.

    Reads more rows than it returns because most `agent_no_trade` events are mechanical
    gates, which are filtered out here. Any read failure returns an empty list rather than
    raising -- this powers a display card and must never break the briefing.
    """
    rows: list[Any] = []
    try:
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT created_at, payload_json
                FROM execution_events
                WHERE event_type = 'agent_no_trade'
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, int(limit)) * 25,),
            ).fetchall()
    except Exception:
        return {"declines": [], "available": False}
    declines: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        summary = summarize_decline(payload)
        if summary is None:
            continue
        summary["created_at"] = row["created_at"]
        declines.append(summary)
        if len(declines) >= limit:
            break
    return {"declines": declines, "available": True}
