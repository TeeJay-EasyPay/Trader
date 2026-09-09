'use strict';
const React = require('react');
const { useEffect, useState } = React;
const { Text, View, ScrollView, TouchableOpacity, StyleSheet } = require('react-native');
const { Section, Button } = require('./shared');
const { styles } = require('../styles');
const { apiRequest } = require('../api/client');
const { seriesFor, outcomeBuckets, lineGeometry, loadTrends } = require('../lib/portfolioTrends');

const money = (n, currency) => typeof n === 'number' && Number.isFinite(n)
  ? `${currency === 'GBP' ? '£' : '$'}${n.toFixed(2)}` : 'Unavailable';
const dateLabel = date => `${date.slice(8)}/${date.slice(5, 7)}`;
const s = StyleSheet.create({
  card: { backgroundColor: '#101d30', borderColor: '#29405b', borderWidth: 1, borderRadius: 16, padding: 14, marginTop: 14 },
  title: { color: '#f1f5f9', fontSize: 19, fontWeight: '700', marginBottom: 6 },
  label: { color: '#cbd5e1', fontSize: 13, marginVertical: 5 },
  value: { color: '#f8fafc', fontSize: 26, fontWeight: '700', marginBottom: 4 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginVertical: 8 },
  chip: { paddingHorizontal: 13, paddingVertical: 11, borderRadius: 10, backgroundColor: '#1d3048' },
  selected: { backgroundColor: '#285982', borderColor: '#70c9fa', borderWidth: 1 },
  chipText: { color: '#f1f5f9', fontWeight: '600' },
  axis: { flexDirection: 'row', justifyContent: 'space-between' },
  plot: { height: 126, marginHorizontal: 5, borderBottomColor: '#456079', borderBottomWidth: 1 },
  segment: { position: 'absolute', height: 2, backgroundColor: '#60c7fa' },
  dot: { position: 'absolute', width: 6, height: 6, borderRadius: 3, backgroundColor: '#60c7fa' },
  flow: { backgroundColor: '#facc15', width: 9, height: 9, borderRadius: 2 },
  bars: { flexDirection: 'row', alignItems: 'flex-end', height: 95, gap: 3 },
  bar: { width: 8, borderTopLeftRadius: 2, borderTopRightRadius: 2 },
  bin: { alignItems: 'center', marginRight: 12, minWidth: 36 },
});

function Choice({ value, selected, onPress }) {
  return <TouchableOpacity accessibilityRole="button" accessibilityState={{ selected }} onPress={onPress} style={[s.chip, selected && s.selected]}><Text style={s.chipText}>{value}</Text></TouchableOpacity>;
}

function ValueChart({ rows, currency }) {
  const [width, setWidth] = useState(260);
  const [chosen, setChosen] = useState(null);
  const graph = lineGeometry(rows, width, 126);
  const valid = rows.filter(row => typeof row.value === 'number');
  if (!valid.length) return <Text style={s.label}>No reliable value history yet. Missing values are not zero.</Text>;
  const latest = valid[valid.length - 1];
  const detail = rows.find(row => row.date === chosen) || latest;
  return <View>
    <Text style={s.value}>{money(latest.value, currency)}</Text>
    <Text style={s.label}>Latest recorded value · {dateLabel(latest.date)}</Text>
    <View style={s.axis}><Text style={s.label}>{money(graph.max, currency)} high</Text><Text style={s.label}>{money(graph.min, currency)} low</Text></View>
    <View style={s.plot} onLayout={event => setWidth(Math.max(20, event.nativeEvent.layout.width - 8))} accessible accessibilityLabel={`Account value history. ${valid.length} observations. Latest ${money(latest.value, currency)}. High ${money(graph.max, currency)}. Low ${money(graph.min, currency)}.`}>
      {graph.segments.map((seg, i) => <View key={i} style={[s.segment, { left: seg.x - seg.length / 2, top: seg.y, width: seg.length, transform: [{ rotate: `${seg.angle}rad` }] }]} />)}
      {graph.points.filter(p => p.y !== null).map(p => <TouchableOpacity key={p.date} onPress={() => setChosen(p.date)} hitSlop={{ top: 8, bottom: 8, left: 5, right: 5 }} accessibilityLabel={`${p.date}: ${money(p.value, currency)}`} style={[s.dot, p.flow ? s.flow : null, { left: p.x - 3, top: p.y - 3 }]} />)}
    </View>
    <View style={s.axis}><Text style={s.label}>{dateLabel(rows[0].date)}</Text><Text style={s.label}>{dateLabel(rows[rows.length - 1].date)}</Text></View>
    <Text style={s.label}>{dateLabel(detail.date)}: {money(detail.value, currency)}{detail.flow ? ` · allocation change ${detail.flow > 0 ? '+' : ''}${money(detail.flow, currency)}` : ''}</Text>
    {valid.length === 1 && <Text style={s.label}>One observation so far; more history is needed for a trend.</Text>}
    <Text style={s.label}>Last observation each UTC day; today is partial. Gaps mean missing data.</Text>
  </View>;
}

