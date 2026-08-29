import { useCallback, useEffect, useRef, useState } from 'react';

const { apiRequest, COMMAND_TIMEOUT_MS } = require('../api/client');
const { cycleProgressLabel, currentStepOf, isTerminal } = require('../lib/cycleProgress');

// 2026-08-29, Founder-reported: "when I go to the executive briefing and come back it stops.
// i then don't know if it actually stopped or it is still running in the background even
// maybe as an orphaned process locking records etc if it fails."
//
// The cycle itself was never stopping -- it runs in a thread on the server and the phone is
// only watching it. What stopped was the WATCHING: every piece of state lived inside
// RunCycleScreen, and App.js unmounts that component the moment another tab is selected, so
// the poll timer was cleared and the cycle id forgotten. The run carried on invisibly, which
// is the worst of both worlds: still going, no longer observable.
//
// So the state lives HERE, mounted once in App.js for the life of the app, and the screen
// only renders what it is given. Polling continues on every screen, which is also what makes
// the "a cycle is running" line in the header possible -- the Founder can be on Portfolio and
// still see that something is in flight.
const POLL_MS = 3000;
// Long enough to cover a Render cold start on the first tap of the day (the hosted web
// service sleeps), short enough that a genuinely dead request still surfaces as an error.
const START_TIMEOUT_MS = Math.max(COMMAND_TIMEOUT_MS || 30000, 45000);

export function useCycleRun() {
  const [cycle, setCycle] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);
  const [lastChecked, setLastChecked] = useState(null);
  // A ref as well as state: the poll timer closes over its own scope, so reading `cycle`
  // from state inside it would capture a stale value forever.
  const activeCycleId = useRef(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const poll = useCallback(async () => {
    try {
      const id = activeCycleId.current;
      const path = id ? `/cycle-run?cycle_id=${encodeURIComponent(id)}` : '/cycle-run';
      const result = await apiRequest(path);
      if (!mounted.current) return null;
      setCycle(result);
      setLastChecked(new Date());
      setError(null);
      if (result?.cycle_id) activeCycleId.current = result.cycle_id;
      return result;
    } catch (err) {
      if (!mounted.current) return null;
      // A failed poll is not a failed cycle -- the run continues on the server. Say that,
      // rather than letting the Founder assume his cycle died because the phone blinked.
      setError(`Could not check progress: ${err.message}`);
      return null;
    }
  }, []);

  // Fetch the latest run once at app start, so the screen is never blank on first open and
  // an already-running cycle (started before the app was opened) is picked up immediately.
  useEffect(() => {
    poll();
  }, [poll]);

  useEffect(() => {
    if (!cycle || isTerminal(cycle.status)) return undefined;
    const timer = setInterval(poll, POLL_MS);
    return () => clearInterval(timer);
  }, [cycle, poll]);

  const start = useCallback(
    async (scope) => {
      setStarting(true);
      setError(null);
      try {
        const result = await apiRequest('/run-cycle', {
          method: 'POST',
          body: JSON.stringify({ scope, trigger_source: 'app' }),
          timeoutMs: START_TIMEOUT_MS,
        });
        if (!mounted.current) return;
        if (result?.status === 'already_running') {
          setError(result.message || 'A cycle is already running.');
        }
        if (result?.cycle_id) {
          activeCycleId.current = result.cycle_id;
          await poll();
        }
      } catch (err) {
        if (mounted.current) setError(`Could not start the cycle: ${err.message}`);
      } finally {
        if (mounted.current) setStarting(false);
      }
    },
    [poll]
  );

  const running = Boolean(cycle && cycle.status === 'running');
  const steps = cycle?.steps || [];
  const currentStep = currentStepOf(steps);

  return {
    cycle,
    steps,
    currentStep,
    running,
    starting,
    busy: starting || running,
    error,
    lastChecked,
    start,
    refresh: poll,
  };
}

// Re-exported so App.js has a single import for the whole feature. The implementation lives
// in lib/cycleProgress.js because that folder is where pure, node-testable logic goes.
export { cycleProgressLabel };
