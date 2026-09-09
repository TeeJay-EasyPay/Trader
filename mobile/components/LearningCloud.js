const React = require('react');
const { View } = require('react-native');

// Native decorative artwork: fixed proportions at every display width, no download.
function LearningCloud({ wide = false }) {
  const cloud = { position: 'absolute', backgroundColor: '#FFFEF7', borderRadius: 60,
    shadowColor: '#CABD9E', shadowOpacity: 0.18, shadowRadius: 10, shadowOffset: { width: 0, height: 5 }, elevation: 2 };
  return <View pointerEvents="none" accessible={false} importantForAccessibility="no-hide-descendants"
    style={{ position: 'absolute', right: wide ? 14 : -40, top: wide ? 10 : -24, width: 152, height: 105, opacity: 0.9, transform: [{ scale: wide ? 1.1 : 0.42 }] }}>
    <View style={{ position: 'absolute', width: 52, height: 52, borderRadius: 26, right: 9, top: 2,
      backgroundColor: '#FFD778', borderWidth: 5, borderColor: '#FFE29C' }} />
    <View style={{ ...cloud, width: 76, height: 58, left: 30, top: 25 }} />
    <View style={{ ...cloud, width: 56, height: 46, right: 5, top: 43 }} />
    <View style={{ ...cloud, width: 65, height: 44, left: 3, top: 53 }} />
    <View style={{ ...cloud, width: 123, height: 40, left: 18, top: 58, backgroundColor: '#FFFDF5' }} />
  </View>;
}
module.exports = { LearningCloud };
