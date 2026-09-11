'use strict';

function confirmStopTrading(alert, onCommand) {
  if (typeof onCommand !== 'function') return;
  alert.alert(
    'Stop trading on all accounts?',
    'Are you sure you want to stop trading? This sends the global stop command. It does not sell all open positions.',
    [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Stop trading', style: 'destructive', onPress: () => onCommand('/stop-trading') },
    ],
    { cancelable: true },
  );
}

module.exports = { confirmStopTrading };
