"""The lock. This is the test that stops the whole problem coming back.

2026-09-02, P8 of the "one home per decision" work.

Everything before this was a fix. This is the part that keeps it fixed, and it exists because
of a specific, humbling fact: on 2026-09-01, WHILE fixing the duplicate-homes problem, I added
two brand-new homes for reward:risk without noticing. The habit that created the mess is not
cured by cleaning the mess. It needs a test that fails the build.

What it enforces:

  1. A trading decision is declared exactly once, in decision_registry.DECISIONS.
  2. Nothing outside the registry resolves one by reaching into the policy maps by hand.
  3. No rule is enforced in both guardrails.py and orchestrator.py.
  4. load_trading_policy resolves nothing itself -- it asks the registry.
  5. Every decision can say, in plain English, what it is and where it came from.

If one of these fails, read the failure before "fixing" the test. Each of them corresponds to
a real bug that reached production and cost a working session.
"""

from __future__ import annotations

import pathlib
import re

from ai_trader.decision_registry import CODE_DEFAULT, DECISIONS

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "ai_trader"
REGISTRY = SRC / "decision_registry.py"
FOUNDATION = SRC / "foundation.py"


def _code(path: pathlib.Path) -> list[str]:
    """Lines with comments stripped. The comments explain these very bugs by name, and a
    guard that trips on its own documentation is a guard someone deletes."""
    return [re.sub(r"#.*$", "", line) for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------
# 1. Declared once.
# --------------------------------------------------------------------------
def test_every_decision_is_declared_exactly_once():
    names = [d.name for d in DECISIONS]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"declared more than once: {sorted(duplicates)}"


def test_no_two_decisions_share_a_storage_key():
    """Two entries pointing at the same database row is the same bug wearing a disguise."""
    seen: dict[tuple[str, str], str] = {}
    clashes = []
    for d in DECISIONS:
        for kind, key in (("risk", d.risk_key), ("investment", d.investment_key), ("broker", d.broker_key)):
            if not key:
                continue
            # A broker override and a global default may legitimately share a name.
            slot = (kind, key)
            if slot in seen:
                clashes.append(f"{d.name} and {seen[slot]} both own {kind}:{key}")
            seen[slot] = d.name
    assert not clashes, clashes


# --------------------------------------------------------------------------
# 2. Nothing else resolves a decision.
# --------------------------------------------------------------------------
def test_only_the_registry_reaches_into_the_policy_maps():
    """The bug this whole project was about.

    Any module fetching a policy row by hand is a second home for that number, and the app
    then has two answers to the same question -- which is how raising Alpaca's position cap
    changed nothing, and how the confidence bar came to live in four places.
    """
    owned = {d.risk_key for d in DECISIONS if d.risk_key} | {
        d.investment_key for d in DECISIONS if d.investment_key
    }
    # Specifically the POLICY maps. An earlier version of this test looked for any `.get(`
    # near an owned key and flagged execution_service.py reading trailing_stop_pct off an
    # individual trade row -- which is the value recorded FOR that trade, not the policy
    # default, and entirely correct. A guard that cries wolf gets deleted, so it is narrow.
    policy_read = re.compile(r"(?:risk|investment|policies\[.risk.\]|policies\[.investment.\])\.get\(\s*[\"']([a-z_0-9]+)")
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if path.name == "decision_registry.py":
            continue
        for number, line in enumerate(_code(path), 1):
            for key in policy_read.findall(line):
                if key in owned:
                    offenders.append(f"{path.name}:{number} resolves {key} by hand")
    assert not offenders, "a decision is being resolved outside the registry:\n  " + "\n  ".join(offenders)


def test_load_trading_policy_asks_the_registry_for_everything():
    """It used to hold 23 hand-written expressions in three different resolution styles."""
    body = FOUNDATION.read_text(encoding="utf-8")
    start = body.index("    return TradingPolicy(")
    constructor = body[start:body.index("\n    )", start)]
    stripped = "\n".join(re.sub(r"#.*$", "", line) for line in constructor.splitlines())
    owned = {d.risk_key for d in DECISIONS if d.risk_key} | {
        d.investment_key for d in DECISIONS if d.investment_key
    }
    # Scoped to the keys the registry owns. crypto_enabled and equities_enabled are feature
    # switches rather than trading numbers, are deliberately not registry decisions, and are
    # read here on purpose -- a blanket ban would be a rule nobody could satisfy, and those
    # get deleted rather than obeyed.
    resolved_by_hand = sorted(k for k in owned if f'.get("{k}"' in stripped)
    assert not resolved_by_hand, (
        f"load_trading_policy resolves these itself instead of via _decided(): {resolved_by_hand}"
    )


# --------------------------------------------------------------------------
# 3. Enforced once.
# --------------------------------------------------------------------------
def test_no_rule_is_enforced_in_two_files():
    """51 of 77 live refusals were once a single rule counted twice under two names."""
    def gates(path):
        return {m for line in _code(path) for m in re.findall(r'failures\.append\("([a-z_0-9]+)"\)', line)}

    both = gates(SRC / "guardrails.py") & gates(SRC / "orchestrator.py")
    assert not both, f"enforced in both files: {sorted(both)}"


def test_exactly_one_place_compares_open_positions_to_a_cap():
    pattern = re.compile(r"len\(\s*[\w.]*\.?open_positions\s*\)\s*>=")
    hits = [f"{p.name}:{n}" for p in SRC.rglob("*.py")
            for n, line in enumerate(_code(p), 1) if pattern.search(line)]
    assert len(hits) == 1, f"expected one position-cap comparison, found: {hits}"


# --------------------------------------------------------------------------
# 4. Readable by the person who owns the money.
# --------------------------------------------------------------------------
def test_every_decision_explains_itself_in_plain_english():
    """These are shown to the Founder, who is not an engineer."""
    for d in DECISIONS:
        assert d.summary.endswith("."), f"{d.name}: summary must be a sentence"
        assert "_" not in d.summary, f"{d.name}: summary reads like a variable name"
        assert len(d.summary) > 25, f"{d.name}: summary is too thin to be useful"


def test_every_decision_can_always_produce_an_answer():
    for d in DECISIONS:
        assert d.precedence[-1] == CODE_DEFAULT, f"{d.name} could resolve to nothing"
        assert d.default is not None, f"{d.name} has no default"


def test_every_decision_declares_where_it_should_live():
    from ai_trader.decision_registry import IN_DATABASE, IN_RENDER

    for d in DECISIONS:
        assert d.belongs_in in (IN_DATABASE, IN_RENDER), f"{d.name}: {d.belongs_in!r}"