function BrokerTrends({ broker, days, weekly, asOf }) {
  const netKnown = broker.pnl_basis === 'net_after_fees';
  const series = seriesFor(broker, days, asOf);
  const bins = outcomeBuckets(series.outcomes, days, asOf, weekly);
  const [selected, setSelected] = useState(null);
  const totals = bins.reduce((acc, b) => { for (const key of Object.keys(acc)) acc[key] += b[key]; return acc; }, { wins: 0, losses: 0, breakeven: 0, unknown: 0, net_pnl: 0 });
  const peak = Math.max(1, ...bins.flatMap(b => [b.wins, b.losses]));
  const detail = bins.find(b => b.date === selected);
  return <View style={s.card}>
    <Text style={s.title}>{broker.broker === 'kraken' ? 'Kraken · GBP' : 'Alpaca · USD'}</Text>
    <Text style={s.label}>{broker.broker === 'kraken' ? 'AI trading capital only · personal holdings excluded' : 'Alpaca account value · cash plus investments'}{broker.account_mode ? ` · ${broker.account_mode}` : ''}</Text>
    <Text style={s.title}>Account value</Text>
    {broker.value_status === 'ok' ? <ValueChart rows={series.values} currency={broker.currency} /> : <Text style={s.label}>Value history is temporarily unavailable.</Text>}
    <Text style={s.label}>{broker.broker === 'kraken' ? 'Yellow markers show recorded allocation changes, not trading profit. Earlier unrecorded funding is not inferred.' : 'Deposit and withdrawal history is unavailable. Balance changes are not necessarily trading profit.'}</Text>
    <Text style={[s.title, { marginTop: 18 }]}>{broker.broker === 'kraken' ? 'Completed AI trades' : 'Completed recorded trades'}</Text>
    {broker.outcome_status !== 'ok' ? <Text style={s.label}>Trade outcomes are temporarily unavailable.</Text> : <View>
      <Text style={s.label}>{netKnown ? 'After recorded fees' : 'Provisional: before unreconciled fees'} · {weekly ? 'weekly, Monday start' : 'daily'} · UTC</Text>
      <Text style={s.label}>Won {totals.wins} · Lost {totals.losses} · Break-even {totals.breakeven} · Unknown {totals.unknown}</Text>
      <Text style={s.value}>{money(totals.net_pnl, broker.currency)} {netKnown ? 'net' : 'recorded P&L'}</Text>
      <Text style={s.label}>Green: won · Red: lost. Counts, not profit amounts.</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={true} accessibilityLabel="Daily or weekly completed trade counts">
        {bins.map(bin => <TouchableOpacity key={bin.date} style={s.bin} onPress={() => setSelected(bin.date)} accessibilityLabel={`${bin.date}: ${bin.wins} won, ${bin.losses} lost, ${bin.breakeven} break-even, ${bin.unknown} unknown`}>
          <View style={s.bars}><View style={[s.bar, { height: bin.wins / peak * 84, backgroundColor: '#42d6a4' }]} /><View style={[s.bar, { height: bin.losses / peak * 84, backgroundColor: '#fb7185' }]} /></View>
          <Text style={s.label}>{dateLabel(bin.date)}</Text>
        </TouchableOpacity>)}
      </ScrollView>
      <Text style={s.label}>{detail ? `${detail.date}: ${detail.wins} won / ${detail.losses} lost · ${money(detail.net_pnl, broker.currency)} ${netKnown ? 'net' : 'before unreconciled fees'}` : 'Tap a bar for details; swipe sideways for more dates.'}</Text>
      {!netKnown && <Text style={s.label}>Alpaca's historical result record does not establish all fees. Small recorded wins may become losses after fees; these are not verified net wins.</Text>}
      {!totals.wins && !totals.losses && !totals.breakeven && !totals.unknown && <Text style={s.label}>No completed trades recorded in this period.</Text>}
      {!!totals.unknown && <Text style={s.label}>Net total excludes outcomes whose profit is unknown.</Text>}
      <Text style={s.label}>Open positions are excluded. First and current weeks may be partial. Historical results may include earlier account modes.</Text>
    </View>}
  </View>;
}

function PortfolioTrends({ request = apiRequest }) {
  const [data, setData] = useState(null), [error, setError] = useState(null);
  const [days, setDays] = useState(30), [weekly, setWeekly] = useState(true), [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    loadTrends(request).then(value => { if (active) { setData(value); setError(null); } }).catch(() => { if (active) setError('History could not be loaded. Your trading is unaffected.'); });
    return () => { active = false; };
  }, [request, retry]);
  return <Section title="Your progress">
    <Text style={styles.bodyText}>See how each account is changing and how completed trades performed.</Text>
    <View style={s.row}>{[7, 30, 90].map(n => <Choice key={n} value={`${n} days`} selected={days === n} onPress={() => setDays(n)} />)}</View>
    <View style={s.row}><Choice value="Daily trades" selected={!weekly} onPress={() => setWeekly(false)} /><Choice value="Weekly trades" selected={weekly} onPress={() => setWeekly(true)} /></View>
    {error ? <View><Text style={styles.bodyText}>{error}</Text><Button label="Retry history" onPress={() => setRetry(retry + 1)} /></View> : !data ? <Text style={styles.bodyText}>Loading compact history…</Text> : <View>
      <Text style={styles.smallText}>Updated {data.as_of.replace('T', ' ').slice(0, 16)} UTC · cached up to 10 minutes</Text>
      {data.brokers.map(broker => <BrokerTrends key={broker.broker} broker={broker} days={days} weekly={weekly} asOf={data.as_of} />)}
    </View>}
  </Section>;
}
module.exports = { PortfolioTrends, BrokerTrends };
