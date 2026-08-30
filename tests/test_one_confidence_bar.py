"""One confidence bar, one place, for every broker and every stage.

Founder, 2026-08-29: "isn't it silly that we have confidence scores in 3 separate places?
everytime we make an adjustment to it we have to change it in 3 separate places. this
complicates things even further if we add more exchanges for both crypto or shares."

That work collapsed the orchestrator's four checks into two. It MISSED the third place --
the crypto research gate, which reads its bar straight from the AUTO_TRADE_MIN_CONFIDENCE
environment variable. That gate is the one that matters most, because it runs BEFORE a
proposal exists: an idea killed there is never seen by the orchestrator, never recorded as a
rejection, and never explainable in the app.

It stayed hidden because CRYPTO_RESEARCH_SCORES returned a hardcoded 0.850 for every coin
every hour until 27 August, and 0.850 clears a 0.85 bar. Once scoring became real the bar
became a blockade: of 1,508 readings in the following days exactly ONE cleared 0.85, against
246 at the 0.70 the Founder had chosen and the app was displaying.

Confirmed live 2026-08-30: SOL scored 0.7137 with a 0.7701 trend -- above the displayed bar
on both counts -- and was dropped anyway, which is the contradiction the Founder spotted in
his own run log ("2 coins cleared the checks but no trades reached the checks").
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "ai_trader"


def test_crypto_research_takes_its_bar_from_the_policy_not_an_env_var():
    """The exact regression: the research gate must read the one stored value."""
    text = (SOURCE / "application" / "research_service.py").read_text(encoding="utf-8")
    call = re.search(r"propose_crypto_trades\((.*?)\n        \)", text, re.DOTALL)
    assert call, "could not locate the propose_crypto_trades call"
    body = call.group(1)
    # Strip comments so the explanation of the old bug does not match as if it were code.
    code = "\n".join(re.sub(r"#.*$", "", line) for line in body.splitlines())

    assert "min_confidence=load_trading_policy(" in code, (
        "crypto research must take min_confidence from load_trading_policy, so the Founder's "
        "single stored bar applies to it like everything else"
    )
    assert "settings.auto_trade.min_confidence" not in code, (
        "the AUTO_TRADE_MIN_CONFIDENCE env var must not gate crypto research again -- it is "
        "set to 0.85 in render.yaml and silently blocked every coin once scoring became real"
    )


def test_no_other_caller_reintroduces_a_second_confidence_bar():
    """Guards the whole package, not just the one call site fixed today.

    A new broker added next month is exactly how a fourth copy of this number appears, and
    the Founder specifically asked that adding exchanges not multiply the places to change.
    """
    offenders: list[str] = []
    for path in SOURCE.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = re.sub(r"#.*$", "", line)
            if "min_confidence=" not in stripped:
                continue
            if "auto_trade.min_confidence" in stripped:
                offenders.append(f"{path.relative_to(SOURCE)}:{number}: {line.strip()[:90]}")
    assert offenders == [], (
        "min_confidence must come from load_trading_policy (the single stored bar), not from "
        f"settings.auto_trade: {offenders}"
    )


def test_the_policy_default_is_the_number_the_founder_chose():
    """foundation's seeded default and the live policy row must not drift apart silently."""
    text = (SOURCE / "foundation.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    found: float | None = None
    for node in ast.walk(tree):
        # DEFAULT_INVESTMENT_POLICIES carries a type annotation, so it parses as AnnAssign
        # rather than Assign -- handle both, or this silently finds nothing and the guard
        # quietly stops guarding.
        if isinstance(node, ast.AnnAssign):
            targets = [node.target.id] if isinstance(node.target, ast.Name) else []
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        else:
            continue
        if "DEFAULT_INVESTMENT_POLICIES" not in targets or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if getattr(key, "value", None) == "minimum_overall_confidence":
                found = value.elts[0].value
    assert found == 0.70, (
        f"the seeded confidence bar is {found}; the Founder chose 0.70 on 2026-08-29 after "
        "being shown the calibration data. Changing it needs his decision, not a code edit."
    )


def test_proposal_validation_uses_the_policy_bar_not_min_confidence_score_env():
    """The FOURTH home, found live on 2026-08-30.

    GRT was proposed at ai_confidence 0.7177 -- above the Founder's 0.70 -- and immediately
    failed validate_trade_proposal with ['confidence_below_minimum'], because
    GuardrailConfig.min_confidence_score comes from MIN_CONFIDENCE_SCORE, a separate Render
    variable set to 0.85. The Founder had named that variable to me himself three days
    earlier and I still left it behind when consolidating.
    """
    text = (SOURCE / "application" / "research_service.py").read_text(encoding="utf-8")
    call = re.search(r"propose_crypto_trades\((.*?)\n        \)", text, re.DOTALL)
    assert call, "could not locate the propose_crypto_trades call"
    code = "\n".join(re.sub(r"#.*$", "", line) for line in call.group(1).splitlines())

    assert "policy_aligned_guardrails(" in code, (
        "crypto proposals must be validated against the one stored bar, not "
        "MIN_CONFIDENCE_SCORE -- see foundation.policy_aligned_guardrails"
    )
    assert not re.search(r"^\s*self\.settings\.guardrails,\s*$", code, re.MULTILINE), (
        "the raw settings guardrails carry MIN_CONFIDENCE_SCORE (0.85) and will fail a "
        "proposal that cleared the Founder's own bar"
    )
