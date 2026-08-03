import React from 'react';
import { Text, View } from 'react-native';
import { styles } from '../../styles';
import { notAvailable } from '../../lib/notAvailable';

export function Metric({ label, value }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{notAvailable(value)}</Text>
    </View>
  );
}
