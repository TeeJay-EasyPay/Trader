import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import { styles } from '../styles';
import { Section } from '../components/shared/Section';
import { Button } from '../components/shared/Button';
import { StatusPill } from '../components/shared/StatusPill';

const { apiRequest, COMMAND_TIMEOUT_MS } = require('../api/client');

// 2026-08-29, Founder-directed: "add a card to the app UI where I can click on a button for
// it to start a research cycle and potentially trade. the card should show every step of the
// process and it's results as a one line summary along the way and conclusion at the end."
//
// This is its own screen rather than a card on the Executive Briefing. The Briefing has been
// deliberately narrowed twice (seven screens -> three -> two) to answer "how am I doing", and
// a growing step-by-step run log is a different question that needs vertical room while it
// runs. Moving it onto the Briefing later is a small change if the Founder prefers that.
//
// A cycle takes two to four minutes, so the button starts it and this screen polls. It must
// never look frozen: every state below says what is happening and when it last checked.
const POLL_MS = 3000;
// Long enough to cover a Render cold start on the first tap of the day (the free-tier web
// service sleeps), short enough that a genuinely dead request still surfaces as an error.
const START_TIMEOUT_MS = Math.max(COMMAND_TIMEOUT_MS || 30000, 45000);

const TERMINAL = ['completed', 'failed', 'none'];

function stepTone(status) {
  if (status === 'completed') return 'good';
  if (status === 'failed') return 'danger';
  if (status === 'running') return 'warn';
  return 'neutral';
}

function stepMark(status) {
  if (status === 'completed') return 'Done';
  if (status === 'failed') return 'Failed';
  if (status === 'running') return 'Running';
  return 'Waiting';
}

export function RunCycleScreen() {
  const [cycle, setCycle] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);
  const [lastChecked, setLastChecked] = useState(null);
  // Held in a ref as well as state: the polling interval closes over its own scope, and
  // reading `cycle` from state inside it would capture a stale value forever.
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
      return result;
    } catch (err) {
      if (!mounted.current) return null;
      // A failed poll is not a failed cycle -- the run continues on the server. Say so,
      // rather than letting the Founder assume his cycle died because the phone blinked.
      setError(`Could not check progress: ${err.message}`);
      return null;
    }
  }, []);

  // Show the previous run on open, so the screen is never blank and the last result is
  // still readable after the app is reopened.
  useEffect(() => {
    poll().then((result) => {
      if (result?.cycle_id && result.status === 'running') {
        activeCycleId.current = result.cycle_id;
      }
    });
  }, [poll]);

  useEffect(() => {
    if (!cycle || TERMINAL.includes(cycle.status)) return undefined;
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
  const busy = starting || running;

  return (
    <View>
      <Section title="Run a cycle now">
        <Text style={styles.bodyText}>
          Runs the whole process end to end: refresh the market data, research every asset,
          check each idea against the two rules, and place any orders that pass. It normally
          takes two to four minutes. Any trades it makes will appear in Trade History on the
          Portfolio screen.
        </Text>
        <View style={styles.buttonGrid}>
          <Button
            label={busy ? 'Running...' : 'Run everything'}
            onPress={() => start('all')}
            disabled={busy}
          />
          <Button
            label="Crypto only"
            tone="neutral"
            onPress={() => start('crypto')}
            disabled={busy}
          />
        </View>
        {busy && (
          <View style={styles.cycleBusyRow}>
            <ActivityIndicator />
            <Text style={styles.smallText}>
              {starting ? 'Starting the cycle...' : 'Cycle running - this screen updates itself.'}
            </Text>
          </View>
        )}
        {error && <Text style={styles.cycleError}>{error}</Text>}
      </Section>

      {cycle && cycle.status === 'none' && (
        <Section title="No cycle has been run yet">
          <Text style={styles.bodyText}>
            Press "Run everything" above and each step will appear here as it happens.
          </Text>
        </Section>
      )}

      {steps.length > 0 && (
        <Section title="What happened, step by step">
          {steps.map((step) => (
            <View key={step.seq} style={styles.cycleStep}>
              <View style={styles.cycleStepHeader}>
                <Text style={styles.cycleStepLabel}>
                  {step.seq}. {step.label}
                </Text>
                <StatusPill label={stepMark(step.status)} tone={stepTone(step.status)} />
              </View>
              {step.summary ? (
                <Text style={styles.cycleStepSummary}>{step.summary}</Text>
              ) : (
                <Text style={styles.cycleStepPending}>Working on this now...</Text>
              )}
            </View>
          ))}
        </Section>
      )}

      {cycle?.conclusion && (
        <Section title="Conclusion">
          <Text style={styles.cycleConclusion}>{cycle.conclusion}</Text>
          <Text style={styles.smallText}>
            {cycle.status === 'failed'
              ? 'Some steps did not finish. The ones marked Failed above say why.'
              : 'Cycle finished normally.'}
          </Text>
        </Section>
      )}

      {lastChecked && (
        <Text style={styles.smallText}>
          Last checked {lastChecked.toLocaleTimeString()}
          {cycle?.cycle_id ? ` - run ${cycle.cycle_id}` : ''}
        </Text>
      )}
    </View>
  );
}
