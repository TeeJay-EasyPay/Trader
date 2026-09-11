'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { confirmStopTrading } = require('./confirmStopTrading');

test('opening or cancelling confirmation never sends a command; confirmation sends stop only', () => {
  const commands = [];
  let dialog;
  confirmStopTrading({ alert: (...args) => { dialog = args; } }, command => commands.push(command));
  assert.deepEqual(commands, []);
  assert.equal(dialog[2][0].style, 'cancel');
  assert.equal(dialog[2][0].onPress, undefined);
  assert.equal(dialog[3].cancelable, true);
  dialog[2][1].onPress();
  assert.deepEqual(commands, ['/stop-trading']);
});

test('no command handler means no dialog', () => {
  confirmStopTrading({ alert: () => assert.fail('unexpected dialog') });
});

test('briefing only exposes confirmed emergency stop in founder controls', () => {
  const source = fs.readFileSync(path.join(__dirname, '../screens/ExecutiveBriefing.js'), 'utf8');
  assert.ok(source.includes('confirmStopTrading(Alert, onCommand)'));
  assert.ok(source.includes('label="Emergency Stop All"'));
  assert.ok(!source.includes('label="Refresh"'));
  assert.ok(!source.includes('label="Run Analysis"'));
});
