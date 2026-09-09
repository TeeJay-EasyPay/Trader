'use strict';
const React = require('react');
const { useEffect, useState } = React;
const { Text, View, TouchableOpacity, StyleSheet } = require('react-native');
const { Button } = require('./shared');
const { styles } = require('../styles');
const { palette, exchangePalette } = require('../lib/palette');
const { apiRequest } = require('../api/client');
const { seriesFor, outcomeBuckets, loadTrends } = require('../lib/portfolioTrends');
const { accountChart, dateTicks, compactMoney } = require('../lib/chartPresentation');
const { exchangeMoney: money } = require('../lib/exchangeOverview');
const dateLabel = date => new Date(date + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const HEIGHT = 116, AXIS = 57, BAR_HEIGHT = 76;
const s = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 16, padding: 14, marginTop: 14 },
  title: { color: '#16324F', fontSize: 19, fontWeight: '800' },
  label: { color: '#476582', fontSize: 12, lineHeight: 17, marginVertical: 3 },
  value: { color: '#16324F', fontSize: 22, fontWeight: '800' },
  heading: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  balance: { alignItems: 'flex-end', flexShrink: 1 },
  segmented: { flexDirection: 'row', borderWidth: 1, borderColor: '#BBD0EB', borderRadius: 10, overflow: 'hidden', backgroundColor: '#FFFFFF' },
  chip: { paddingHorizontal: 14, paddingVertical: 12, minHeight: 44, justifyContent: 'center' },
  selected: { backgroundColor: palette.primary },
  chipText: { color: '#16324F', fontSize: 13, fontWeight: '700' },
  chart: { marginTop: 14, marginBottom: 4 },
  plotRow: { flexDirection: 'row' },
  scale: { width: AXIS },
  tick: { position: 'absolute', right: 6, color: '#476582', fontSize: 10, lineHeight: 14 },
  plot: { flex: 1, height: HEIGHT },
  grid: { position: 'absolute', left: 0, right: 0, height: 1, backgroundColor: '#8E9CB5', opacity: .17 },
  verticalGrid: { position: 'absolute', top: 0, bottom: 0, width: 1, backgroundColor: '#8E9CB5', opacity: .12 },
  segment: { position: 'absolute', height: 2.5, borderRadius: 2 },
  fill: { position: 'absolute', opacity: .10 },
  dot: { position: 'absolute', width: 5, height: 5, borderRadius: 3 },
  dates: { marginLeft: AXIS, flexDirection: 'row', justifyContent: 'space-between', marginTop: 7 },
  date: { fontSize: 10, color: '#476582' },
  subheading: { fontSize: 14, color: '#16324F', fontWeight: '700', marginTop: 14 },
  barPlot: { flex: 1, height: BAR_HEIGHT, flexDirection: 'row' },
  bin: { flex: 1, height: BAR_HEIGHT, alignItems: 'center' },
  bar: { position: 'absolute', width: '65%', maxWidth: 11, borderRadius: 1 },
  detailsLink: { paddingVertical: 10, minHeight: 44, justifyContent: 'center' },
  detailsText: { color: '#476582', fontSize: 12, fontWeight: '600' },
});
function Choice({ value, selected, onPress }) {
  return <TouchableOpacity accessibilityRole="button" accessibilityState={{ selected }} onPress={onPress} style={[s.chip, selected && s.selected]}><Text style={[s.chipText, selected && { color: '#FFFFFF' }]}>{value}</Text></TouchableOpacity>;
}
function Dates({ rows }) {
  return <View style={s.dates}>{dateTicks(rows).map(date => <Text key={date} style={s.date}>{dateLabel(date)}</Text>)}</View>;
}
function ValueChart({ rows, currency, colour }) {
  const [width, setWidth] = useState(230), [chosen, setChosen] = useState(null);
  const graph = accountChart(rows, width, HEIGHT);
  if (!graph.points.length) return <Text style={s.label}>No reliable value history yet. Missing values are not zero.</Text>;
  const detail = graph.points.find(p => p.date === chosen);
  return <View style={s.chart}>
    <View style={s.plotRow}>
      <View style={[s.scale, { height: HEIGHT }]}>{graph.ticks.map((tick, i) => <Text key={i} numberOfLines={1} adjustsFontSizeToFit style={[s.tick, { top: tick.y - 7, left: 0, textAlign: 'right' }]}>{compactMoney(tick.value, currency, graph.ticks[1].value - graph.ticks[0].value)}</Text>)}</View>
      <View style={s.plot} onLayout={event => setWidth(Math.max(20, event.nativeEvent.layout.width))}>
        {graph.ticks.map((tick, i) => <View key={'grid-' + i} style={[s.grid, { top: tick.y }]} />)}
        {[0, .5, 1].map(fraction => <View key={fraction} style={[s.verticalGrid, { left: fraction * 100 + '%' }]} />)}
        <View pointerEvents="none" style={{ position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, overflow: 'hidden' }}>
          {graph.fills.map((fill, i) => <View key={'fill-' + i} style={[s.fill, { backgroundColor: colour, left: fill.x, top: fill.y, width: fill.width, height: fill.height }]} />)}
          {graph.strokes.map((seg, i) => <View key={'line-' + i} style={[s.segment, { backgroundColor: colour, left: seg.x - seg.length / 2, top: seg.y - 1.25, width: seg.length, transform: [{ rotate: seg.angle + 'rad' }] }]} />)}
        </View>
        {graph.points.filter(p => p.y !== null).map(p => <TouchableOpacity key={p.date} onPress={() => setChosen(p.date)} hitSlop={8} accessibilityRole="button" accessibilityLabel={p.date + ': ' + money(p.value, currency) + (p.flow ? ', allocation changed' : '')} style={[s.dot, { left: p.x - 2.5, top: p.y - 2.5, backgroundColor: p.flow ? '#A16207' : colour, opacity: p.flow || chosen === p.date || graph.points.length === 1 ? 1 : .35 }]} />)}
      </View>
    </View>
    <Dates rows={rows} />
    {detail && <Text style={s.label}>{dateLabel(detail.date)}: {money(detail.value, currency)}{detail.flow ? ' · allocation change ' + money(detail.flow, currency) : ''}</Text>}
    {graph.points.filter(p => p.y !== null).length === 1 && <Text style={s.label}>One observation so far; more history is needed for a trend.</Text>}
  </View>;
}
function OutcomeChart({ bins, currency, netKnown }) {
  const [selected, setSelected] = useState(null);
  const peak = Math.max(1, ...bins.flatMap(b => [b.wins, b.losses]));
  const detail = bins.find(b => b.date === selected);
  return <View style={s.chart}>
    <View style={s.plotRow}>
      <View style={[s.scale, { height: BAR_HEIGHT }]}>{[{ y: 0, text: peak }, { y: BAR_HEIGHT / 2, text: 0 }, { y: BAR_HEIGHT, text: '−' + peak }].map(tick => <Text key={tick.y} style={[s.tick, { top: tick.y - 7 }]}>{tick.text}</Text>)}</View>
      <View style={s.barPlot}>
        {[0, BAR_HEIGHT / 2, BAR_HEIGHT].map(y => <View key={y} style={[s.grid, { top: y, opacity: y === BAR_HEIGHT / 2 ? .4 : .17 }]} />)}
        {bins.map(bin => <TouchableOpacity key={bin.date} style={s.bin} accessibilityRole="button" onPress={() => setSelected(bin.date)} accessibilityLabel={bin.date + ': ' + bin.wins + ' won, ' + bin.losses + ' lost, ' + bin.breakeven + ' break-even, ' + bin.unknown + ' unknown'}>
          <View style={[s.bar, { bottom: BAR_HEIGHT / 2, height: bin.wins / peak * (BAR_HEIGHT / 2 - 2), backgroundColor: '#319C6B' }]} />
          <View style={[s.bar, { top: BAR_HEIGHT / 2, height: bin.losses / peak * (BAR_HEIGHT / 2 - 2), backgroundColor: '#E45E68' }]} />
        </TouchableOpacity>)}
      </View>
    </View>
    <Dates rows={bins} />
    {detail && <Text style={s.label}>{detail.date}: {detail.wins} won / {detail.losses} lost · {money(detail.net_pnl, currency)} {netKnown ? 'net' : 'before unreconciled fees'}</Text>}
  </View>;
}
function BrokerTrends({ broker, days, weekly, asOf }) {
  const [details, setDetails] = useState(false);
  const netKnown = broker.pnl_basis === 'net_after_fees';
  const series = seriesFor(broker, days, asOf), bins = outcomeBuckets(series.outcomes, days, asOf, weekly);
  const latest = series.values.filter(row => typeof row.value === 'number' && Number.isFinite(row.value)).at(-1);
  const totals = bins.reduce((acc, b) => { for (const key of Object.keys(acc)) acc[key] += b[key]; return acc; }, { wins: 0, losses: 0, breakeven: 0, unknown: 0, net_pnl: 0 });
  const name = broker.broker === 'kraken' ? 'Kraken' : broker.broker === 'alpaca' ? 'Alpaca' : broker.broker;
  return <View style={[s.card, exchangePalette(broker.broker)]}>
    <View style={s.heading}>
      <Text style={s.title}>{name} · {broker.currency}</Text>
      <View style={s.balance}><Text style={s.label}>Account value ({days}d)</Text><Text style={s.value}>{broker.value_status === 'ok' && latest ? money(latest.value, broker.currency) : 'Unavailable'}</Text></View>
    </View>
    <Text style={s.label}>{broker.broker === 'kraken' ? 'AI capital only · personal holdings excluded' : 'Whole account · cash plus investments'}{broker.account_mode ? ' · ' + broker.account_mode : ''}</Text>
    {broker.value_status === 'ok' ? <ValueChart rows={series.values} currency={broker.currency} colour={broker.broker === 'kraken' ? '#8064DC' : broker.broker === 'alpaca' ? '#BC8800' : '#476582'} /> : <Text style={s.label}>Value history is temporarily unavailable.</Text>}
    <Text style={s.subheading}>{broker.broker === 'kraken' ? 'Completed AI trades' : 'Completed recorded trades'} ({days}d)</Text>
    {broker.outcome_status !== 'ok' ? <Text style={s.label}>Trade outcomes are temporarily unavailable.</Text> : <>
      <Text style={s.label}>{netKnown ? 'After recorded fees' : 'Provisional · fees not fully reconciled'} · {weekly ? 'weekly' : 'daily'} UTC</Text>
      <Text style={s.label}>Wins above · losses below · counts, not money</Text>
      <OutcomeChart bins={bins} currency={broker.currency} netKnown={netKnown} />
      <Text style={s.label}>Won {totals.wins} · Lost {totals.losses} · {money(totals.net_pnl, broker.currency)} {netKnown ? 'net' : 'before unreconciled fees'}</Text>
      {!!totals.unknown && <Text style={s.label}>{totals.unknown} outcomes have unknown profit and are excluded from the total.</Text>}
      {!totals.wins && !totals.losses && !totals.breakeven && !totals.unknown && <Text style={s.label}>No completed trades recorded in this period.</Text>}
    </>}
    <TouchableOpacity accessibilityRole="button" accessibilityState={{ expanded: details }} onPress={() => setDetails(value => !value)} style={s.detailsLink}><Text style={s.detailsText}>{details ? 'Hide chart details −' : 'Chart details +'}</Text></TouchableOpacity>
    {details && <View>
      <Text style={s.label}>Green bars above zero count wins; red bars below zero count losses, not negative trade counts or money. Break-even {totals.breakeven} · Unknown {totals.unknown}. Tap chart points or bars for details.</Text>
      <Text style={s.label}>Last observation each UTC day; today is partial. Missing days remain gaps, not zero. {latest ? 'Latest value: ' + latest.date : ''}</Text>
      <Text style={s.label}>{broker.broker === 'kraken' ? 'Amber markers show recorded allocation changes, not trading profit. Earlier unrecorded funding is not inferred.' : 'Deposit and withdrawal history is unavailable. Balance changes are not necessarily trading profit.'}</Text>
      {!netKnown && <Text style={s.label}>Small recorded wins may become losses after fees; these are not verified net wins.</Text>}
      <Text style={s.label}>Open positions are excluded. First and current weeks may be partial. Historical results may include earlier account modes.</Text>
    </View>}
  </View>;
}
function PortfolioTrends({ request = apiRequest }) {
  const [data, setData] = useState(null), [error, setError] = useState(null);
  const [days, setDays] = useState(30), [weekly, setWeekly] = useState(false), [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    loadTrends(request).then(value => { if (active) { setData(value); setError(null); } }).catch(() => { if (active) setError('History could not be loaded. Your trading is unaffected.'); });
    return () => { active = false; };
  }, [request, retry]);
  return <View style={styles.bareSection}>
    <View style={s.heading}><Text style={styles.sectionTitle}>Your progress</Text><View style={s.segmented}>{[7, 30, 90].map(n => <Choice key={n} value={n + 'd'} selected={days === n} onPress={() => setDays(n)} />)}</View></View>
    <Text style={s.label}>Account value and completed trades</Text>
    <View style={s.heading}><View style={s.segmented}><Choice value="Daily" selected={!weekly} onPress={() => setWeekly(false)} /><Choice value="Weekly" selected={weekly} onPress={() => setWeekly(true)} /></View></View>
    {error ? <View><Text style={styles.bodyText}>{error}</Text><Button label="Retry history" onPress={() => setRetry(retry + 1)} /></View> : !data ? <Text style={styles.bodyText}>Loading compact history…</Text> : <View>
      {data.brokers.map(broker => <BrokerTrends key={broker.broker} broker={broker} days={days} weekly={weekly} asOf={data.as_of} />)}
      <Text style={s.label}>Updated {data.as_of.replace('T', ' ').slice(0, 16)} UTC · cached up to 10 minutes</Text>
    </View>}
  </View>;
}
module.exports = { PortfolioTrends, BrokerTrends, ValueChart, OutcomeChart };
