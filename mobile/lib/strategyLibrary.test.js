'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('strategy library keeps historical navigation without suggesting live stage progress', () => {
  const source = fs.readFileSync(path.join(__dirname, '../screens/Learning.js'), 'utf8');
  assert.ok(source.includes('title="Strategy library"'));
  assert.ok(!source.includes("['Research', 'Backtest', 'Shadow', 'Review'].map"));
  assert.ok(source.includes('label="Saved strategies" onPress={() => onOpen(\'strategies\')}'));
  assert.ok(source.includes('label="Past backtests" onPress={() => onOpen(\'tests\')}'));
  assert.ok(source.includes('A saved idea is not approval to trade.'));
  assert.ok(source.includes('Active shadow tests and weekly reviews appear in Experiments above.'));
});
