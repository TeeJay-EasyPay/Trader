const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const babel = require('@babel/core');
const { createRequire } = require('node:module');
const { palette, exchangePalette, exchangeChartColour } = require('./palette');
const { cioGreeting } = require('./cio');

function load(relative, extra = {}) {
  const file = require.resolve(relative), localRequire = createRequire(file), module = { exports: {} };
  vm.runInNewContext(babel.transformFileSync(file, { presets: [require.resolve('babel-preset-expo')] }).code, {
    module, exports: module.exports, require: name => {
      if (name === 'react-native') return { StyleSheet: { create: x => x }, Text: 'Text', View: 'View', Pressable: 'Pressable' };
      if (Object.hasOwn(extra, name)) return extra[name];
      return localRequire(name);
    },
  });
  return module.exports;
}
function luminance(hex) {
  const rgb = hex.slice(1).match(/../g).map(x => parseInt(x, 16) / 255)
    .map(x => x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4);
  return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
}
function contrast(a, b) {
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
}
test('brand cards stay distinct; unknown broker gets a neutral palette', () => {
  assert.equal(exchangePalette(' Kraken ').backgroundColor, '#F5F1FF');
  assert.equal(exchangePalette('alpaca').backgroundColor, '#FFF8D9');
  for (const broker of ['future', null, '__proto__']) {
    assert.equal(exchangePalette(broker).backgroundColor, '#F4F6F8');
  }
});
test('white racing-green controls and dark card text meet AA text contrast', () => {
  for (const green of [palette.primary, palette.pressed]) assert.ok(contrast('#FFFFFF', green) >= 4.5);
  for (const bg of [palette.canvas, palette.greeting, exchangePalette('kraken').backgroundColor, exchangePalette('alpaca').backgroundColor]) {
    assert.ok(contrast(palette.ink, bg) >= 4.5);
    assert.ok(contrast('#476582', bg) >= 4.5);
  }
});
test('selected navigation, Standup and primary actions share racing green', () => {
  const { styles } = load('../styles');
  for (const key of ['primaryTabActive', 'activeTab', 'primary', 'standupModeActive', 'standupStart', 'standupSend']) {
    assert.equal(styles[key].backgroundColor, palette.primary);
  }
  assert.notEqual(styles.danger.backgroundColor, palette.primary);
  assert.notEqual(styles.warn.backgroundColor, palette.primary);
});
test('pressed primary buttons stay legible and disabled/icon controls retain their styles', () => {
  const { styles } = load('../styles');
  const { Button } = load('../components/shared/Button', { '../../styles': { styles } });
  const button = Button({ label: 'Continue' });
  assert.ok(button.props.style({ pressed: true }).includes(styles.controlPressed));
  assert.equal(button.props.children.props.style[0].color, '#ffffff');
  const disabled = Button({ label: 'Continue', disabled: true });
  assert.equal(disabled.props.disabled, true);
  assert.ok(!disabled.props.style({ pressed: true }).includes(styles.controlPressed));
  const icon = Button({ label: 'Mic', icon: true });
  assert.ok(icon.props.style({ pressed: true }).includes(styles.iconButton));
});
test('the greeting spells the founder name Tarik, never Tarek', () => {
  assert.equal(cioGreeting({ getHours: () => 14 }), 'Good afternoon Tarik.');
});
test('exchange chart strokes remain visible on their tinted cards', () => {
  for (const broker of ['kraken', 'alpaca', 'future']) {
    assert.ok(contrast(exchangeChartColour(broker), exchangePalette(broker).backgroundColor) >= 3);
  }
});
