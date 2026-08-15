"""Local curated trading-knowledge library: retrieval over knowledge/*.md.

Phase B of the external-intelligence work (see external_intelligence.py for
Phase A). A trade proposal's asset type/sector determines what gets pulled at
call time -- no manual curation per trade, matching the Founder's explicit
requirement that this run automatically.

The library itself (knowledge/ at the repo root) is a living document, not a
one-time seed: relevant_excerpts logs a "coverage gap" via record_knowledge_gap
whenever nothing matches a real trade's asset type/sector/topics, so future
additions are driven by evidence of what is actually missing rather than
guessed. This module is retrieval only (tag/keyword matching); no
embeddings/vector search in this phase -- see relevant_excerpts's docstring
for why that is a deliberate, revisitable choice, not an oversight.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .sprint6 import record_operational_event

# 2026-08-15 incident: computing this as "three directories above this file" only
# resolves correctly for an editable/source-tree install (this repo's own .venv).
# A real `pip install .` (Dockerfile's actual production install) copies this file
# into site-packages, at which point the same relative computation lands somewhere
# under the Python installation itself, nowhere near the repo's knowledge/ folder --
# confirmed by simulating a real non-editable install. AI_TRADER_KNOWLEDGE_DIR
# matches this codebase's existing pattern for AI_TRADER_DB_PATH/AI_TRADER_OUTPUT_DIR
# (explicit Dockerfile ENV, not fragile path inference) and is authoritative in
# production; the relative computation remains only as the local-dev fallback.
KNOWLEDGE_DIR = Path(os.getenv("AI_TRADER_KNOWLEDGE_DIR") or (Path(__file__).resolve().parent.parent.parent / "knowledge"))


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Dependency-free parser for this module's small, deliberately-constrained
    frontmatter dialect: `key: value` and `key: [a, b, c]` list syntax only,
    delimited by a leading/trailing `---` line. PyYAML is not a dependency of
    this codebase (confirmed: not importable, not listed anywhere) and this
    codebase's convention is to avoid adding a new one where the actual need
    is this narrow -- a handful of scalar/list frontmatter fields, not
    general YAML.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    frontmatter: dict[str, Any] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value.startswith("[") and raw_value.endswith("]"):
            inner = raw_value[1:-1].strip()
            items = [item.strip().strip('"').strip("'") for item in inner.split(",")] if inner else []
            frontmatter[key] = [item for item in items if item]
        else:
            frontmatter[key] = raw_value.strip('"').strip("'")
    body = "\n".join(lines[end + 1 :]).strip()
    return frontmatter, body


def load_knowledge_index(path: Path = KNOWLEDGE_DIR) -> list[dict[str, Any]]:
    """Scan `path` for *.md files and parse each into an index entry:
    {title, topics, applies_to, sectors, excerpt, file_path}. Files with no
    parseable frontmatter are skipped (not raised) so one malformed file
    cannot take the whole knowledge base down -- matching this codebase's
    established partial-failure isolation convention.
    """
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for file_path in sorted(path.glob("*.md")):
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, body = _parse_frontmatter(text)
        if not frontmatter:
            continue
        applies_to = frontmatter.get("applies_to") or []
        if isinstance(applies_to, str):
            applies_to = [applies_to]
        topics = frontmatter.get("topics") or []
        if isinstance(topics, str):
            topics = [topics]
        sectors = frontmatter.get("sectors") or []
        if isinstance(sectors, str):
            sectors = [sectors]
        entries.append(
            {
                "title": frontmatter.get("title") or file_path.stem,
                "topics": [str(item).lower() for item in topics],
                "applies_to": [str(item).lower() for item in applies_to],
                "sectors": [str(item).lower() for item in sectors],
                "excerpt": body,
                "file_path": str(file_path),
            }
        )
    return entries


def relevant_excerpts(
    *,
    asset_type: str,
    sector: str | None = None,
    topics: list[str] | None = None,
    limit: int = 5,
    index: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return up to `limit` knowledge entries relevant to a real trade's
    asset type/sector/topics, most-relevant-first.

    Matching is tag/keyword-based, not semantic search -- deliberate for this
    phase: at the scale of a curated library (tens to low hundreds of files),
    exact tag matching is precise and needs no extra infrastructure. If the
    library grows into the thousands of files, exact-tag matching will start
    missing relevant material phrased/tagged differently than the query, and
    embeddings-based semantic search should replace this function's body --
    this function's signature (asset_type/sector/topics/limit in, ranked
    excerpts out) is designed so that swap would not require changing any
    caller.

    A file is eligible only if `asset_type` (case-insensitive) appears in its
    `applies_to`. Among eligible files, sector match and topic overlap both
    add to a relevance score (sector match counts more, since a sector-tagged
    file that matches is a stronger signal than an incidental topic overlap);
    broadly-applicable files (empty `sectors`) are always eligible regardless
    of the queried sector, since an empty `sectors` list means "not
    sector-specific," not "matches no sector."
    """
    entries = index if index is not None else load_knowledge_index()
    asset_type_normalized = (asset_type or "").strip().lower()
    sector_normalized = (sector or "").strip().lower() if sector else None
    topics_normalized = {str(topic).strip().lower() for topic in (topics or [])}

    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        if asset_type_normalized not in entry["applies_to"]:
            continue
        # A sector-specific file that does not match the queried sector stays
        # eligible (it is not excluded), it is simply not boosted below -- an
        # empty `sectors` list means "not sector-specific" (always eligible);
        # a non-matching `sectors` list means "specific to a different
        # sector," which is still broadly relevant, just less targeted.
        entry_sectors = entry["sectors"]
        score = 0.0
        if entry_sectors and sector_normalized and sector_normalized in entry_sectors:
            score += 2.0
        if topics_normalized:
            score += len(topics_normalized.intersection(entry["topics"]))
        scored.append((score, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored[: max(1, int(limit))]]


def record_knowledge_gap(
    db_path: Path,
    *,
    asset_type: str,
    sector: str | None,
    topics_searched: list[str] | None,
) -> None:
    """Log a coverage gap when relevant_excerpts finds nothing for a real
    trade's asset type/sector/topics, so future knowledge-base additions are
    driven by evidence of what is actually missing (a concrete, queryable
    worklist) rather than guessed.
    """
    record_operational_event(
        db_path,
        component="knowledge_base",
        event_type="knowledge_gap",
        severity="info",
        success=True,
        summary=f"No relevant knowledge-base entries for asset_type={asset_type!r} sector={sector!r}.",
        details={"asset_type": asset_type, "sector": sector, "topics_searched": topics_searched or []},
    )
