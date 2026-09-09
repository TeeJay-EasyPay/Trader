const React = require('react');
const { Image, StyleSheet } = require('react-native');

// Bundled background image: no weather feed or runtime network request.
function GreetingIllustration() {
  return <Image source={require('../assets/greeting-sun-cloud.png')} resizeMode="stretch" style={StyleSheet.absoluteFillObject} pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" />;
}
module.exports = { GreetingIllustration };
