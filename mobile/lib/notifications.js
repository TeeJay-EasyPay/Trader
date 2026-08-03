// Pure presentation logic for Activity's NotificationsCard. Extracted so the AT-ED-011.5
// notifications decision (surface, not remove - see Data_Freshness_Findings.md) is
// unit-testable the same way every other lib/*.js module in this project is.
//
// NOTIFICATION_EVENTS (src/ai_trader/multi_broker.py) has no separate read/acknowledged
// timestamp column - mark_notifications_read() sets delivery_status = 'read' directly, and a
// row otherwise passes through 'queued' then possibly 'sent' (via dispatch_pending_push_
// notifications, once a push has gone out) before a Founder ever opens this screen. "Unread"
// is therefore exactly "not yet marked read", not "not yet pushed".

'use strict';

function unreadNotifications(items) {
  return (items || []).filter((item) => item && item.delivery_status !== 'read');
}

function notificationsBadge(items) {
  const unread = unreadNotifications(items);
  return unread.length
    ? { label: `${unread.length} unread`, tone: 'warn' }
    : { label: 'All read', tone: 'neutral' };
}

module.exports = {
  unreadNotifications,
  notificationsBadge,
};
