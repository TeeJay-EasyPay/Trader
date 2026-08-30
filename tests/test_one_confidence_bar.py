"""One confidence bar, and Render owns it.

Founder, 2026-08-29: "isn't it silly that we have confidence scores in 3 separate places?
everytime we make an adjustment to it we have to change it in 3 separate places."

Founder, 2026-08-30, after being shown where it actually lived: Render wins. He manages
MIN_CONFIDENCE_SCORE in the dashboard, and that value must be the one every gate applies.

What was really running before this (checked against the Render API, not render.yaml):

    MIN_CONFIDENCE_SCORE        = 0.75   on both services
    AUTO_TRADE_MIN_CONFIDENCE   = not set on either service -> silent code default of 0.75
    INVESTMENT_POLICIES row     = 0.70   set from the app, and read FIRST by load_trading_policy

Three sources, two of them invisible from any dashboard, and whichever one someone edited at
least one of the others disagreed. render.yaml said 0.85 for MIN_CONFIDENCE_SCORE and
declared AUTO_TRADE_MIN_CONFIDENCE -- neither true of the running services, which is exactly
how a written summary of this came to be wrong.

Now: config reads MIN_CONFIDENCE_SCORE once, load_trading_policy derives min_ai_confidence
from it, and every gate reaches its bar through one of those two.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "ai_trader"


def test_the_policy_bar_is_derived_from_the_render_variable_not_the_database():
    """load_trading_policy is the single funnel every gate reaches its bar through."""
    text = (SOURCE / "foundation.py").read_text(encoding="utf-8")
    match = re.search(r"min_ai_confidence=([^\n]+)", text)
    assert match, "could not find min_ai_confidence in load_trading_policy"
    expression = match.group(1)
    assert "guardrails" in expression and "min_confidence_score" in expression, (
        f"min_ai_confidence must derive from the Render variable, got: {expression.strip()}"
    )
    assert "minimum_overall_confidence" not in expression, (
        "the database row must not be a source again -- the Founder chose Render as "
        "authoritative on 2026-08-30"
    )


def test_no_second_environment_variable_feeds_the_confidence_bar():
    """AUTO_TRADE_MIN_CONFIDENCE is set on neither Render service.

    Reading it meant falling through to a code default nobody could see in any dashboard --
    an invisible second source for a number the Founder was actively managing elsewhere.
    """
    text = (SOURCE / "config.py").read_text(encoding="utf-8")
    code = "\n".join(re.sub(r"#.*$", "", line) for line in text.splitlines())
    assert "AUTO_TRADE_MIN_CONFIDENCE" not in code, (
        "min_confidence must come from MIN_CONFIDENCE_SCORE, the variable that actually "
        "exists on both Render services and that the Founder edits"
    )


def test_render_yaml_matches_what_is_actually_deployed():
    """The file that caused the wrong answer.

    render.yaml declared AUTO_TRADE_MIN_CONFIDENCE (on neither service) and gave
    MIN_CONFIDENCE_SCORE as 0.85 when both services had 0.75. Anyone reading the repo --
    including me, in a table I presented to the Founder as fact -- got a false picture.
    A config file that lies is worse than no config file.
    """
    raw = (ROOT / "render.yaml").read_text(encoding="utf-8")
    # Strip comments: the explanation of this very bug names the retired variable, and a
    # guard that trips on its own documentation is a guard nobody keeps.
    text = "\n".join(re.sub(r"#.*$", "", line) for line in raw.splitlines())
    assert "AUTO_TRADE_MIN_CONFIDENCE" not in text, (
        "render.yaml must not declare a variable the code no longer reads and neither "
        "service defines"
    )
    match = re.search(r"key:\s*MIN_CONFIDENCE_SCORE\s*\n\s*value:\s*\"?([0-9.]+)\"?", text)
    if match:
        assert match.group(1) == "0.75", (
            f"render.yaml claims MIN_CONFIDENCE_SCORE is {match.group(1)}; the live value on "
            "both services is 0.75. Update the file when the dashboard changes, or drop the "
            "hardcoded value and mark it sync:false so the file cannot contradict reality."
        )


def test_no_caller_reintroduces_a_rival_confidence_source():
    """Guards the whole package. Adding a broker is exactly how a fourth copy appears."""
    offenders: list[str] = []
    for path in SOURCE.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = re.sub(r"#.*$", "", line)
            if re.search(r"_float_env\(\s*[\"']AUTO_TRADE_MIN_CONFIDENCE", stripped):
                offenders.append(f"{path.relative_to(SOURCE)}:{number}")
            if "investment.get(\"minimum_overall_confidence\"" in stripped:
                offenders.append(f"{path.relative_to(SOURCE)}:{number}")
    assert offenders == [], (
        f"a rival source for the confidence bar reappeared: {offenders}"
    )


def test_the_seeded_database_row_is_marked_retired_not_authoritative():
    """It stays for history, but its description must not invite anyone to trust it."""
    text = (SOURCE / "foundation.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    description: str | None = None
    for node in ast.walk(tree):
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
                description = value.elts[2].value
    assert description is not None, "the policy key should still be seeded for history"
    assert "RETIRED" in description.upper() and "MIN_CONFIDENCE_SCORE" in description, (
        f"the retired row must say where the real bar lives, got: {description!r}"
    )
