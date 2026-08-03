import React from 'react';
import { Text, TouchableOpacity } from 'react-native';
import { styles } from '../../styles';

export function Button({ label, onPress, tone = 'primary', disabled = false }) {
  return (
    <TouchableOpacity style={[styles.button, styles[tone], disabled && styles.disabledButton]} onPress={onPress} disabled={disabled}>
      <Text style={styles.buttonText}>{label}</Text>
    </TouchableOpacity>
  );
}
