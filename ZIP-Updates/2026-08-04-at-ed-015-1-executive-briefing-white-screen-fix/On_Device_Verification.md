# On-Device / Production Acceptance — AT-ED-015.1

Per Section 10 of the directive, this pass is complete only once the Founder confirms the items
below on their own device. Nothing in this file is claimed as already verified on the Founder's
device — the automated and emulator-based verification described in `Test_Report.md` and
`Root_Cause_Analysis.md` is strong evidence the fix is correct, but it is not a substitute for
this checklist. This file is a checklist for the Founder to work through, not a completed report.

## Checklist

- [ ] App opens into the Executive Briefing.
- [ ] Initial content appears (portfolio, market environment, thesis, etc.).
- [ ] A live refresh completes without the screen going blank.
- [ ] The screen remains visible and usable for at least five minutes.
- [ ] Repeated manual refreshes (pull-to-refresh or the Refresh button) do not blank the screen.
- [ ] Navigation across all screens works (Operations, Activity, Recommendations, Portfolio,
      Market, Learning).
- [ ] Returning to the Executive Briefing from another screen works.
- [ ] Backgrounding the app and reopening it works.
- [ ] Transitions between cached and live data (e.g., after a brief network drop) work without a
      blank screen.
- [ ] If any single card or section does fail, a calm fallback message appears (with Retry and
      Open Operations buttons) rather than the whole app going white.

## How To Report Back

If everything above holds, this directive is complete and no further action is needed. If
anything still fails, please note: which screen you were on, what you had just done (opened the
app / refreshed / switched screens / reopened from background), and if possible, the "Diagnostic
ID" shown on the fallback screen (if the new error boundary caught something) - that ID does not
identify what went wrong on its own, but it lets me correlate your report with the engineering
logs precisely.
