from __future__ import annotations

import json
from pathlib import Path

from .models import TradeProposal


def save_proposals(path: Path, proposals: list[TradeProposal]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([proposal.to_dict() for proposal in proposals], indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_proposals(path: Path) -> list[TradeProposal]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Proposal file must contain a JSON list")
    return [TradeProposal.from_dict(item) for item in raw]

