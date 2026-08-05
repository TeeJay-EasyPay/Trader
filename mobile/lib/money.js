function brokerKey(value) {
  return String(value || 'All').toLowerCase().replace(/[\s_-]+/g, '');
}

// AT-ED-017 (Founder request, 2026-08-05): a negative amount previously formatted as "$-500" (the
// minus sign landing after the currency symbol, from toLocaleString's own "-500" output being
// pasted straight after "$"). Moved the sign in front of the symbol ("-$500") so combined-currency
// totals (see lib/portfolioPosition.js's *ByCurrency helpers) can be passed a raw signed number
// directly, instead of every call site needing its own abs()/sign-word workaround.
function money(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const number = Number(value);
  const sign = number < 0 ? '-' : '';
  return `${sign}$${Math.abs(number).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function gbp(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const number = Number(value);
  const sign = number < 0 ? '-' : '';
  return `${sign}£${Math.abs(number).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
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

const CURRENCY_SYMBOLS = { USD: '$', GBP: '£' };

// AT-ED-017 (Founder request, 2026-08-05): "I should have 2 totals, one in pounds and one in
// dollars" - formats a {currency: amount} map (see lib/portfolioPosition.js's
// sumBrokerFieldByCurrency() and friends) as "$X + £Y", two honest per-currency totals instead of
// one blended number wearing the wrong symbol on part of it. Returns null only when there is no
// real evidence in any currency - a single-currency map still returns just that one formatted
// total, not a fabricated "+ £0". Each entry's own sign picks the join operator ("-" instead of
// "+" before a negative one) so a negative second total reads "£X - £Y", never "£X + -£Y".
function formatByCurrency(totals) {
  const order = ['USD', 'GBP', ...Object.keys(totals || {}).filter((currency) => currency !== 'USD' && currency !== 'GBP')];
  const entries = order
    .filter((currency) => totals?.[currency] !== undefined && totals[currency] !== null)
    .map((currency) => {
      const number = Number(totals[currency]);
      const symbol = CURRENCY_SYMBOLS[currency] || `${currency} `;
      return { negative: number < 0, text: `${symbol}${Math.abs(number).toLocaleString(undefined, { maximumFractionDigits: 2 })}` };
    });
  if (!entries.length) {
    return null;
  }
  return entries.reduce((result, entry, index) => (
    index === 0
      ? (entry.negative ? `-${entry.text}` : entry.text)
      : `${result} ${entry.negative ? '-' : '+'} ${entry.text}`
  ), '');
}

// AT-ED-017 (Founder request, 2026-08-05): "Today is up $X" previously blended Alpaca (USD) and
// Kraken (GBP) into one number under a single $ sign. Builds one real sentence per broker instead
// - shared by lib/founderEvidenceMapping.js's founderHeadline() (the Executive Summary's opening
// line) and screens/ExecutiveBriefing.js's Current Position card, so the two don't duplicate (and
// risk drifting apart from) the same logic. `brokers` can be either the raw evidence.brokers rows
// or the mapped status.brokers rows - both carry a real `broker` name field; `field` names which
// money field to read off each ('day_pnl' vs 'todays_pnl' depending on which shape is passed).
function brokerMoneySentence(brokers, field) {
  const list = (brokers || []).filter((broker) => broker?.[field] !== null && broker?.[field] !== undefined && Number.isFinite(Number(broker[field])));
  if (!list.length) {
    return null;
  }
  const sentences = list.map((broker) => {
    const value = Number(broker[field]);
    const label = String(broker.broker || '').toLowerCase() === 'kraken' ? 'Kraken' : 'Alpaca';
    return `${label} is ${value >= 0 ? 'up' : 'down'} ${brokerMoney(broker, Math.abs(value))} today`;
  });
  return `${sentences.join('; ')}.`;
}

module.exports = {
  brokerKey,
  money,
  gbp,
  moneyOrText,
  gbpOrText,
  brokerMoney,
  historyMoneyOrText,
  formatByCurrency,
  brokerMoneySentence,
};
