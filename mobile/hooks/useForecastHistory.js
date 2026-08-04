// AT-ED-016 Part 3: real, on-device forecast persistence, following the exact
// load/parse-defensively/discard-on-incompatible pattern hooks/useFounderEvidence.js already
// established for AsyncStorage reads (see loadCachedFounderEvidence() there) - kept as thin as
// possible, with every real decision (dedup, due-check, directional grading) delegated to the
// pure, tested functions in lib/forecastHistory.js and lib/forecastAccountability.js.

'use strict';

const React = require('react');
const { useCallback, useEffect, useRef, useState } = React;
const AsyncStorage = require('@react-native-async-storage/async-storage').default;
const { buildNewRecordsForHorizons, resolveDueRecords } = require('../lib/forecastHistory');
const { forecastAccountability } = require('../lib/forecastAccountability');

const FORECAST_HISTORY_KEY = 'ai-trader:forecast-history:v1';
// Bounds on-device storage growth - roughly a year of daily records across five horizons, well
// under AsyncStorage's known Android size ceiling (see AT-ED-011.9's ARCHITECTURE_DELTA entry for
// the incident that established why this project takes storage growth seriously).
const MAX_STORED_RECORDS = 200;

async function loadStoredRecords() {
  try {
    const raw = await AsyncStorage.getItem(FORECAST_HISTORY_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function persist(records) {
  AsyncStorage.setItem(FORECAST_HISTORY_KEY, JSON.stringify(records.slice(-MAX_STORED_RECORDS))).catch(() => {});
}

// horizons: the latest output of lib/forecastEngine.js's projectPortfolioHorizons().
// currentPortfolioValue: the latest real portfolio value, used both to record new forecasts'
// starting point and to resolve any due-but-unresolved older forecasts against a real
// observation.
function useForecastHistory({ horizons, currentPortfolioValue } = {}) {
  const [records, setRecords] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const isMountedRef = useRef(true);

  useEffect(
    () => () => {
      isMountedRef.current = false;
    },
    []
  );

  useEffect(() => {
    loadStoredRecords().then((stored) => {
      if (isMountedRef.current) {
        setRecords(stored);
        setLoaded(true);
      }
    });
  }, []);

  const hasPortfolioValue = typeof currentPortfolioValue === 'number' && Number.isFinite(currentPortfolioValue);

  // Resolve any due records against the real, current portfolio value - this is the actual
  // "compare forecast to outcome" mechanism, run on every render where fresh evidence is
  // available, not on a timer (there is no background execution in a React Native screen).
  useEffect(() => {
    if (!loaded || !hasPortfolioValue) {
      return;
    }
    setRecords((prev) => {
      const resolved = resolveDueRecords(prev, currentPortfolioValue);
      const changed = resolved.some((record, index) => record !== prev[index]);
      if (changed) {
        persist(resolved);
      }
      return changed ? resolved : prev;
    });
  }, [loaded, hasPortfolioValue, currentPortfolioValue]);

  // Records any new, real, available forecasts (deduped to roughly once/day per horizon by
  // lib/forecastHistory.js's buildNewRecordsForHorizons) whenever fresh horizons and a fresh
  // portfolio value are both available.
  useEffect(() => {
    if (!loaded || !hasPortfolioValue || !horizons || !horizons.length) {
      return;
    }
    setRecords((prev) => {
      const additions = buildNewRecordsForHorizons({ horizons, portfolioValueAtCreation: currentPortfolioValue, existingRecords: prev });
      if (!additions.length) {
        return prev;
      }
      const next = [...prev, ...additions];
      persist(next);
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, hasPortfolioValue, currentPortfolioValue, horizons]);

  const clearHistory = useCallback(() => {
    setRecords([]);
    AsyncStorage.removeItem(FORECAST_HISTORY_KEY).catch(() => {});
  }, []);

  const summary = forecastAccountability(records);

  return { records, summary, clearHistory };
}

module.exports = { useForecastHistory, FORECAST_HISTORY_KEY };
