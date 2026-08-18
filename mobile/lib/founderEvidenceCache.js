// AT-ED-011.9: what gets written to AsyncStorage for /founder-evidence, kept deliberately far
// smaller than the live payload. AT-ED-011.8 traced a production "database or disk is full
// (SQLite code 13 SQLITE_FULL)" Founder-visible error to this exact write - AsyncStorage's
// Android backing store is itself a small SQLite database with its own size ceiling (a known
// upstream defect, react-native-async-storage/async-storage#427), and the full
// /founder-evidence response is large enough to hit it on its own, before even counting the
// separate recommendations cache (see recCacheItemLimit below).
//
// Measured against a representative production /founder-evidence fetch (2026-08-04,
// 4,555,434 bytes total): `recommendations` alone was 4,324,201 bytes (94.9% of the entire
// payload) across 100 items - about 43KB each, dominated by per-item fields
// (intelligence/committee/strategy/signals/probability) that statusFromFounderEvidence never
// reads for anything beyond a handful of scalars. Every other top-level section combined was
// under 230KB. Two further redundancies were found and are also dropped here, not just
// trimmed: `portfolio.brokers` duplicates the top-level `brokers` array verbatim (63,551 of
// portfolio's 64,736 bytes) and is never read by statusFromFounderEvidence; each broker's
// `payload_json`/`positions_json` are raw-JSON-string re-encodings of the already-present
// `payload`/`positions` objects (about half of a broker's ~32KB).
//
// The resulting shape is still founder-evidence-shaped (same top-level keys), just with
// bounded array lengths and the two duplicate fields removed, so statusFromFounderEvidence(),
// activityFromFounderEvidence() and founderLearningForMobile() all continue to work completely
// unchanged against a cached snapshot - only useFounderEvidence.js's cache read/write layer
// needed to change.

'use strict';

const FOUNDER_EVIDENCE_CACHE_VERSION = 2;

// Every array below is capped independently so no single section can grow back into the
// AT-ED-011.8 failure mode as production data accumulates over time.
const MAX_CACHED_RECOMMENDATION_STUBS = 10;
const MAX_CACHED_TRADES = 20;
const MAX_CACHED_CLOSED_TRADE_HISTORY = 20;
const MAX_CACHED_JOBS = 20;
const MAX_CACHED_TIMELINE_ITEMS = 20;
const MAX_CACHED_RESEARCH_ROWS = 10;
const MAX_CACHED_LEARNING_ROWS = 10;

// The shared recommendations cache (mobile/hooks/useFounderEvidence.js) now receives compact
// backend summaries and remains capped as defence in depth. Full dossiers use the separate
// screen-owned cache in hooks/useRecommendationDossiers.js and are fetched only on demand.
const MAX_CACHED_RECOMMENDATION_LIST_ITEMS = 15;

// Fields kept per recommendation in the small founder-evidence-snapshot stub list. Confirmed
// by reading every recommendation-field access in founderEvidenceMapping.js's
// statusFromFounderEvidence(): only .length, .symbol, .freshness_status, .broker, and
// .suggested_broker are ever read from the shared founder-evidence recommendations array (the
// Recommendations screen's rich detail comes from useRecommendationDossiers, not from this
// high-frequency Founder snapshot).
const RECOMMENDATION_STUB_FIELDS = [
  'proposal_id',
  'recommendation_id',
  'symbol',
  'broker',
  'suggested_broker',
  'freshness_status',
  'confidence',
  'created_at',
];

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function trimRecommendationStub(item) {
  const stub = {};
  RECOMMENDATION_STUB_FIELDS.forEach((key) => {
    if (item && item[key] !== undefined) {
      stub[key] = item[key];
    }
  });
  return stub;
}

// portfolio.brokers is a verbatim duplicate of the top-level `brokers` array (see module
// comment) - statusFromFounderEvidence reads only the scalar/array fields kept here.
function trimPortfolio(portfolio) {
  if (!isPlainObject(portfolio)) {
    return portfolio || null;
  }
  const { brokers, ...rest } = portfolio;
  return rest;
}

