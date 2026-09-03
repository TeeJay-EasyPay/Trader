import React from 'react';
import { Text, TouchableOpacity } from 'react-native';
import { styles } from '../../styles';

// 2026-09-04, Founder-reported: "the microphone icon on the speak button is barely visible.
// The button is too dark, and I can't see what the microphone looks like apart from maybe the
// blue bulb bit on the end of it."
//
// He was right, and the cause is that an emoji paints its OWN colours -- it ignores the white
// buttonText colour entirely. A dark-bodied microphone on a #57606a button leaves only its
// blue tip visible. So an icon button gets a light background for the glyph to sit on, and a
// larger size, rather than being squeezed into a style built for 13px uppercase words.
export function Button({ label, onPress, tone = 'primary', disabled = false, icon = false, accessibilityLabel }) {
  return (
    <TouchableOpacity
      style={[styles.button, styles[tone], icon && styles.iconButton, disabled && styles.disabledButton]}
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel || (typeof label === 'string' ? label : undefined)}
    >
      <Text style={[styles.buttonText, icon && styles.iconButtonText]}>{label}</Text>
    </TouchableOpacity>
  );
}
