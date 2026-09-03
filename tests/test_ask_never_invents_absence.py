"""An empty section must never read as "I looked and there was nothing".

2026-09-03, Founder-reported. He asked the app why crypto had not traded for a week. It told
him:

    "There is no evidence of recent crypto recommendations, trades, or research activity
     after August 25th."
    "It's a deliberate pause until better trading opportunities or clearer signals emerge."

Every sentence was false. Crypto research had run 82 minutes before he asked: 40 coins scored,
4 through the confidence bar, FIL top at 0.82, two trade ideas put forward. There were 15,319
research scores in the database and 507 written since 1 September.

THE CAUSE was not the model being careless. The API handed it `crypto_research_scores: []`
because AI Trader had restarted and was answering from a fast partial context while the rest
loaded. An empty list does not read as "not fetched yet" -- it reads as "I checked, and there
is nothing." The model filled the gap the way models do: no research visible became "research
stopped on 25 August" became "a deliberate, risk-conscious pause". Coherent, confident, and
entirely invented.

The Founder was weighing decisions about real money against that answer.

The fix is a distinction, not a feature: a section that was not fetched is now LABELLED
not_loaded_yet, with an instruction not to treat its absence as evidence. These tests exist
because the failure is invisible from the outside -- the answer looked more authoritative than
a correct one would have.
"""

from __future__ import annotations

import json
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "ai_trader"
API = SRC / "api" / "__init__.py"

WITHHELD_IN_FAST_MODE = (
    "latest_recommendations",
    "market_forecasts",
    "crypto_research_scores",
    "recent_crypto_news",
)


def _source() -> str:
    return API.read_text(encoding="utf-8")


def test_no_withheld_section_is_handed_over_as_an_empty_list():
    """The exact defect. `[] if fast_only else ...` is the shape that caused it."""
    source = _source()
    offenders = []
    for section in WITHHELD_IN_FAST_MODE:
        for pattern in (rf'"{section}": \[\] if fast_only',
                        rf'\["{section}"\] = \[\] if fast_only'):
            if re.search(pattern, source):
                offenders.append(section)
    assert not offenders, (
        f"these sections are handed to the model as an empty list when not loaded, which reads "
        f"as 'there is nothing' rather than 'not fetched': {offenders}"
    )


def test_every_withheld_section_is_labelled_instead():
    source = _source()
    for section in WITHHELD_IN_FAST_MODE:
        assert re.search(rf'"{section}".{{0,8}}_NOT_LOADED_YET|\["{section}"\] = _NOT_LOADED_YET', source), (
            f"{section} is not marked _NOT_LOADED_YET in the fast path"
        )


def test_the_label_tells_the_model_what_absence_does_not_mean():
    """A status field alone is not enough -- the model has to be told what NOT to conclude,
    because the wrong conclusion is the plausible one."""
    source = _source()
    block = source[source.index("_NOT_LOADED_YET = {"):]
    block = block[:block.index("\n}") + 2].lower()
    assert "not_loaded_yet" in block
    for required in ("not empty", "must not infer", "again in a moment"):
        assert required in block, f"the label is missing {required!r}"
    for forbidden_conclusion in ("research stopped", "trading paused"):
        assert forbidden_conclusion in block, (
            f"the label should name {forbidden_conclusion!r} as a conclusion not to draw -- "
            "it is exactly what the model invented"
        )


def test_the_warming_note_forbids_the_inference_too():
    """Belt and braces. The per-section label and the top-level note must agree, because the
    model may read either."""
    source = _source()
    note = source[source.index('"AI Trader has just restarted.'):]
    note = note[:note.index("            )")].lower()
    assert "absence here is not evidence" in note
    assert "not_loaded_yet" in note
    assert "cannot see them yet" in note


def test_the_label_survives_being_turned_into_json():
    """The context is serialised before it reaches the model. A marker that vanishes in
    transit is no marker at all."""
    source = _source()
    namespace: dict = {}
    block = source[source.index("_NOT_LOADED_YET = {"):]
    exec(block[:block.index("\n}") + 2], namespace)  # noqa: S102 - a literal dict in our own source
    restored = json.loads(json.dumps(namespace["_NOT_LOADED_YET"]))
    assert restored["status"] == "not_loaded_yet"
    assert "not empty" in restored["meaning"].lower()


def test_the_full_context_path_is_untouched():
    """The fix must only affect the fast path. A normal answer should carry real research, and
    quietly labelling it 'not loaded' would be a worse bug than the one being fixed."""
    source = _source()
    for section in ("market_forecasts", "crypto_research_scores", "recent_crypto_news"):
        assert f"else self._ask_{section}()" in source, (
            f"{section} no longer falls through to the real fetch when there is time"
        )