// payload_json/positions_json are raw-JSON-string duplicates of payload/positions - every
// field statusFromFounderEvidence reads off a broker row is preserved here, just not the two
// duplicate encodings.
function trimBroker(broker) {
  if (!isPlainObject(broker)) {
    return broker;
  }
  const { payload_json, positions_json, ...rest } = broker;
  return rest;
}

function buildFounderEvidenceCacheSnapshot(founderEvidence) {
  if (!isPlainObject(founderEvidence)) {
    return null;
  }
  const timeline = isPlainObject(founderEvidence.timeline) ? founderEvidence.timeline : {};
  return {
    generated_at: founderEvidence.generated_at || null,
    period: founderEvidence.period || null,
    status: founderEvidence.status || null,
    portfolio: trimPortfolio(founderEvidence.portfolio),
    brokers: (founderEvidence.brokers || []).map(trimBroker),
    summary: founderEvidence.summary || null,
    why_no_trade: founderEvidence.why_no_trade || null,
    snapshot: founderEvidence.snapshot || null,
    truthfulness: founderEvidence.truthfulness || null,
    recommendations: (founderEvidence.recommendations || [])
      .slice(0, MAX_CACHED_RECOMMENDATION_STUBS)
      .map(trimRecommendationStub),
    trades: (founderEvidence.trades || []).slice(0, MAX_CACHED_TRADES),
    // Not period-bound (see production_evidence.py's _load_closed_trade_history) - this is
    // what Current Position/Forecast Centre/Learning read, cached separately from the
    // period-scoped `trades` above so an offline reopen still shows real closed-trade
    // figures instead of whatever the last-viewed period happened to contain.
    closed_trade_history: (founderEvidence.closed_trade_history || []).slice(0, MAX_CACHED_CLOSED_TRADE_HISTORY),
    research: (founderEvidence.research || []).slice(0, MAX_CACHED_RESEARCH_ROWS),
    learning: (founderEvidence.learning || []).slice(0, MAX_CACHED_LEARNING_ROWS),
    jobs: (founderEvidence.jobs || []).slice(0, MAX_CACHED_JOBS),
    timeline: {
      items: (timeline.items || []).slice(0, MAX_CACHED_TIMELINE_ITEMS),
      total: timeline.total || 0,
    },
  };
}

// Reads back a raw AsyncStorage.getItem() string (already JSON.parsed by the caller) and
// decides whether it's a usable, current-version cache. AT-ED-011.8's incident cache (and any
// pre-AT-ED-011.9 install's cache) has no `v` field at all and holds the full, multi-megabyte
// founder-evidence payload directly under `data` - that shape must never be treated as this
// version's small snapshot shape, so any mismatch is reported as incompatible rather than
// guessed at.
function parseCachedFounderEvidenceEnvelope(parsed) {
  if (!isPlainObject(parsed)) {
    return { compatible: false, data: null, fetchedAt: null };
  }
  if (parsed.v === FOUNDER_EVIDENCE_CACHE_VERSION && isPlainObject(parsed.data)) {
    return { compatible: true, data: parsed.data, fetchedAt: parsed.fetchedAt || null };
  }
  return { compatible: false, data: null, fetchedAt: null };
}

module.exports = {
  FOUNDER_EVIDENCE_CACHE_VERSION,
  MAX_CACHED_RECOMMENDATION_STUBS,
  MAX_CACHED_TRADES,
  MAX_CACHED_CLOSED_TRADE_HISTORY,
  MAX_CACHED_JOBS,
  MAX_CACHED_TIMELINE_ITEMS,
  MAX_CACHED_RESEARCH_ROWS,
  MAX_CACHED_LEARNING_ROWS,
  MAX_CACHED_RECOMMENDATION_LIST_ITEMS,
  buildFounderEvidenceCacheSnapshot,
  parseCachedFounderEvidenceEnvelope,
};
