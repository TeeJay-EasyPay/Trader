import React from 'react';
import { Text, View } from 'react-native';
import { styles } from '../../styles';

export function StatusPill({ label, tone = 'neutral' }) {
  const styleName = tone === 'good' ? 'pillGood' : tone === 'warn' ? 'pillWarn' : tone === 'danger' ? 'pillDanger' : 'pillNeutral';
  return (
    <View style={[styles.statusPill, styles[styleName]]}>
      <Text style={[styles.statusPillText, styles[`${styleName}Text`]]}>{label}</Text>
    </View>
  );
}
