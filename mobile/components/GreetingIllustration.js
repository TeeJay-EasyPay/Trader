const React = require('react');
const { View, StyleSheet } = require('react-native');

// Decorative native shapes: no remote image, weather feed, or database request.
const s = StyleSheet.create({
  scene: { width: 92, height: 74, marginLeft: 8 },
  glow: { position: 'absolute', width: 66, height: 66, borderRadius: 33, backgroundColor: '#FFE6A9', right: 0, top: 0 },
  sun: { position: 'absolute', width: 44, height: 44, borderRadius: 22, backgroundColor: '#F5BD55', right: 11, top: 10 },
  cloud: { position: 'absolute', left: 0, bottom: 5, width: 82, height: 29, borderRadius: 20, backgroundColor: '#FFFEFB', borderBottomWidth: 3, borderBottomColor: '#E9E5DB' },
  puff: { position: 'absolute', backgroundColor: '#FFFEFB', borderRadius: 25 },
  left: { left: 10, bottom: 18, width: 37, height: 32 },
  right: { left: 33, bottom: 18, width: 38, height: 42 },
});
function GreetingIllustration() {
  return <View style={s.scene} pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
    <View style={s.glow} /><View style={s.sun} />
    <View style={[s.puff, s.left]} /><View style={[s.puff, s.right]} /><View style={s.cloud} />
  </View>;
}
module.exports = { GreetingIllustration };
