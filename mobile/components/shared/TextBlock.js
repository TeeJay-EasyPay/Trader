import React from 'react';
import { Text, View } from 'react-native';
import { styles } from '../../styles';
import { notAvailable } from '../../lib/notAvailable';

export function TextBlock({ label, value }) {
  return (
    <View style={styles.textBlock}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.bodyText}>{notAvailable(value)}</Text>
    </View>
  );
}
