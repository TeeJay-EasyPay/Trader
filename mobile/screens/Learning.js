'use strict';
const React = require('react');
const { useEffect, useState } = React;
const { View, Text, TouchableOpacity, ActivityIndicator, StyleSheet, Platform, BackHandler, useWindowDimensions } = require('react-native');
const { LearningCloud } = require('../components/LearningCloud');
const { exchangePalette, palette } = require('../lib/palette');
const { learningRequest, shiftedDate, resultText, humanStatus, priceText, matchesLearningView } = require('../lib/learningScreen');
const HEADINGS = { rejected: 'Tracked opportunities', decisions: 'Rejected decisions', trades: 'Completed trades',
  strategies: 'Strategy ideas', tests: 'Test results', reviews: 'Trade reviews', proposals: 'Proposed lessons' };
const s = StyleSheet.create({
  page: { gap: 12, paddingBottom: 20 },
  title: { fontFamily: Platform?.OS === 'ios' ? 'Georgia' : 'serif', fontSize: 27, fontWeight: '700', color: '#081D45' },
  heading: { fontFamily: Platform?.OS === 'ios' ? 'Georgia' : 'serif', fontSize: 20, fontWeight: '700', color: '#081D45' },
  body: { color: '#243C60', fontSize: 14, lineHeight: 20 }, small: { color: '#52637D', fontSize: 11, lineHeight: 16 },
  card: { backgroundColor: '#FFFFFF', borderRadius: 10, borderWidth: 1, borderColor: '#E0E8EF', padding: 12, gap: 8,
    shadowColor: '#16324F', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.06, shadowRadius: 6, elevation: 1 },
  summary: { backgroundColor: '#FFF6E7', borderColor: '#F2D9AE', padding: 0, overflow: 'hidden' },
  summaryArt: { position: 'absolute', top: 0, right: 0, left: 0, height: 160, opacity: 0.55 },
  summaryContent: { padding: 14, gap: 8 }, row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' },
  footer: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  footerNote: { flex: 1, minWidth: 120 },
  compactButton: { minHeight: 36, paddingVertical: 6, paddingHorizontal: 12, borderRadius: 6, alignSelf: 'flex-end' },
  link: { borderWidth: 0, backgroundColor: 'transparent', paddingHorizontal: 0, alignSelf: 'flex-start' },
  button: { minHeight: 44, borderRadius: 9, borderWidth: 1, borderColor: '#C8D7DF', paddingHorizontal: 13,
    paddingVertical: 11, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  active: { backgroundColor: palette.primary, borderColor: palette.primary },
  buttonText: { color: palette.ink, fontWeight: '700', fontSize: 13 }, selectedText: { color: '#FFFFFF' },
  grow: { flexGrow: 1 }, muted: { opacity: 0.45 },
  badge: { color: '#835500', backgroundColor: '#FFF0C5', borderRadius: 12, paddingVertical: 3, paddingHorizontal: 8, alignSelf: 'flex-start', fontSize: 11 },
  broker: { borderRadius: 9, borderWidth: 1, padding: 10, gap: 6, overflow: 'hidden' },
  waveA: { position: 'absolute', width: 320, height: 140, borderRadius: 120, right: -90, top: -50,
    backgroundColor: 'rgba(255,255,255,0.5)', transform: [{ rotate: '-16deg' }] },
  waveB: { position: 'absolute', width: 310, height: 150, borderRadius: 130, right: -140, bottom: -100,
    backgroundColor: 'rgba(255,255,255,0.5)', transform: [{ rotate: '-12deg' }] },
  value: { fontSize: 21, fontWeight: '700', color: '#182D50' },
  metric: { flex: 1, minWidth: 55, alignItems: 'center', paddingVertical: 5 },
  divider: { borderTopWidth: 1, borderColor: '#E2E7EA', paddingTop: 10, gap: 5 },
  chart: { borderWidth: 1, borderColor: '#E2DAFF', backgroundColor: '#F7F5FF', borderRadius: 8, padding: 10, gap: 5 },
  plot: { height: 92, borderLeftWidth: 1, borderBottomWidth: 1, borderColor: '#BCC3D6', justifyContent: 'center', alignItems: 'center' },
  gridHorizontal: { position: 'absolute', left: 0, right: 0, height: 1, backgroundColor: '#DEDDEF' },
  gridVertical: { position: 'absolute', top: 0, bottom: 0, width: 1, backgroundColor: '#E7E4F3' },
  chartMessage: { backgroundColor: '#F7F5FF', padding: 4, textAlign: 'center', color: '#52637D', fontSize: 12 },
  legendDot: { width: 9, height: 9, borderRadius: 5 },
  segmented: { flexDirection: 'row', borderWidth: 1, borderColor: '#CBD3DF', borderRadius: 9, overflow: 'hidden' },
  segment: { flex: 1, minHeight: 36, paddingVertical: 6, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF' },
  fact: { flexDirection: 'row', borderTopWidth: 1, borderColor: '#E8DFCC', paddingVertical: 6, gap: 8 },
  factLabel: { color: '#182D50', fontWeight: '700', width: 70, fontSize: 12 },
  factValue: { color: '#33486B', flex: 1, fontSize: 12, lineHeight: 18 },
  brokerBadge: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  stageLine: { position: 'absolute', left: '12%', right: '12%', top: 9, height: 1, backgroundColor: '#ADB9D5' },
});
function SectionHeading({ icon, title }) {
  return <View style={[s.row, { flexWrap: 'nowrap', flexShrink: 1 }]}><Text accessible={false} style={{ color: '#006346', fontSize: 22 }}>{icon}</Text><Text style={[s.heading, { flexShrink: 1 }]}>{title}</Text></View>;
}
function BrokerBadge({ broker }) {
  return <View accessible={false} style={[s.brokerBadge, { backgroundColor: broker === 'kraken' ? '#7955DA' : '#F3CE59' }]}>
    <Text style={{ color: broker === 'kraken' ? '#FFFFFF' : '#4C3B00', fontWeight: '800', fontSize: 19 }}>{broker === 'kraken' ? 'K' : 'A'}</Text></View>;
}
function LearningComparisonChart({ period }) {
  return <View style={s.chart} accessibilityLabel="Kraken simulated comparison chart. Awaiting comparison results. No results plotted.">
    <View style={s.footer}><Text style={[s.small, { color: '#633BC1', fontWeight: '700' }]}>Kraken · simulated comparison</Text>
    <View style={[s.row, { gap: 4 }]}>
      <View style={[s.legendDot, { backgroundColor: '#00884A' }]} /><Text style={s.small}>Proposed rule</Text>
      <View style={[s.legendDot, { backgroundColor: '#8B93AC' }]} /><Text style={s.small}>Unchanged rule</Text>
    </View></View>
    <Text style={s.small}>Indexed value · scale pending</Text>
    <View style={s.plot}>
      {[0, 25, 50, 75].map(p => <View key={'h' + p} style={[s.gridHorizontal, { top: p + '%' }]} />)}
      {[25, 50, 75, 100].map(p => <View key={'v' + p} style={[s.gridVertical, { left: p + '%' }]} />)}
      <Text style={s.chartMessage}>Awaiting comparison results</Text>
    </View>
    <Text style={[s.small, { textAlign: 'center' }]}>{periodLabel(period)} · UTC</Text>
    <Text style={s.small}>No paired rule experiment recorded · after estimated costs.</Text>
  </View>;
}
function Action({ label, onPress, selected, disabled, grow, compact, link }) {
  return <TouchableOpacity accessibilityRole="button" accessibilityState={{ selected: !!selected, disabled: !!disabled }}
    disabled={disabled} onPress={onPress} style={[s.button, compact && s.compactButton, link && s.link, grow && s.grow, selected && s.active, disabled && s.muted]}>
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
  const wide = useWindowDimensions().width >= 600;
  const [opportunityBroker, setOpportunityBroker] = useState('all');
  const [notes, setNotes] = useState(false);
  const preview = (data.opportunity_previews || []).find(p => opportunityBroker === 'all' || p.broker === opportunityBroker);
  const latest = data.reviews[0];
  const lesson = latest?.lessons?.[0] || latest?.what_happened || 'No lesson is recorded for this period yet. Evidence is still being gathered.';
  const count = data.unavailable.includes('lesson proposals') ? '—' : data.proposals.reduce((n, x) => n + Number(x.total || 0), 0);
  return <View style={s.page}>
    <View><Text style={s.title}>What are we learning?</Text><Text style={s.body}>From decisions to evidence.</Text></View>
    <View style={[s.card, s.summary]}>
      <LearningCloud wide={wide} />
      <View style={s.summaryContent}>
        <View style={{ paddingRight: wide ? 180 : 65 }}><SectionHeading icon="▤" title="Learning summary" /></View>
        <View style={[s.segmented, wide && { width: '65%' }]}>{['daily', 'weekly', 'monthly'].map(p => <TouchableOpacity key={p} accessibilityRole="tab"
          accessibilityState={{ selected: p === period }} style={[s.segment, p === period && s.active]} onPress={() => onPeriod(p)}>
          <Text style={[s.buttonText, p === period && s.selectedText]}>{p[0].toUpperCase() + p.slice(1)}</Text></TouchableOpacity>)}</View>
        <View style={[s.row, { justifyContent: 'center' }]}><Action compact link label="‹" onPress={() => onMove(-1)} disabled={anchor <= '2020-01-01'} />
          <Text style={[s.small, { textAlign: 'center', flexShrink: 1 }]}>{periodLabel(data.period)} · UTC</Text>
          <Action compact link label="›" onPress={() => onMove(1)} disabled={shiftedDate(data.period.start, period, 1) > today} /></View>
        <Text style={[s.badge, { alignSelf: 'center' }]}>{data.period.in_progress ? '◷ In progress' : 'Period complete · evidence may update'}</Text>
        <Text style={s.heading}>{period === 'daily' ? "The day's learning" : period === 'weekly' ? "The week's learning" : "The month's learning"}</Text>
        <Text style={s.body}>{lesson}</Text>
        <Text style={s.small}>Recorded hypothesis—not proven improvement.</Text>
        {data.unavailable.length > 0 && <Text style={s.badge}>Unavailable: {data.unavailable.join(', ')}</Text>}
        {[['Evidence', data.unavailable.length ? 'Some evidence is unavailable; see details below.' : `${data.outcomes.reduce((n, o) => n + o.total, 0)} completed outcomes · ${data.review_count ?? 'Unknown'} reviews · ${data.shadows.reduce((n, o) => n + o.total, 0)} shadow candidates`],
          ['Next test', 'Compare a named lesson against unchanged rules.'], ['Decision', 'No rule change is made by this report.']].map(([label, value]) => <View key={label} style={s.fact}><Text style={s.factLabel}>{label}</Text><Text style={s.factValue}>{value}</Text></View>)}
        <Action compact link label="Read trade reviews →" onPress={() => onOpen('reviews')} />
        <Text style={s.small}>Daily, weekly and monthly evidence · earlier reports may update.</Text>
      </View>
    </View>
    <View style={s.card}>
      <View style={[wide ? [s.footer, { flexWrap: 'nowrap' }] : { gap: 6 }]}><SectionHeading icon="▥" title="Is learning helping?" />
        <View style={[s.segmented, { width: 170, alignSelf: 'flex-end' }]}>{[['daily', 'Today'], ['weekly', 'This week']].map(([p, label]) => <TouchableOpacity key={p} accessibilityRole="tab" accessibilityState={{ selected: period === p }} onPress={() => onPeriod(p)} style={[s.segment, period === p && s.active]}><Text style={[s.buttonText, period === p && s.selectedText]}>{label}</Text></TouchableOpacity>)}</View></View>
      <Text style={s.badge}>Not enough evidence yet</Text>
      <View style={s.row}><View style={s.metric}><Text style={s.value}>{count}</Text><Text style={s.small}>proposals recorded</Text></View>
        <View style={s.metric}><Text style={s.value}>{data.review_count ?? '—'}</Text><Text style={s.small}>reviews written</Text></View>
        <View style={s.metric}><Text style={s.value}>—</Text><Text style={s.small}>validated change</Text></View></View>
      <LearningComparisonChart period={data.period} />
      <View style={s.footer}><Text style={[s.small, s.footerNote]}>Reviews alone do not prove improvement.</Text><Action compact label="View proposed lessons →" onPress={() => onOpen('proposals')} /></View>
    </View>
    <View style={s.card}><View style={wide ? [s.footer, { flexWrap: 'nowrap' }] : { gap: 6 }}><SectionHeading icon="⊘" title="Rejected opportunities" />
      <View style={[s.row, { alignSelf: 'flex-end', gap: 4 }]}>{['all', 'kraken', 'alpaca'].map(b => <Action compact key={b} label={b[0].toUpperCase() + b.slice(1)} selected={b === opportunityBroker} onPress={() => setOpportunityBroker(b)} />)}</View></View>
      <Text style={s.small}>{data.unavailable.includes('rejection events') ? 'Rejection counts unavailable' : data.rejections.reduce((n, x) => n + Number(x.events), 0) + ' rejection events'} · includes repeated checks.</Text>
      <BrokerCard broker={preview?.broker || (opportunityBroker === 'all' ? 'kraken' : opportunityBroker)}>
        {preview ? <><View style={s.row}><BrokerBadge broker={preview.broker} /><Text style={[s.body, { fontWeight: '700', flexShrink: 1 }]}>{preview.symbol} · {preview.broker}</Text><Text style={s.badge}>SIMULATED</Text></View>
          <Text style={s.body}>{preview.reason ? humanStatus(preview.reason) : 'Rejection reason not recorded'}</Text>
          <View style={{ flexDirection: wide ? 'row' : 'column', gap: 10 }}><View style={[s.row, { flex: wide ? 3 : undefined, backgroundColor: 'rgba(255,255,255,0.55)', borderRadius: 8 }]}>{[['Entry', preview.intended_entry], ['Target', preview.take_profit], ['Stop', preview.stop_loss]].map(([label, value]) => <View key={label} style={s.metric}><Text style={s.small}>{label}</Text><Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8} accessibilityLabel={label + ': ' + (value ?? 'Unknown')} style={[s.body, { fontWeight: '700' }]}>{priceText(value)}</Text></View>)}</View>
          <View style={{ flex: wide ? 2 : undefined, gap: 4 }}>
          <Text style={s.badge}>{humanStatus(preview.outcome_status)}</Text>
          <Text style={s.small}>{typeof preview.estimated_net_r === 'number' ? `Estimated net outcome: ${preview.estimated_net_r.toFixed(2)}R (planned risk, not currency).` : 'Estimated outcome pending / unknown.'}</Text>
          </View></View>
          <Action compact link label="View tracked opportunities →" onPress={() => onOpen('rejected')} />
        </> : <Text style={s.body}>No linked rejected-opportunity preview is available for this selection.</Text>}
      </BrokerCard>
      {!preview && <Action compact link label="View tracked opportunities →" onPress={() => onOpen('rejected')} />}
      <View style={s.footer}><Text style={[s.small, s.footerNote]}>Simulated, not verified fills · prices rounded.</Text>
      <Action compact label="View rejected decisions →" onPress={() => onOpen('decisions')} /></View>
    </View>
    <View style={s.card}><SectionHeading icon="✓" title="Completed trades" />
      {['kraken', 'alpaca'].map(b => { const row = data.outcomes.find(o => o.broker === b); return <BrokerCard key={b} broker={b}>
        <TouchableOpacity accessibilityRole="button" accessibilityLabel={'Review ' + b + ' completed trades'} onPress={() => onOpen('trades', b)} style={[s.row, { flexWrap: 'nowrap', gap: 6 }]}><BrokerBadge broker={b} /><View style={{ flex: 1 }}><Text style={[s.body, { fontWeight: '700' }]}>{b === 'kraken' ? 'Kraken' : 'Alpaca'} <Text style={[s.small, { color: b === 'kraken' ? '#633BC1' : '#835500' }]}>· {b === 'kraken' ? 'LIVE' : 'PAPER'}</Text></Text>
          {!wide && <Text style={s.small}>{b === 'kraken' ? 'Net result' : 'Before fees'}</Text>}</View>
          {wide && <Text style={s.small}>{b === 'kraken' ? 'Recorded net result' : 'Before unreconciled fees'}</Text>}
          <Text style={[s.value, { fontSize: 17, textAlign: 'right', color: row?.pnl < 0 ? '#B42318' : row?.pnl > 0 ? '#006A3B' : '#182D50' }]}>{row ? resultText(row.pnl, b) : data.unavailable.includes('completed trades') ? 'Unavailable' : '—'}</Text><Text style={s.body}>›</Text></TouchableOpacity>
        {data.unavailable.includes('completed trades') && <Text style={s.small}>Completed-trade evidence could not be loaded.</Text>}
      </BrokerCard>; })}
      <View style={s.footer}><Text style={[s.small, s.footerNote]}>AI-managed trades · Alpaca fees unreconciled.</Text><Action compact label="Review completed trades →" onPress={() => onOpen('trades')} /></View>
    </View>
    <View style={s.card}><SectionHeading icon="⚗" title="Strategy research & testing" />
      <View style={{ flexDirection: 'row', marginVertical: 4 }}><View style={s.stageLine} />{['Research', 'Backtest', 'Shadow', 'Review'].map(stage => <View key={stage} style={{ flex: 1, alignItems: 'center', gap: 8 }}><View style={{ width: 19, height: 19, borderRadius: 10, borderWidth: 2, borderColor: '#ADB9D5', backgroundColor: '#FFFFFF' }} /><Text style={s.small}>{stage}</Text></View>)}</View>
      <BrokerCard><View style={wide ? s.footer : { gap: 4 }}><View style={{ flex: wide ? 1 : undefined }}><Text style={[s.body, { fontWeight: '700' }]}>{data.strategy_preview?.name || 'Awaiting a strategy record'}</Text>
        <Text numberOfLines={2} style={s.small}>{data.strategy_preview?.purpose || 'Recorded strategy ideas will appear here.'}</Text></View>
        <Text style={s.badge}>{data.strategy_preview ? humanStatus(data.strategy_preview.production_status) : 'No candidate selected'}</Text></View>
      </BrokerCard>
      <View style={[s.row, { flexWrap: 'nowrap' }]}><Action compact grow selected label="Strategy ideas" onPress={() => onOpen('strategies')} /><Action compact grow label="Test results" onPress={() => onOpen('tests')} /></View>
      <Text style={s.small}>Research stages, not verified progress · {data.backtest_count ?? 'Unknown'} backtest records.</Text>
    </View>
    <Action compact link label={notes ? 'Hide evidence notes −' : 'Evidence notes & limitations +'} onPress={() => setNotes(v => !v)} />
    {notes && <View style={s.card}><Text style={s.small}>Evidence updated {data.generated_at}. Cached for up to 10 minutes.</Text>
      <Text style={s.small}>{data.assessment.explanation}</Text>
      <Text style={s.small}>Simulations assume entry and use stop-first daily candles with estimated costs. Prices are rounded; exact prices appear in tracked opportunities. External discovery and paired rule experiments are not connected yet.</Text>
      {data.caveats.map(note => <Text key={note} style={s.small}>• {note}</Text>)}</View>}
  </View>;
}
function EvidenceRow({ row, kind }) {
  const [expanded, setExpanded] = useState(false);
  return <BrokerCard broker={row.broker}>
    <Text style={[s.body, { fontWeight: '700' }]}>{row.symbol || row.name || row.proposal_type || row.strategy_id || 'Recorded evidence'}{row.broker ? ' · ' + row.broker : ''}</Text>
    <Text style={s.small}>{row.created_at}</Text>
    {kind === 'rejected' && <><Text style={s.badge}>SIMULATED · {humanStatus(row.outcome_status)}</Text>
      <Text style={s.body}>{row.reason || 'Reason not recorded'}</Text><Text style={s.small}>{row.provenance}</Text>
      <View style={s.row}>{[['Entry', row.intended_entry], ['Target', row.take_profit], ['Stop', row.stop_loss]].map(([label, v]) => <View key={label} style={s.metric}><Text style={s.small}>{label}</Text><Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8} style={[s.body, { fontWeight: '700' }]}>{priceText(v)}</Text></View>)}</View>
      <Text selectable style={s.small}>Exact recorded prices: entry {row.intended_entry ?? 'unknown'} · target {row.take_profit ?? 'unknown'} · stop {row.stop_loss ?? 'unknown'}</Text>
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
  useEffect(() => { if (matchesLearningView(data, detail) && onNavigate) onNavigate(Boolean(detail)); }, [data, detail, onNavigate]);
  const open = (kind, selectedBroker = 'all') => { if (onNavigate) onNavigate(true); setPage(0); setBroker(selectedBroker); setDetail(kind); };
  if (busy || error || !matchesLearningView(data, detail)) return <View style={s.card}>{detail && <Action label="‹ Back to Learning" onPress={() => setDetail(null)} />}
    <Text style={s.heading}>Learning</Text>{!error ? <ActivityIndicator /> : <Action label="Retry" onPress={() => setRetry(n => n + 1)} />}<Text style={s.body}>{error || 'Loading compact evidence…'}</Text></View>;
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
