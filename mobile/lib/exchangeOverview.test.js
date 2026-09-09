const test = require('node:test');
const assert = require('node:assert/strict');
const { exchangeName, currencyFor, exchangeMoney, activityByExchange } = require('./exchangeOverview');
test('future exchanges and missing currency never get mislabeled as Kraken or USD', () => {
  assert.equal(exchangeName({broker:'third',label:'Third venue'}),'Third venue');
  assert.equal(currencyFor({broker:'third'}),null);
  assert.equal(exchangeMoney(null,'USD'),'Unavailable');
  assert.match(exchangeMoney(100,null),/currency unknown/);
  assert.match(exchangeMoney(100,'EUR'),/€/);
});
test('repeated order observations count once per exchange and research remains checks',()=>{
  const activity={research:[{broker:'kraken',assets_analysed:20,recommendations_created:2}],trades:[{broker:'kraken',external_id:'same',status:'filled'},{broker:'kraken',external_id:'same',status:'filled'},{broker:'alpaca',external_id:'same',status:'filled'},{broker:'kraken',status:'filled'}]};
  assert.deepEqual(activityByExchange(activity,{broker:'kraken'}),{available:true,checks:20,candidates:2,orders:1,fills:1,unidentified:1});
  assert.equal(activityByExchange(null,{broker:'alpaca'}).available,false);
});
