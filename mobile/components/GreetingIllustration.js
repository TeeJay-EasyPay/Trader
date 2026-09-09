const React = require('react');
const { Image, View, StyleSheet } = require('react-native');

function artworkSize(width, height) {
  const scale = Math.max(width / 2172, height / 724);
  return { width: 2172 * scale, height: 724 * scale };
}

// Bundled background image: no weather feed or runtime network request.
function GreetingIllustration({ fadeToCream = false } = {}) {
  const [size, setSize] = React.useState(null);
  // Uniform scaling preserves a circular sun on folded and unfolded displays.
  // Pin the artwork to the top-right so cropping never removes the sun.
  return <View style={[StyleSheet.absoluteFillObject, { overflow: 'hidden' }]} pointerEvents="none"
    accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
    onLayout={({ nativeEvent: { layout } }) => setSize(artworkSize(layout.width, layout.height))}>
    <Image source={require('../assets/greeting-sun-cloud.png')} resizeMode="cover"
      style={size ? { position: 'absolute', top: 0, right: 0, ...size } : { ...StyleSheet.absoluteFillObject, width: '100%', height: '100%' }} />
    {fadeToCream && Array.from({ length: 32 }, (_, i) => <View key={i} style={{ position: 'absolute', left: 0, right: 0,
      bottom: i * 3, height: 3.5, backgroundColor: `rgba(255,246,231,${1 - i / 32})` }} />)}
  </View>;
}
module.exports = { GreetingIllustration, artworkSize };
