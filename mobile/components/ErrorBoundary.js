// AT-ED-015.1 Section 5: a screen-level error boundary. Defence-in-depth, not a substitute for
// fixing the actual defect - the AT-ED-015.1 white-screen root cause (a TypeError thrown during
// PrincipalOpportunitiesSection's render - see Root_Cause_Analysis.md) is fixed at its source in
// lib/principalOpportunities.js. This exists so that ANY future unforeseen render exception in
// the Executive Briefing subtree unmounts only that subtree, never the whole app: the header,
// navigation, and every other screen stay mounted and usable, and the Founder sees a calm,
// business-language fallback instead of a blank white screen.
//
// React error boundaries must be class components - there is no hook equivalent as of the React
// version this project uses (`getDerivedStateFromError`/`componentDidCatch` are class-only
// lifecycle methods).

import React from 'react';
import { Text, View } from 'react-native';
import { styles } from '../styles';
import { Button } from './shared';

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, diagnosticId: null };
  }

  static getDerivedStateFromError() {
    // A short, non-sensitive identifier the Founder can quote when reporting the issue - never
    // the error message or stack itself (Section 5: "never expose stack traces or raw
    // implementation details to the Founder").
    const diagnosticId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    return { hasError: true, diagnosticId };
  }

  componentDidCatch(error, info) {
    // Logged for engineering diagnosis only (Section 5: "Log the original component error for
    // engineering diagnosis") - this is the ONLY place the real error/stack is referenced
    // anywhere in this component; render() below never touches `error` or `info`.
    console.error(`[ErrorBoundary:${this.props.label || 'unknown'}]`, error, info && info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false, diagnosticId: null });
    if (this.props.onRetry) {
      this.props.onRetry();
    }
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }
    return (
      <View style={styles.summaryCard}>
        <Text style={styles.cardTitle}>{this.props.title || 'This section could not be displayed.'}</Text>
        <Text style={styles.bodyText}>
          {this.props.message || 'Something went wrong while preparing this screen. Your other data and navigation are unaffected.'}
        </Text>
        <View style={styles.buttonGrid}>
          <Button label="Retry" onPress={this.handleRetry} />
          {this.props.onOpenOperations ? <Button label="Open Operations" tone="neutral" onPress={this.props.onOpenOperations} /> : null}
        </View>
        <Text style={styles.smallText}>Diagnostic ID: {this.state.diagnosticId}</Text>
      </View>
    );
  }
}
