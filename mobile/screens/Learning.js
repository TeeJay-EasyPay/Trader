'use strict';
const React = require('react');
const { useEffect, useState } = React;
const { View, Text, TouchableOpacity, ActivityIndicator, StyleSheet, Platform, BackHandler } = require('react-native');
const { LearningCloud } = require('../components/LearningCloud');
const { exchangePalette, palette } = require('../lib/palette');
const { learningRequest, shiftedDate, resultText, humanStatus } = require('../lib/learningScreen');
const HEADINGS = { rejected: 'Tracked opportunities', decisions: 'Rejected decisions', trades: 'Completed trades',
  strategies: 'Strategy ideas', tests: 'Test results', reviews: 'Trade reviews', proposals: 'Proposed lessons' };
const s = StyleSheet.create({
  page: { gap: 16, paddingBottom: 24 },
  title: { fontFamily: Platform?.OS === 'ios' ? 'Georgia' : 'serif', fontSize: 27, fontWeight: '700', color: '#081D45' },
  heading: { fontFamily: Platform?.OS === 'ios' ? 'Georgia' : 'serif', fontSize: 22, fontWeight: '700', color: '#081D45' },
  body: { color: '#243C60', fontSize: 15, lineHeight: 23 }, small: { color: '#52637D', fontSize: 12, lineHeight: 18 },
  card: { backgroundColor: '#FFFFFF', borderRadius: 18, borderWidth: 1, borderColor: '#DAE3EB', padding: 17, gap: 12,
    shadowColor: '#16324F', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.06, shadowRadius: 6, elevation: 1 },
  summary: { backgroundColor: '#FFF6E7', borderColor: '#F2D9AE', padding: 0, overflow: 'hidden' },
  summaryArt: { position: 'absolute', top: 0, right: 0, left: 0, height: 160, opacity: 0.55 },
  summaryContent: { padding: 18, gap: 14 }, row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' },
  button: { minHeight: 44, borderRadius: 9, borderWidth: 1, borderColor: '#C8D7DF', paddingHorizontal: 13,
    paddingVertical: 11, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  active: { backgroundColor: palette.primary, borderColor: palette.primary },
  buttonText: { color: palette.ink, fontWeight: '700', fontSize: 13 }, selectedText: { color: '#FFFFFF' },
  grow: { flexGrow: 1 }, muted: { opacity: 0.45 },
  badge: { color: '#835500', backgroundColor: '#FFF0C5', borderRadius: 12, paddingVertical: 6, paddingHorizontal: 10, alignSelf: 'flex-start', fontSize: 13 },
  broker: { borderRadius: 14, borderWidth: 1, padding: 14, gap: 8, overflow: 'hidden' },
  waveA: { position: 'absolute', width: 320, height: 140, borderRadius: 120, right: -90, top: -50,
    backgroundColor: 'rgba(255,255,255,0.5)', transform: [{ rotate: '-16deg' }] },
  waveB: { position: 'absolute', width: 310, height: 150, borderRadius: 130, right: -140, bottom: -100,
    backgroundColor: 'rgba(255,255,255,0.5)', transform: [{ rotate: '-12deg' }] },
  value: { fontSize: 21, fontWeight: '700', color: '#182D50' },
  metric: { flex: 1, minWidth: 75, alignItems: 'center', paddingVertical: 9 },
  divider: { borderTopWidth: 1, borderColor: '#E2E7EA', paddingTop: 10, gap: 5 },
  chart: { borderWidth: 1, borderColor: '#D8CBFF', backgroundColor: '#F5F1FF', borderRadius: 12, padding: 12, gap: 10 },
  plot: { height: 150, borderLeftWidth: 1, borderBottomWidth: 1, borderColor: '#BCC3D6', justifyContent: 'center', alignItems: 'center' },
  gridHorizontal: { position: 'absolute', left: 0, right: 0, height: 1, backgroundColor: '#DEDDEF' },
  gridVertical: { position: 'absolute', top: 0, bottom: 0, width: 1, backgroundColor: '#E7E4F3' },
  chartMessage: { backgroundColor: '#F5F1FF', padding: 10, margin: 12, textAlign: 'center', color: '#52637D', fontSize: 14 },
  legendDot: { width: 9, height: 9, borderRadius: 5 },
  segmented: { flexDirection: 'row', borderWidth: 1, borderColor: '#CBD3DF', borderRadius: 9, overflow: 'hidden' },
  segment: { flex: 1, minHeight: 44, paddingVertical: 11, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  fact: { flexDirection: 'row', flexWrap: 'wrap', borderTopWidth: 1, borderColor: '#E8DFCC', paddingVertical: 8, gap: 8 },
  factLabel: { color: '#182D50', fontWeight: '700', width: 80, fontSize: 14 },
  factValue: { color: '#33486B', flex: 1, minWidth: 160, fontSize: 14, lineHeight: 21 },
  brokerBadge: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  stageLine: { position: 'absolute', left: '12%', right: '12%', top: 9, height: 1, backgroundColor: '#ADB9D5' },
});
function SectionHeading({ icon, title }) {
  return <View style={s.row}><Text accessible={false} style={{ color: '#006346', fontSize: 22 }}>{icon}</Text><Text style={[s.heading, { flexShrink: 1 }]}>{title}</Text></View>;
}
function BrokerBadge({ broker }) {
  return <View accessible={false} style={[s.brokerBadge, { backgroundColor: broker === 'kraken' ? '#7955DA' : '#F3CE59' }]}>
    <Text style={{ color: broker === 'kraken' ? '#FFFFFF' : '#4C3B00', fontWeight: '800', fontSize: 19 }}>{broker === 'kraken' ? 'K' : 'A'}</Text></View>;
}
function LearningComparisonChart({ period }) {
  return <View style={s.chart} accessibilityLabel="Kraken simulated comparison chart. Awaiting comparison results. No results plotted.">
    <Text style={[s.body, { color: '#633BC1', fontWeight: '700' }]}>Kraken · simulated comparison</Text>
    <View style={s.row}>
      <View style={[s.legendDot, { backgroundColor: '#00884A' }]} /><Text style={s.small}>Proposed rule</Text>
      <View style={[s.legendDot, { backgroundColor: '#8B93AC' }]} /><Text style={s.small}>Unchanged rule</Text>
    </View>
    <Text style={s.small}>Indexed value · scale pending</Text>
    <View style={s.plot}>
      {[0, 25, 50, 75].map(p => <View key={'h' + p} style={[s.gridHorizontal, { top: p + '%' }]} />)}
      {[25, 50, 75, 100].map(p => <View key={'v' + p} style={[s.gridVertical, { left: p + '%' }]} />)}
      <Text style={s.chartMessage}>Awaiting comparison results</Text>
    </View>
    <Text style={[s.small, { textAlign: 'center' }]}>{periodLabel(period)} · UTC</Text>
    <Text style={s.small}>No paired rule experiment recorded. Test-result integration is still needed to plot a named rule against an unchanged baseline after estimated costs.</Text>
  </View>;
}
function Action({ label, onPress, selected, disabled, grow }) {
  return <TouchableOpacity accessibilityRole="button" accessibilityState={{ selected: !!selected, disabled: !!disabled }}
    disabled={disabled} onPress={onPress} style={[s.button, grow && s.grow, selected && s.active, disabled && s.muted]}>
    <Text style={[s.buttonText, selected && s.selectedText]}>{label}</Text>
  </TouchableOpacity>;
}
function BrokerCard({ broker, children }) {
  return <View style={[s.broker, exchangePalette(broker)]}>
    <View pointerEvents="none" accessible={false} style={StyleSheet.absoluteFillObject}>
      <View style={s.waveA} /><View style={s.waveB} />
    </View>{children}
  </View>;
}
function periodLabel(bounds) {
  const end = new Date(bounds.end + 'T12:00:00Z'); end.setUTCDate(end.getUTCDate() - 1);
  return bounds.kind === 'daily' ? bounds.start : bounds.start + ' – ' + end.toISOString().slice(0, 10);
}
function LearningOverview({ data, period, anchor, onPeriod, onMove, onOpen, today }) {
  const [opportunityBroker, setOpportunityBroker] = useState('all');
  const preview = (data.opportunity_previews || []).find(p => opportunityBroker === 'all' || p.broker === opportunityBroker);
  const latest = data.reviews[0];
  const lesson = latest?.lessons?.[0] || latest?.what_happened || 'No lesson is recorded for this period yet. Evidence is still being gathered.';
  const count = data.unavailable.includes('lesson proposals') ? '—' : data.proposals.reduce((n, x) => n + Number(x.total || 0), 0);
  return <View style={s.page}>
    <View><Text style={s.title}>What are we learning?</Text><Text style={s.body}>From decisions to evidence.</Text></View>
    <View style={[s.card, s.summary]}>
      <LearningCloud />
      <View style={s.summaryContent}>
        <View style={{ paddingRight: 112, minHeight: 56 }}><SectionHeading icon="▤" title="Learning summary" /></View>
        <View style={s.segmented}>{['daily', 'weekly', 'monthly'].map(p => <TouchableOpacity key={p} accessibilityRole="tab"
          accessibilityState={{ selected: p === period }} style={[s.segment, p === period && s.active]} onPress={() => onPeriod(p)}>
          <Text style={[s.buttonText, p === period && s.selectedText]}>{p[0].toUpperCase() + p.slice(1)}</Text></TouchableOpacity>)}</View>
        <View style={[s.row, { justifyContent: 'center' }]}><Action label="‹" onPress={() => onMove(-1)} disabled={anchor <= '2020-01-01'} />
          <Text style={[s.small, { textAlign: 'center', flexShrink: 1 }]}>{periodLabel(data.period)} · UTC</Text>
          <Action label="›" onPress={() => onMove(1)} disabled={shiftedDate(data.period.start, period, 1) > today} /></View>
        <Text style={[s.badge, { alignSelf: 'center' }]}>{data.period.in_progress ? '◷ In progress' : 'Period complete · evidence may update'}</Text>
        <Text style={s.heading}>{period === 'daily' ? "The day's learning" : period === 'weekly' ? "The week's learning" : "The month's learning"}</Text>
        <Text style={s.body}>{lesson}</Text>
        <Text style={s.small}>Recorded hypothesis—not proven improvement.</Text>
        {data.unavailable.length > 0 && <Text style={s.badge}>Unavailable: {data.unavailable.join(', ')}</Text>}
        {[['Evidence', data.unavailable.length ? 'Some evidence is unavailable; see details below.' : `${data.outcomes.reduce((n, o) => n + o.total, 0)} completed outcomes · ${data.review_count ?? 'Unknown'} reviews · ${data.shadows.reduce((n, o) => n + o.total, 0)} shadow candidates`],
          ['Next test', 'Compare a named lesson against unchanged rules.'], ['Decision', 'No rule change is made by this report.']].map(([label, value]) => <View key={label} style={s.fact}><Text style={s.factLabel}>{label}</Text><Text style={s.factValue}>{value}</Text></View>)}
        <Action label="Read trade reviews →" onPress={() => onOpen('reviews')} />
        <Text style={s.small}>Daily, weekly and monthly evidence · earlier reports may update.</Text>
      </View>
    </View>
    <View style={s.card}>
      <SectionHeading icon="▥" title="Is learning helping?" /><Text style={s.badge}>Not enough evidence yet</Text>
      <View style={s.row}><View style={s.metric}><Text style={s.value}>{count}</Text><Text style={s.small}>proposals recorded</Text></View>
        <View style={s.metric}><Text style={s.value}>{data.review_count ?? '—'}</Text><Text style={s.small}>reviews written</Text></View>
        <View style={s.metric}><Text style={s.value}>—</Text><Text style={s.small}>validated change</Text></View></View>
      <LearningComparisonChart period={data.period} />
      <Text style={s.small}>{data.assessment.explanation}</Text>
      <Action label="View proposed lessons →" onPress={() => onOpen('proposals')} />
    </View>
    <View style={s.card}><SectionHeading icon="⊘" title="Rejected opportunities" />
      <View style={s.row}>{['all', 'kraken', 'alpaca'].map(b => <Action key={b} grow label={b[0].toUpperCase() + b.slice(1)} selected={b === opportunityBroker} onPress={() => setOpportunityBroker(b)} />)}</View>
      <Text style={s.body}>{data.unavailable.includes('rejection events') ? 'Rejection counts unavailable' : data.rejections.reduce((n, x) => n + Number(x.events), 0) + ' recorded rejection events'} · may include repeated checks.</Text>
      <BrokerCard broker={preview?.broker || (opportunityBroker === 'all' ? 'kraken' : opportunityBroker)}>
        {preview ? <><View style={s.row}><BrokerBadge broker={preview.broker} /><Text style={[s.body, { fontWeight: '700', flexShrink: 1 }]}>{preview.symbol} · {preview.broker}</Text><Text style={s.badge}>SIMULATED</Text></View>
          <Text style={s.body}>{preview.reason || 'Rejection reason not recorded'}</Text>
          <View style={[s.row, { backgroundColor: 'rgba(255,255,255,0.55)', borderRadius: 10 }]}>{[['Entry', preview.intended_entry], ['Target', preview.take_profit], ['Stop', preview.stop_loss]].map(([label, value]) => <View key={label} style={s.metric}><Text style={s.small}>{label}</Text><Text style={[s.body, { fontWeight: '700' }]}>{value ?? 'Unknown'}</Text></View>)}</View>
          <Text style={s.badge}>{humanStatus(preview.outcome_status)}</Text>
          <Text style={s.small}>{typeof preview.estimated_net_r === 'number' ? `Estimated net outcome: ${preview.estimated_net_r.toFixed(2)}R (planned risk, not currency).` : 'Estimated outcome pending / unknown.'}</Text>
        </> : <Text style={s.body}>No linked rejected-opportunity preview is available for this selection.</Text>}
      </BrokerCard>
      <Text style={s.small}>Entry prices are as recorded. Simulations assume entry, use daily candles and estimated costs—not verified fills.</Text>
      <Action label="View tracked opportunities →" onPress={() => onOpen('rejected')} />
      <Action label="View rejected decisions →" onPress={() => onOpen('decisions')} />
    </View>
    <View style={s.card}><SectionHeading icon="✓" title="Completed trades" />
      {['kraken', 'alpaca'].map(b => { const row = data.outcomes.find(o => o.broker === b); return <BrokerCard key={b} broker={b}>
        <View style={s.row}><BrokerBadge broker={b} /><View style={{ flexGrow: 1 }}><Text style={[s.body, { fontWeight: '700' }]}>{b === 'kraken' ? 'Kraken' : 'Alpaca'}</Text><Text style={s.small}>{row ? `${row.total} closed · ${row.unknown} unknown` : 'No recorded outcomes'}</Text></View>
          <Text style={[s.value, { fontSize: 18, textAlign: 'right', color: row?.pnl < 0 ? '#B42318' : row?.pnl > 0 ? '#006A3B' : '#182D50' }]}>{row ? resultText(row.pnl, b) : data.unavailable.includes('completed trades') ? 'Unavailable' : '—'}</Text></View>
        <Text style={s.small}>{data.unavailable.includes('completed trades') ? 'Completed-trade evidence could not be loaded.' : b === 'kraken' ? 'Recorded net P&L · AI-managed trades only' : 'Before unreconciled fees · not verified net profit'}</Text>
      </BrokerCard>; })}
      <Action label="Review completed trades →" onPress={() => onOpen('trades')} />
    </View>
    <View style={s.card}><SectionHeading icon="⚗" title="Strategy research & testing" />
      <View style={{ flexDirection: 'row', marginVertical: 4 }}><View style={s.stageLine} />{['Research', 'Backtest', 'Shadow', 'Review'].map(stage => <View key={stage} style={{ flex: 1, alignItems: 'center', gap: 8 }}><View style={{ width: 19, height: 19, borderRadius: 10, borderWidth: 2, borderColor: '#ADB9D5', backgroundColor: '#FFFFFF' }} /><Text style={s.small}>{stage}</Text></View>)}</View>
      <BrokerCard><Text style={[s.body, { fontWeight: '700' }]}>{data.strategy_preview?.name || 'Awaiting a strategy record'}</Text>
        <Text style={s.small}>{data.strategy_preview?.purpose || 'Recorded strategy ideas will appear here.'}</Text>
        <Text style={s.badge}>{data.strategy_preview ? 'Catalogue record · ' + humanStatus(data.strategy_preview.production_status) : 'No candidate selected'}</Text>
      </BrokerCard>
      <Text style={s.small}>Stages show the testing process, not verified progress. {data.backtest_count ?? 'Unknown'} backtest records in this period. External discovery and paired experiments are not connected yet.</Text>
      <View style={s.row}><Action grow label="Strategy ideas" onPress={() => onOpen('strategies')} /><Action grow label="Test results" onPress={() => onOpen('tests')} /></View>
    </View>
    <Text style={s.small}>Evidence updated {data.generated_at}. Cached for up to 10 minutes.</Text>
    {data.caveats.map(note => <Text key={note} style={s.small}>• {note}</Text>)}
  </View>;
}
function EvidenceRow({ row, kind }) {
  const [expanded, setExpanded] = useState(false);
  return <BrokerCard broker={row.broker}>
    <Text style={[s.body, { fontWeight: '700' }]}>{row.symbol || row.name || row.proposal_type || row.strategy_id || 'Recorded evidence'}{row.broker ? ' · ' + row.broker : ''}</Text>
    <Text style={s.small}>{row.created_at}</Text>
    {kind === 'rejected' && <><Text style={s.badge}>SIMULATED · {humanStatus(row.outcome_status)}</Text>
      <Text style={s.body}>{row.reason || 'Reason not recorded'}</Text><Text style={s.small}>{row.provenance}</Text>
      <View style={s.row}>{[['Entry', row.intended_entry], ['Target', row.take_profit], ['Stop', row.stop_loss]].map(([label, v]) => <View key={label} style={s.metric}><Text style={s.small}>{label}</Text><Text style={[s.body, { fontWeight: '700' }]}>{v ?? 'Unknown'}</Text></View>)}</View>
      <Text style={s.body}>Estimated net result: {typeof row.estimated_net_r === 'number' ? row.estimated_net_r.toFixed(2) + 'R' : 'Pending / unknown'}</Text>
      <Text style={s.small}>R means planned risk, not money. Entry unverified; stop-first daily-candle model.</Text></>}
    {kind === 'decisions' && <><Text style={s.body}>{row.reason || 'Reason not recorded'}</Text><Text style={s.small}>{row.provenance} · repeated checks may appear separately.</Text></>}
    {kind === 'trades' && <><Text style={s.value}>{resultText(row.pnl, row.broker)}</Text><Text style={s.small}>{row.broker === 'alpaca' ? 'Before unreconciled fees' : 'Recorded net P&L'}</Text></>}
    {kind === 'strategies' && <><Text style={s.badge}>{humanStatus(row.production_status)}</Text><Text style={s.body}>{row.purpose}</Text><Text style={s.small}>Registry status is not proof of a validated edge.</Text></>}
    {kind === 'tests' && <><Text style={s.badge}>HISTORICAL BACKTEST</Text><Text style={s.body}>{row.trades} trades · expectancy {row.expectancy_r ?? 'unknown'}R</Text><Text style={s.small}>Not a paired-rule experiment or verified live return.</Text></>}
    {kind === 'reviews' && <><Text style={s.badge}>{humanStatus(row.outcome_classification)}</Text><Text style={s.body}>{row.what_happened}</Text></>}
    {kind === 'proposals' && <><Text style={s.badge}>{humanStatus(row.approval_status)}</Text><Text style={s.body}>{row.current_value} → {row.proposed_value}</Text><Text style={s.small}>{row.sample_size} samples · approval is not proof of improvement</Text></>}
    {['strategies', 'tests', 'reviews', 'proposals'].includes(kind) && <><Action label={expanded ? 'Hide evidence' : 'Read recorded evidence'} onPress={() => setExpanded(v => !v)} />
      {expanded && <Text selectable style={s.body}>{row.evidence_note || row.result_summary || row.lessons_json || row.expected_impact || 'No further evidence recorded.'}</Text>}</>}
  </BrokerCard>;
}
function LearningScreen({ request, onNavigate }) {
  const today = new Date().toISOString().slice(0, 10);
  const [period, setPeriod] = useState('daily'), [anchor, setAnchor] = useState(today);
  const [detail, setDetail] = useState(null), [broker, setBroker] = useState('all'), [page, setPage] = useState(0);
  const [data, setData] = useState(null), [busy, setBusy] = useState(true), [error, setError] = useState(null), [retry, setRetry] = useState(0);
  const path = detail ? '/learning-details?kind=' + detail + '&period=' + period + '&date=' + anchor + '&broker=' + broker + '&page=' + page
    : '/learning-summary?period=' + period + '&date=' + anchor;
  useEffect(() => { let active = true; setBusy(true); setData(null); setError(null);
    learningRequest(request, path).then(v => { if (active) setData(v); }).catch(e => { if (active) setError(e.message || 'Unable to load learning evidence'); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [request, path, retry]);
  useEffect(() => { if (!detail || !BackHandler) return undefined; const listener = BackHandler.addEventListener('hardwareBackPress', () => { setDetail(null); return true; }); return () => listener.remove(); }, [detail]);
  useEffect(() => { if (data && onNavigate) onNavigate(Boolean(detail)); }, [data, detail, onNavigate]);
  const open = kind => { if (onNavigate) onNavigate(true); setPage(0); setBroker('all'); setDetail(kind); };
  if (busy || error || !data) return <View style={s.card}>{detail && <Action label="‹ Back to Learning" onPress={() => setDetail(null)} />}
    <Text style={s.heading}>Learning</Text>{busy ? <ActivityIndicator /> : <Action label="Retry" onPress={() => setRetry(n => n + 1)} />}<Text style={s.body}>{error || 'Loading compact evidence…'}</Text></View>;
  if (!detail) return <LearningOverview data={data} period={period} anchor={anchor} today={today} onPeriod={setPeriod}
    onMove={n => setAnchor(shiftedDate(data.period.start, period, n))} onOpen={open} />;
  return <View style={s.page}><Action label="‹ Back to Learning" onPress={() => setDetail(null)} />
    <Text style={s.title}>{HEADINGS[detail]}</Text><Text style={s.small}>{periodLabel(data.period)} · UTC. {data.note}</Text>
    {['rejected', 'decisions', 'trades', 'reviews'].includes(detail) && <View style={s.row}>{['all', 'kraken', 'alpaca'].map(b => <Action key={b} grow label={b[0].toUpperCase() + b.slice(1)} selected={broker === b} onPress={() => { setPage(0); setBroker(b); }} />)}</View>}
    {!data.rows.length && <View style={s.card}><Text style={s.body}>No recorded evidence for this selection.</Text></View>}
    {data.rows.map((row, i) => <EvidenceRow key={(row.id || row.symbol) + '-' + i} row={row} kind={detail} />)}
    <View style={s.row}><Action grow label="‹ Previous" disabled={page === 0} onPress={() => setPage(n => n - 1)} /><Text style={s.small}>Page {page + 1}</Text><Action grow label="Next ›" disabled={!data.has_more} onPress={() => setPage(n => n + 1)} /></View>
  </View>;
}
module.exports = { LearningScreen, LearningOverview, EvidenceRow, BrokerCard, LearningComparisonChart };
