# Changed Files — AT-ED-016.1

All changes are wording/presentation only. No file's numeric logic, evidence-selection logic, or
boolean conditions changed - only output strings and JSX structure.

## Modified

- `mobile/screens/ExecutiveBriefing.js` — substantially restructured JSX; every card collapsed to
  its directive-specified field list; `explainMissing()` calls that leaked raw field names
  (`week_pnl`, `month_pnl`) removed in favour of omitting missing lines.
- `mobile/lib/cio.js` + `.test.js` — `cioMarketOutlook()` and every honest-fallback sentence
  reworded to first-person CIO framing; `cioNoActionReason()`/`cioClosingRecommendation()` polish.
- `mobile/lib/forecastEngine.js` + `.test.js` — grammar-only fixes to `evidence`/
  `confidenceReason`/`explanation` string templates. Zero numeric formulas touched.
- `mobile/lib/investmentThesis.js` + `.test.js` — `evidence` array wording only.
- `mobile/lib/investmentCommittee.js` + `.test.js` — every department conclusion string
  rewritten; all nine `hasEvidence` conditions and the department order unchanged.
- `mobile/lib/principalRisks.js` + `.test.js` — six fields collapsed to four; same underlying
  percentage math.
- `mobile/lib/principalOpportunities.js` + `.test.js` — six fields collapsed to four; the
  AT-ED-015.1 `key_drivers` string-vs-array safety guard is untouched.
- `mobile/lib/founderActions.js` + `.test.js` — six fields collapsed to one spoken recommendation.
- `architecture/ARCHITECTURE_DELTA.md`, `governance/IMPLEMENTATION_LOG.md` — new dated entries.

## Not Touched

`lib/forecastFactors.js`, `lib/forecastHistory.js`, `lib/forecastAccountability.js`,
`hooks/useForecastHistory.js`, `lib/portfolioPosition.js`, `lib/investmentRhythm.js`,
`components/ErrorBoundary.js`, `App.js`, and every screen other than the Executive Briefing.
Nothing under `src/` changed.
