"""One honest number: does the system make money over time?

2026-09-03, Founder-directed: "Please go ahead and fix it then."

TRADE_R_MULTIPLES was written for weeks and read by nothing. Read naively it said the average
trade returned +1.30R, while the scorecard drawn from the same 22 trades said the month was
down 5.08 pounds on 10 wins and 16 losses. Both cannot be true.

The fixture below is those 22 real Kraken trades, copied from production on 2026-09-03. That
matters: a synthetic fixture would have been shaped by what I expected to find, and what was
actually there is stranger than anything I would have invented -- three trades risking FOUR
PENCE each, returning +21R, +15R and +9.4R, carrying the entire average between them.

The arithmetic was never wrong. The reading was. These tests pin the corrected reading against
the exact data that produced the misleading answer.
"""

from __future__ import annotations

from ai_trader.expectancy import DEFAULT_MINIMUM_RISK, expectancy

# symbol, risk, gross_r, net_r, fee_r -- production, 2026-09-03.
REAL = [
    ("GRT",  0.38,  2.64,   1.53, 1.11),
    ("LTC",  0.38, -0.85,  -1.64, 0.79),
    ("AAVE", 0.38, -1.64,  -2.70, 1.06),
    ("ADA",  0.38, -1.07,  -2.13, 1.06),
    ("ADA",  0.37, -0.93,  -2.02, 1.08),
    ("ATOM", 0.37, -1.69,  -2.74, 1.06),
    ("LTC",  0.38,  1.51,   0.43, 1.08),
    ("XRP",  0.36, -0.84,  -1.90, 1.05),
    ("KSM",  0.34, -1.94,  -2.71, 0.77),
    ("SOL",  0.38, -0.13,  -1.19, 1.06),
    ("LINK", 0.38,  0.06,  -1.00, 1.07),
    ("LINK", 0.09,  0.50,  -0.58, 1.08),
    ("XLM",  0.38, -0.02,  -1.09, 1.08),
    ("LTC",  0.06, -0.69,  -1.76, 1.06),
    ("ETH",  0.04, 10.27,   9.38, 0.89),   # the three that
    ("XRP",  0.04, 21.98,  21.00, 0.98),   # carried the whole
    ("ETH",  0.04, 15.96,  15.03, 0.93),   # +1.30 average
    ("ETH",  0.04,  2.24,   1.43, 0.81),
    ("BCH",  0.04,  2.03,   1.21, 0.82),
    ("BTC",  0.05,  1.86,   1.05, 0.82),
    ("ETH",  0.04, -1.25,  -2.04, 0.79),
    ("BCH",  0.04,  1.77,   0.96, 0.81),
]

ROWS = [
    {"symbol": s, "broker": "kraken", "risk": risk, "planned_r": None,
     "gross_r": g, "net_r": n, "fee_r": f, "created_at": "2026-09-01T00:00:00Z"}
    for s, risk, g, n, f in REAL
]


def test_the_naive_average_really_was_plus_one_point_three():
    """Anchors the problem. If this stops reproducing, the fixture has drifted from the data
    that caused the investigation and every test below is measuring something else."""
    nets = [r["net_r"] for r in ROWS]
    assert round(sum(nets) / len(nets), 2) == 1.30


def test_the_corrected_reading_is_negative():
    """The whole point. Once four-penny trades stop voting, the picture matches the scorecard:
    the month was down, and the average trade lost money."""
    result = expectancy(ROWS)
    assert result["expectancy_r"] is not None
    assert result["expectancy_r"] < 0, (
        f"expected a negative expectancy, got {result['expectancy_r']}"
    )


def test_the_tiny_trades_are_excluded_and_counted():
    """Excluding data silently is how you get a different lie. The count must be reported."""
    result = expectancy(ROWS)
    # Twelve trades risked 0.34-0.38. Ten risked between 4p and 9p -- and of those ten, three
    # are the ones returning +21R, +15R and +9.4R that produced the misleading +1.30.
    assert result["trades_counted"] == 12
    assert result["trades_excluded_as_too_small"] == 10
    assert result["trades_counted"] + result["trades_excluded_as_too_small"] == len(ROWS)


def test_the_fee_cost_is_surfaced_because_it_is_the_real_finding():
    """Roughly 1R of every trade goes in fees -- the entire amount risked. This is the plainest
    statement of the crypto problem in the whole app and it must not be buried."""
    result = expectancy(ROWS)
    assert result["average_fee_cost_r"] is not None
    assert result["average_fee_cost_r"] > 0.9
    assert "fees" in result["plain_english"].lower()


def test_both_averages_are_reported_never_just_the_flattering_one():
    result = expectancy(ROWS)
    assert result["expectancy_r"] is not None
    assert result["risk_weighted_expectancy_r"] is not None


def test_a_single_huge_multiple_on_a_tiny_stake_cannot_move_the_answer():
    """The failure mode, isolated. One 4p trade returning +500R must change nothing."""
    baseline = expectancy(ROWS)["expectancy_r"]
    poisoned = ROWS + [{"symbol": "XXX", "broker": "kraken", "risk": 0.04, "planned_r": None,
                        "gross_r": 501.0, "net_r": 500.0, "fee_r": 1.0,
                        "created_at": "2026-09-02T00:00:00Z"}]
    assert expectancy(poisoned)["expectancy_r"] == baseline


def test_a_genuinely_large_winner_does_move_the_answer():
    """The guard must not be so blunt that real results cannot register."""
    baseline = expectancy(ROWS)["expectancy_r"]
    real_win = ROWS + [{"symbol": "YYY", "broker": "kraken", "risk": 0.50, "planned_r": None,
                        "gross_r": 4.0, "net_r": 3.0, "fee_r": 1.0,
                        "created_at": "2026-09-02T00:00:00Z"}]
    assert expectancy(real_win)["expectancy_r"] > baseline


def test_it_says_plainly_that_the_strategy_does_not_pay_for_itself():
    """The Founder is not an engineer. A number without a sentence is not an answer."""
    text = expectancy(ROWS)["plain_english"].lower()
    assert "does not pay for itself" in text
    assert "%" not in text and "expectancy_r" not in text


def test_a_thin_sample_is_labelled_as_early_rather_than_a_verdict():
    few = ROWS[:3]
    result = expectancy(few)
    assert result["sample_is_meaningful"] is False
    assert "early reading" in result["plain_english"]


def test_no_qualifying_trades_says_so_instead_of_returning_zero():
    """Zero would read as 'breaks even', which is a different and wrong claim."""
    result = expectancy([r for r in ROWS if r["risk"] < 0.1])
    assert result["expectancy_r"] is None
    assert "nothing to measure" in result["plain_english"]


def test_missing_values_are_skipped_not_treated_as_zero():
    rows = ROWS + [{"symbol": "ZZZ", "broker": "kraken", "risk": 0.40, "planned_r": None,
                    "gross_r": None, "net_r": None, "fee_r": None, "created_at": "x"}]
    assert expectancy(rows)["trades_counted"] == expectancy(ROWS)["trades_counted"]


def test_the_minimum_is_above_krakens_dust_and_below_a_real_position():
    """0.25 sits between the two worlds in the data: a 2-pound Kraken minimum position with a
    1.5% stop risks about 3p, while the Founder's current 25-50 pound sizing risks 0.38-0.75."""
    assert 0.10 < DEFAULT_MINIMUM_RISK < 0.35
