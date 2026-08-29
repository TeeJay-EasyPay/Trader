"""Which businesses the Founder is willing to own, checked rather than assumed.

2026-08-29, Founder-directed. Until now the Shariah screen existed only as a curated list of 50
companies chosen by hand on 2 July, enforced by accident: a company absent from that list has no
philosophy-fit rating, keeps TradeProposal's 0.0 default, and so can never clear the permission
gate. That works, but it is fragile and it does not scale -- "keeping fifty as a list that's
static and never changes is not really a good long term strategy... there could be thousands."

This module states the rule the list was built from, so the universe can grow without losing the
screen. Seven excluded activities, Founder-specified:

    alcohol, tobacco, gambling, conventional banking and insurance, pork,
    adult entertainment, military and defence

Two deliberate design choices.

FIRST, this screens the BUSINESS ACTIVITY only. The other half of a standard Shariah screen is
financial: debt, interest-bearing cash and non-compliant income as a share of market value
(AAOIFI Shari'ah Standard 21 sets the criteria; it publishes no approved-company list, so those
ratios have to be computed from filings). That is a separate piece of work and this module makes
no claim to cover it.

SECOND, and more important: an uncertain answer is never treated as a pass. A company matching a
clear activity signal is EXCLUDED. A company with a weak or ambiguous signal is REFERRED, not
admitted, because the cost of wrongly admitting a company the Founder did not want to own is
much higher than the cost of him reviewing one by hand. Only a clean company is admitted
automatically.

That asymmetry matters most for defence. Many ordinary industrials have some military revenue --
a semiconductor maker whose chips end up in defence systems is not a weapons company, but a
keyword match would call it one. So "defence" as a PRIMARY business excludes; an incidental
mention refers for review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

EXCLUDED = "excluded"
REFERRED = "referred"
PERMITTED = "permitted"


@dataclass(frozen=True)
class ScreenResult:
    verdict: str          # "excluded" | "referred" | "permitted"
    category: str | None  # which excluded activity, when one matched
    reason: str

    @property
    def tradeable(self) -> bool:
        """Only a clean pass is tradeable. Referred means a person decides, not the app."""
        return self.verdict == PERMITTED

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "category": self.category, "reason": self.reason}


# Phrases that identify the activity as what the company primarily DOES. Matched against the
# sector and industry classification, which describe a company's main line of business.
_PRIMARY_SIGNALS: dict[str, tuple[str, ...]] = {
    "alcohol": ("brewer", "brewing", "distiller", "distilling", "winery", "wine", "spirits",
                "alcoholic beverage", "beer", "liquor"),
    "tobacco": ("tobacco", "cigarette", "cigar", "vaping", "e-cigarette", "smokeless"),
    "gambling": ("casino", "gambling", "gaming and leisure", "betting", "wagering", "lottery",
                 "sports betting", "bookmaker"),
    "conventional_finance": ("bank", "banking", "consumer finance", "mortgage finance",
                             "insurance", "reinsurance", "consumer lending", "credit services",
                             "savings and loan", "thrift"),
    "pork": ("pork", "swine", "hog", "bacon"),
    "adult": ("adult entertainment", "pornograph", "adult content"),
    # 2026-08-29 Founder addition. Primary-business signals only -- see the module docstring on
    # why an incidental mention must not exclude.
    "defence": ("defense", "defence", "aerospace and defense", "aerospace and defence",
                "weapons", "armaments", "munitions", "firearms", "military vehicles",
                "missile", "ordnance", "arms manufacturer"),
}

# Weaker signals: a mention in free text suggests exposure without establishing it as the main
# business. These refer for review rather than excluding.
_SECONDARY_SIGNALS: dict[str, tuple[str, ...]] = {
    "alcohol": ("alcohol",),
    "gambling": ("gaming",),
    "conventional_finance": ("interest income", "lending", "credit card"),
    "defence": ("military", "defense contract", "defence contract", "army", "navy", "warfare"),
    "adult": ("adult",),
}

# Terms that mean the same thing wherever they appear -- no innocent reading -- so they exclude
# on a business-description match too, not merely refer. Kept deliberately narrow: anything with
# a plausible non-excluded meaning ("gaming", "military") belongs in _SECONDARY_SIGNALS instead.
_UNAMBIGUOUS_ANYWHERE: dict[str, tuple[str, ...]] = {
    "alcohol": ("brewery", "distillery", "winery", "spirits producer", "alcoholic beverage"),
    "tobacco": ("tobacco", "cigarette", "cigar"),
    "gambling": ("casino", "sports betting", "bookmaker", "wagering"),
    "pork": ("pork", "swine", "hog production", "bacon"),
    "adult": ("pornograph", "adult entertainment"),
}

_HUMAN_LABEL = {
    "alcohol": "alcohol",
    "tobacco": "tobacco",
    "gambling": "gambling",
    "conventional_finance": "conventional banking or insurance",
    "pork": "pork",
    "adult": "adult entertainment",
    "defence": "military or defence",
}


def _normalise(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def _matches(haystack: str, needles: tuple[str, ...]) -> str | None:
    for needle in needles:
        # Word-boundary matched so "bank" does not fire inside unrelated words, but a trailing
        # plural or gerund is allowed: real classifications read "Distillers and Vintners",
        # "Casinos and Gaming", "Brewers". Tested live -- without this, Diageo and Flutter both
        # came back permitted, which is exactly the failure this screen exists to prevent.
        if re.search(rf"(?<![a-z]){re.escape(needle)}(?:s|es|ing|ers)?(?![a-z])", haystack):
            return needle
    return None


def screen_business_activity(
    *,
    company_name: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    business_summary: str | None = None,
) -> ScreenResult:
    """Judge one company against the Founder's excluded activities.

    Classification (sector/industry) carries the primary-business test because that is what it
    describes. The free-text summary can only refer for review -- it mentions what a company
    touches, not what it is.
    """
    classification = _normalise(sector, industry, company_name)
    narrative = _normalise(business_summary)

    for category, needles in _PRIMARY_SIGNALS.items():
        hit = _matches(classification, needles)
        if hit:
            return ScreenResult(
                verdict=EXCLUDED,
                category=category,
                reason=f"Classified as {_HUMAN_LABEL[category]} ('{hit}' in its sector or industry).",
            )

    # Some activities are unmistakable wherever they appear: a company describing itself as a
    # pork processor is one, whatever its sector says. Tested live -- Smithfield Foods is
    # classified only as "Packaged Foods" and passed the classification test cleanly, which is
    # precisely the case this screen exists to catch. These words carry no innocent reading, so
    # a match in the business description excludes rather than refers.
    for category, needles in _UNAMBIGUOUS_ANYWHERE.items():
        hit = _matches(narrative, needles)
        if hit:
            return ScreenResult(
                verdict=EXCLUDED,
                category=category,
                reason=f"Describes itself as {_HUMAN_LABEL[category]} ('{hit}' in its business "
                       f"description), even though its sector classification does not say so.",
            )

    if not classification.strip():
        return ScreenResult(
            verdict=REFERRED,
            category=None,
            reason="No sector or industry recorded, so the business could not be screened. "
                   "Referred for review rather than admitted.",
        )

    for category, needles in _SECONDARY_SIGNALS.items():
        hit = _matches(narrative, needles)
        if hit:
            return ScreenResult(
                verdict=REFERRED,
                category=category,
                reason=f"Possible {_HUMAN_LABEL[category]} exposure ('{hit}' in its business "
                       f"description) without it being the primary business. Needs a human decision.",
            )

    return ScreenResult(
        verdict=PERMITTED,
        category=None,
        reason="No excluded business activity found in its classification or description.",
    )


def screen_many(companies: list[dict[str, Any]]) -> dict[str, ScreenResult]:
    """Screen a batch, keyed by ticker."""
    out: dict[str, ScreenResult] = {}
    for company in companies or []:
        ticker = str(company.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        out[ticker] = screen_business_activity(
            company_name=company.get("company_name"),
            sector=company.get("sector"),
            industry=company.get("industry"),
            business_summary=company.get("business_summary"),
        )
    return out
