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


def test_the_policy_bar_is_derived_from_the_database_with_render_as_fallback():
    """load_trading_policy is the single funnel every gate reaches its bar through.

    2026-09-02, Founder-directed, REVERSING the 2026-08-30 decision this file was written for:
    "move the confidence bar to the database. it's not an environment variable."

    The earlier decision was the right answer to a different question -- the number lived in
    three places and naming Render the winner ended the argument. Now that every decision has
    one declared home (decision_registry.py) the tie-break is unnecessary, and a strategy
    number should not need a deploy and a 15-minute worker restart to change.

    Done in the safe order: the live INVESTMENT_POLICIES row was set to 0.70, the exact value
    already in MIN_CONFIDENCE_SCORE, BEFORE the reader was switched -- so moving the home
    could not move the bar. What this file guards is unchanged: exactly ONE source, never three.
    """
    text = (SOURCE / "foundation.py").read_text(encoding="utf-8")
    match = re.search(r"min_ai_confidence=(.+?\n.*?\n.*?\),)", text, re.S)
    assert match, "could not find min_ai_confidence in load_trading_policy"
    expression = match.group(1)
    assert "minimum_overall_confidence" in expression, (
        f"min_ai_confidence must read the database row, got: {expression.strip()}"
    )
    assert "min_confidence_score" in expression, (
        "Render must remain the fallback, or a database missing that row silently drops the "
        f"bar to a built-in default, got: {expression.strip()}"
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
    assert offenders == [], (
        f"a rival source for the confidence bar reappeared: {offenders}"
    )


def test_exactly_one_place_reads_the_confidence_row():
    """The point of the file, restated for the new home.

    Reading the database row is now correct -- in ONE place. A second reader is how the
    original three-way split began, so the count is asserted rather than trusted.
    """
    readers: list[str] = []
    for path in SOURCE.rglob("*.py"):
        if path.name == "decision_registry.py":
            continue  # declares the decision; does not resolve it for the live path yet
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = re.sub(r"#.*$", "", line)
            if "minimum_overall_confidence" in stripped and ".get(" in stripped:
                readers.append(f"{path.relative_to(SOURCE)}:{number}")
    assert len(readers) == 1, (
        f"the confidence row must have exactly one reader, found: {readers}"
    )


def test_the_seeded_database_row_is_described_as_the_live_bar():
    """2026-09-02: this row IS the bar now, so its description must say so.

    It previously had to be marked RETIRED, because trusting it would have been a mistake.
    Leaving that wording in place after the Founder moved the bar would be worse than useless
    -- it would tell the next reader to ignore the number that is actually in charge.
    """
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
    assert description is not None, "the policy key must be seeded"
    assert "RETIRED" not in description.upper(), (
        f"this row is the live bar now, not a retired one: {description!r}"
    )
    assert "sure" in description.lower() or "confiden" in description.lower(), (
        f"the description must say in plain English what the number does, got: {description!r}"
    )
