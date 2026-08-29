import React from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import { styles } from '../styles';
import { Section } from '../components/shared/Section';
import { Button } from '../components/shared/Button';
import { StatusPill } from '../components/shared/StatusPill';

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
  if (status === 'completed') return 'Done';
  if (status === 'failed') return 'Failed';
  if (status === 'running') return 'Running';
  return 'Waiting';
}

export function RunCycleScreen({ cycleRun }) {
  const { cycle, steps, running, starting, busy, error, lastChecked, start } = cycleRun;

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
              {starting
                ? 'Starting the cycle...'
                : 'Cycle running on the server. You can switch screens - it keeps going and keeps updating.'}
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
