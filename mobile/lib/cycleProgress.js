'use strict';

// 2026-08-29, Founder-reported: "when I go to the executive briefing and come back it stops.
// i then don't know if it actually stopped or it is still running in the background."
//
// The cycle was never stopping -- it runs in a thread on the server. What stopped was the
// watching. Part of the fix is a line shown on EVERY screen naming exactly which step is in
// flight, so "is it still running?" stops being a question the Founder has to ask.
//
// Pure function, kept in lib/ rather than in the hook, so it can be tested with plain node
// the way the rest of this folder is.

const TERMINAL_STATUSES = ['completed', 'failed', 'none'];

function isTerminal(status) {
  return TERMINAL_STATUSES.includes(String(status || ''));
}

/**
 * One line describing a cycle in flight, or null when there is nothing to announce.
 *
 * Returns null for a finished cycle on purpose: the header must not keep advertising a run
 * that ended ten minutes ago, or the Founder learns to ignore the line and it stops working
 * as a signal at exactly the moment it matters.
 */
function cycleProgressLabel(state) {
  const { running, starting, steps, currentStep } = state || {};
  if (starting) return 'Starting a cycle...';
  if (!running) return null;
  if (!currentStep || !currentStep.label) return 'Cycle running...';
  const total = Array.isArray(steps) && steps.length ? steps.length : '?';
  return `Cycle running - step ${currentStep.seq} of ${total}: ${currentStep.label}`;
}

/** The step currently in flight, which is the only one worth naming in a one-line summary. */
function currentStepOf(steps) {
  if (!Array.isArray(steps)) return null;
  return steps.find((step) => step && step.status === 'running') || null;
}

module.exports = { cycleProgressLabel, currentStepOf, isTerminal, TERMINAL_STATUSES };
