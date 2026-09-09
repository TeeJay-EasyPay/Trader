import React, { useState } from 'react';
import { ActivityIndicator, Text, View, TouchableOpacity } from 'react-native';
import { styles } from '../styles';
import { Section } from '../components/shared/Section';
import { Button } from '../components/shared/Button';
import { StatusPill } from '../components/shared/StatusPill';
const { cycleElapsedLabel } = require('../lib/cycleProgress');
const { cycleStepLabel } = require('../lib/cycleStepPresentation');

// 2026-08-29, Founder-directed: "add a card to the app UI where I can click on a button for
// it to start a research cycle and potentially trade. the card should show every step of the
// process and it's results as a one line summary along the way and conclusion at the end."
//
// This is its own screen rather than a card on the Executive Briefing. The Briefing has been
// deliberately narrowed twice (seven screens -> three -> two) to answer "how am I doing", and
// a growing step-by-step run log is a different question that needs vertical room while it
// runs. Moving it onto the Briefing later is a small change if the Founder prefers that.
//
// This component holds NO state of its own. Everything comes from useCycleRun, mounted once
// in App.js, because state kept here was destroyed every time the Founder switched tabs --
// see the hook's own comment for the bug report that caused the change.
function stepTone(status) {
  if (status === 'completed') return 'good';
  if (status === 'failed') return 'danger';
  if (status === 'running') return 'warn';
  return 'neutral';
}

function stepMark(status) {
  if (status === 'completed') return '✓  Done';
  if (status === 'failed') return 'Failed';
  if (status === 'running') return 'Running';
  return 'To do';
}

export function RunCycleScreen({ cycleRun }) {
  const [expandedSteps, setExpandedSteps] = useState({});
  const { cycle, steps, running, starting, busy, error, lastChecked, start } = cycleRun;
  const elapsed = cycleElapsedLabel(cycle, lastChecked);

  return (
    <View>
      <Section title="Run a cycle now">
        <Text style={styles.bodyText}>
          Research and review opportunities. Orders are placed only when the trading rules allow them.
        </Text>
        <View style={styles.cycleWarning}>
          <Text style={styles.cycleWarningIcon} accessible={false}>!</Text>
          <Text style={styles.cycleWarningText}>A cycle may place real orders when live trading is enabled.</Text>
        </View>
        {/* 2026-09-01, Founder-directed: "alpaca should have its own cycle like kraken...
            especially if we are doing test runs after upgrades or updates." One button per
            venue, so a change to one broker can be tested without running the other and
            without waiting on it. The backend already supported an equities-only scope; it
            had simply never been offered here. */}
        <View style={styles.cycleButtonStack}>
          <Button
            label={busy ? 'Running...' : 'Run everything'}
            onPress={() => start('all')}
            disabled={busy}
          />
          <Button
            label="Kraken only"
            tone="neutral"
            onPress={() => start('kraken')}
            disabled={busy}
          />
          <Button
            label="Alpaca only"
            tone="neutral"
            onPress={() => start('alpaca')}
            disabled={busy}
          />
        </View>
        <Text style={styles.smallText}>A run may take 30 minutes or longer. An order is not guaranteed; confirm fills in Portfolio trade history.</Text>
        {busy && (
          <View style={styles.cycleBusyRow}>
            <ActivityIndicator />
            <Text style={styles.smallText}>
              {starting
                ? 'Starting the cycle...'
                : 'Cycle running on the server. You can switch screens - it keeps going and keeps updating.'}
            </Text>
          </View>
        )}
        {elapsed && <Text style={styles.smallText}>{elapsed}</Text>}
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
              <TouchableOpacity style={styles.cycleStepHeader} accessibilityRole="button" accessibilityState={{ expanded: !!expandedSteps[`${cycle?.cycle_id}-${step.seq}`] || step.status === 'failed' || step.status === 'running' }} onPress={() => setExpandedSteps(prev => ({ ...prev, [`${cycle?.cycle_id}-${step.seq}`]: !prev[`${cycle?.cycle_id}-${step.seq}`] }))}>
                <Text style={styles.cycleStepLabel}>
                  {cycleStepLabel(step.label)}
                </Text>
                <StatusPill label={stepMark(step.status)} tone={stepTone(step.status)} />
              </TouchableOpacity>
              {/* The whole plan is written up front, so a step with no summary is either
                  in flight or still queued -- and saying "working on this now" for a step
                  that has not started would be the same overstatement as "step 1 of 1". */}
              {(expandedSteps[`${cycle?.cycle_id}-${step.seq}`] || step.status === 'failed' || step.status === 'running') && (step.summary ? (
                <Text style={styles.cycleStepSummary}>{step.label}{'\n'}{step.summary}</Text>
              ) : (
                <Text style={styles.cycleStepPending}>
                  {step.status === 'running' ? 'Working on this now...' : 'Not started yet.'}
                </Text>
              ))}
            </View>
          ))}
          <Text style={styles.smallText}>Tap a step for its full result. Running steps and errors stay visible.</Text>
        </Section>
      )}

      {cycle?.conclusion && !running && (
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
