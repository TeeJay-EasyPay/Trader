import React from 'react';
import { Text, View } from 'react-native';
import { styles } from '../../styles';

export function Section({ title, children }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}
