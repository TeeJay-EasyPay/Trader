const React = require('react');
const { Image, StyleSheet } = require('react-native');

// Bundled background image: no weather feed or runtime network request.
function GreetingIllustration() {
  // Image supplies the asset's intrinsic width/height before applying our style.
  // Insets alone do not override those dimensions: Android clipped a full-size
  // 2172px image to the card, hiding the sun/clouds at the far right.
  return <Image source={require('../assets/greeting-sun-cloud.png')} resizeMode="stretch" style={{ ...StyleSheet.absoluteFillObject, width: '100%', height: '100%' }} pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" />;
}
module.exports = { GreetingIllustration };
