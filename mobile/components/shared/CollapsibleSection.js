import React, { useState } from 'react';
import { Text, TouchableOpacity, View } from 'react-native';
import { styles } from '../../styles';
import { StatusPill } from './StatusPill';

// Same visual language as Section, but starts collapsed and can be expanded on tap -- used to
// group Command-screen detail out of the way by default so the top summary card answers the
// Founder's question at a glance instead of scrolling past a wall of always-open cards.
export function CollapsibleSection({ title, subtitle, defaultExpanded = false, badge, children }) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  return (
    <View style={styles.section}>
      <TouchableOpacity onPress={() => setExpanded((value) => !value)} style={styles.collapsibleHeader}>
        <View style={styles.collapsibleHeaderText}>
          <Text style={styles.sectionTitle}>{title}</Text>
          {subtitle ? <Text style={styles.smallText}>{subtitle}</Text> : null}
        </View>
        {badge ? <StatusPill label={badge.label} tone={badge.tone} /> : null}
        <Text style={styles.collapsibleChevron}>{expanded ? '▲' : '▼'}</Text>
      </TouchableOpacity>
      {expanded ? <View style={styles.collapsibleBody}>{children}</View> : null}
    </View>
  );
}
