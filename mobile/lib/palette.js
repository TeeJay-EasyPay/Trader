'use strict';

// Presentation only. Broker identity colours never indicate profit or readiness.
const palette = Object.freeze({
  canvas: '#FFFCF7', primary: '#004225', pressed: '#00351D',
  ink: '#16324F', greeting: '#FFF2DD', greetingBorder: '#F5D5A1',
});
const exchanges = Object.freeze({
  kraken: Object.freeze({ backgroundColor: '#F5F1FF', borderColor: '#D8CBFF' }),
  alpaca: Object.freeze({ backgroundColor: '#FFF8D9', borderColor: '#E8C85B' }),
});
const fallback = Object.freeze({ backgroundColor: '#F4F6F8', borderColor: '#D5DCE3' });
function exchangePalette(broker) {
  const key = String(broker || '').trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(exchanges, key) ? exchanges[key] : fallback;
}
function exchangeChartColour(broker) {
  const key = String(broker || '').trim().toLowerCase();
  return key === 'kraken' ? '#7352C7' : key === 'alpaca' ? '#9A6B00' : '#476582';
}
module.exports = { palette, exchangePalette, exchangeChartColour };
