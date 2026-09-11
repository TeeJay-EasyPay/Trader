---
title: "Experiment validity and overfitting"
topics: [experiment_design, backtesting, evidence]
applies_to: [stock, crypto]
sectors: []
version: 2026-09-11
status: shadow_only
accessed_at: 2026-09-11
review_due: 2026-10-11
publication_date: unknown
usage_basis: original_summary_and_links_no_full_source_copy
freshness: broker_facts_require_current_account_verification
---

## Principle

Selecting a strategy because it performed best among many historical alternatives can select noise. Record failed variants, freeze rules before prospective evaluation, and separate development data from evaluation data. Do not use future information or repeated correlated signals as independent evidence.

## Application checklist

Specify the hypothesis, baseline, costs, sample and risk checks before collecting results. Retain skipped opportunities and open-position uncertainty. Inspect dependence on individual winners. Weekly reviews are checkpoints, not automatic success declarations. Multiple comparisons and model variability limit confidence; inconclusive is a valid outcome.

## Source and limitations

Bailey, Borwein, Lopez de Prado and Zhu, The Probability of Backtest Overfitting: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf . Accessed 2026-09-11. Original short summary plus application-specific checklist, not a reproduction or implementation of the paper's statistical method. No license to redistribute the full paper is claimed. This guidance does not make the app's screening bounds calibrated statistical tests.
