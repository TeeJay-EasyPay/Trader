const React = require('react');
const { View } = require('react-native');
const { GreetingIllustration } = require('./GreetingIllustration');

// Exact Executive Briefing artwork, using the same aspect-preserving renderer.
function LearningCloud({ wide = false }) {
  return <View pointerEvents="none" accessible={false} importantForAccessibility="no-hide-descendants"
    style={{ position: 'absolute', left: 0, right: 0, top: 0, height: wide ? 160 : 130, overflow: 'hidden' }}>
    <GreetingIllustration fadeToCream />
  </View>;
}
module.exports = { LearningCloud };
