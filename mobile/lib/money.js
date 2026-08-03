function brokerKey(value) {
  return String(value || 'All').toLowerCase().replace(/[\s_-]+/g, '');
}

function money(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function gbp(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  return `£${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function moneyOrText(value) {
  if (typeof value === 'string' && value.startsWith('Not available')) {
    return value;
  }
  return money(value);
}

function gbpOrText(value) {
  if (typeof value === 'string' && value.startsWith('Not available')) {
    return value;
  }
  return gbp(value);
}

function brokerMoney(broker, value) {
  return String(broker?.broker || '').toLowerCase() === 'kraken' ? gbpOrText(value) : moneyOrText(value);
}

function historyMoneyOrText(selectedExchange, value) {
  return brokerKey(selectedExchange) === 'kraken' ? gbpOrText(value) : moneyOrText(value);
}

module.exports = {
  brokerKey,
  money,
  gbp,
  moneyOrText,
  gbpOrText,
  brokerMoney,
  historyMoneyOrText,
};
