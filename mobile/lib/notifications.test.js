// Plain Node assert-based tests for notifications.js - run with
// `node mobile/lib/notifications.test.js`. See that file's module comment for the AT-ED-011.5
// notifications decision this backs (surface in Activity, not remove the fetch).

'use strict';

const assert = require('assert');
const { unreadNotifications, notificationsBadge } = require('./notifications');

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`ok - ${name}`);
  } catch (err) {
    console.error(`FAIL - ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

test('unreadNotifications: empty/null input returns an empty list, not an error', () => {
  assert.deepStrictEqual(unreadNotifications(null), []);
  assert.deepStrictEqual(unreadNotifications([]), []);
});

test('unreadNotifications: queued and sent notifications count as unread', () => {
  const items = [
    { notification_id: 1, delivery_status: 'queued' },
    { notification_id: 2, delivery_status: 'sent' },
  ];
  assert.deepStrictEqual(unreadNotifications(items).map((item) => item.notification_id), [1, 2]);
});

test('unreadNotifications: a row marked read by mark_notifications_read is excluded', () => {
  const items = [
    { notification_id: 1, delivery_status: 'queued' },
    { notification_id: 2, delivery_status: 'read' },
  ];
  assert.deepStrictEqual(unreadNotifications(items).map((item) => item.notification_id), [1]);
});

test('notificationsBadge: all read gives a neutral "All read" badge', () => {
  const badge = notificationsBadge([{ delivery_status: 'read' }]);
  assert.deepStrictEqual(badge, { label: 'All read', tone: 'neutral' });
});

test('notificationsBadge: any unread gives a warn-toned count', () => {
  const badge = notificationsBadge([{ delivery_status: 'read' }, { delivery_status: 'queued' }, { delivery_status: 'queued' }]);
  assert.deepStrictEqual(badge, { label: '2 unread', tone: 'warn' });
});

console.log(`\n${passed} passed`);
