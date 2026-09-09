const labels = {
  'Check what we actually hold against Kraken': 'Check Kraken positions',
  'Refresh the list of coins we are allowed to trade': 'Refresh eligible coins',
  'Get fresh prices, liquidity and news for each coin': 'Refresh market evidence',
  'Research and score every coin': 'Research crypto candidates',
  'Check each idea against the two rules': 'Apply trading rules',
  'Place any crypto orders': 'Review & place eligible crypto orders',
  'Research shares': 'Research share candidates',
  'Place any share orders': 'Review & place eligible share orders',
};
function cycleStepLabel(label) { return Object.hasOwn(labels, label) ? labels[label] : label; }
module.exports = { cycleStepLabel };
