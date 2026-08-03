// Report evidence card, shared by the Dashboard and Portfolio screens.
// Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

const React = require('react');
const { Linking, Text, View } = require('react-native');
const { styles } = require('../styles');
const { TextBlock, Button } = require('./shared');
const { notAvailable } = require('../lib/notAvailable');
const { absoluteApiUrl } = require('../api/client');

function ReportPanel({ report }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{notAvailable(report.report_type).toUpperCase()} report - {notAvailable(report.broker)} - {notAvailable(report.date)}</Text>
      <Text style={styles.bodyText}>{notAvailable(report.summary)}</Text>
      {report.report_url ? (
        <View style={styles.buttonGrid}>
          <Button label="Open Report" onPress={() => Linking.openURL(absoluteApiUrl(report.report_url))} />
        </View>
      ) : null}
      <TextBlock label="Report" value={report.report_markdown} />
      {report.path ? <Text style={styles.smallText}>Saved: {report.path}</Text> : null}
    </View>
  );
}

module.exports = { ReportPanel };
