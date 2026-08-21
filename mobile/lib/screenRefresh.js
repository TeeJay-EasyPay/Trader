// Screen-level refresh composition, added for AT-ED-011.5 requirement 5 ("each major screen
// refreshes independently rather than merely displaying a screen-specific spinner while still
// reloading one large shared payload").
//
// Before this module existed, App.js decided which loading flag/refresh function to show with
// an ad-hoc ternary keyed on the active screen name, and Activity/Recommendations/Portfolio/
// Learning had NO refresh state of their own at all - they simply read useFounderEvidence's
// `loading`/`lastRefreshedAt`/`lastRefreshError` directly, so there was nowhere to answer "does
// Activity have its own last-successful-refresh timestamp?" other than "it borrows Portfolio's".
// That is fine when it is done on purpose (four screens that are honestly reading one
// authoritative shared payload should show one honest shared state - see the ownership table in
// ARCHITECTURE_DELTA.md / Data_Freshness_Findings.md for why no narrower backend endpoint
// changes that), but it needs to be an explicit, testable composition, not an implicit side
// effect of every screen happening to destructure the same hook. Recommendation summaries
// remain shared, while the heavy full dossiers are a Recommendations-screen-only source.
//
// SCREEN_DATA_SOURCES is the single source of truth for which named data source(s) each screen
// depends on. "Command" (the Founder's own name for the Dashboard/Command-Centre screen) and
// "Broker Panels" (a component embedded in Dashboard and Portfolio, not an independently
// navigable screen) are intentionally not separate keys here - see the ownership table for why.
// AT-ED-014: the CIO became the primary, dedicated screen (Section 1 - "The CIO is NOT embedded
// within Dashboard... shall have its own dedicated navigation item"); the former Dashboard was
// renamed Operations and now covers operational health only. AT-ED-015 Section 11 renamed the
// CIO screen itself to ExecutiveBriefing. Both read the same shared + founderBrief sources
// Dashboard always did - the briefing synthesises the same evidence Operations shows in detail,
// it does not introduce a new backend source.
// APP SIMPLIFICATION (2026-08-21): Recommendations and Market were deleted as dedicated
// screens. Market's themes data is still genuinely needed (the Executive Briefing's Investment
// Thesis/Opportunities content), so the 'market' source moved here rather than being dropped -
// pulling to refresh the Briefing now also refreshes themes, since there is no longer a
// separate screen whose own pull-to-refresh could do it.
const SCREEN_DATA_SOURCES = Object.freeze({
  ExecutiveBriefing: ['shared', 'founderBrief', 'market'],
  Operations: ['shared', 'founderBrief'],
  Activity: ['shared'],
  Portfolio: ['shared'],
  Learning: ['shared'],
});

// A screen's own "is it currently loading" state is the OR of only the sources it actually
// reads - Market's `loading` must never become true because founder-evidence happens to be
// mid-refresh, and vice versa.
function combineLoading(sources) {
  return sources.some((source) => Boolean(source && source.loading));
}

// A screen's own "when did I last finish successfully" timestamp is the latest of only the
// sources it reads. For a screen backed by a single source this is just that source's own
// timestamp; for Dashboard (shared + founderBrief) it is whichever of the two most recently
// completed, since `Promise.all` in the composed `refresh()` below only resolves once both have.
function latestTimestamp(sources) {
  const timestamps = sources
    .map((source) => (source && source.lastRefreshedAt ? new Date(source.lastRefreshedAt).getTime() : NaN))
    .filter((value) => !Number.isNaN(value));
  if (!timestamps.length) {
    return null;
  }
  return new Date(Math.max(...timestamps)).toISOString();
}

// A screen's own error is truthful about exactly which of ITS OWN sources failed, never
// another screen's. Mirrors combineOptionalResults' "name every failure, don't hide or merge
// silently" rule in refreshLifecycle.js.
function combineErrors(sources) {
  const failures = sources
    .map((source) => (source && source.lastRefreshError ? String(source.lastRefreshError) : null))
    .filter(Boolean);
  return failures.length ? failures.join('; ') : null;
}

// Composes N underlying hook-shaped sources ({ refresh, loading, lastRefreshedAt,
// lastRefreshError }) into one screen-shaped refresh object with the same shape. Each
// underlying source keeps its own duplicate-refresh guard (shouldStartRefresh, in
// refreshLifecycle.js) - this function does not need to reimplement deduplication, only compose
// already-deduplicated sources without introducing a NEW way to double-fetch one of them (e.g.
// two screens must never each hold their own copy of the `shared` source's refresh(), since
// calling both would still just hit `shared`'s own single in-flight guard, not create a second
// concurrent request to the shared source).
function composeScreenRefresh(sources) {
  const list = sources.filter(Boolean);
  return {
    refresh: () => Promise.all(list.map((source) => source.refresh())),
    loading: combineLoading(list),
    lastRefreshedAt: latestTimestamp(list),
    lastRefreshError: combineErrors(list),
  };
}

// Builds every screen's composed refresh object from the underlying source objects, in
// one place, so App.js cannot accidentally wire a screen to a source SCREEN_DATA_SOURCES does
// not list for it.
function buildScreenRefreshRegistry({ shared, market, founderBrief }) {
  const sourcesByName = { shared, market, founderBrief };
  const registry = {};
  Object.entries(SCREEN_DATA_SOURCES).forEach(([screen, sourceNames]) => {
    registry[screen] = composeScreenRefresh(sourceNames.map((name) => sourcesByName[name]));
  });
  return registry;
}

module.exports = {
  SCREEN_DATA_SOURCES,
  combineLoading,
  latestTimestamp,
  combineErrors,
  composeScreenRefresh,
  buildScreenRefreshRegistry,
};
