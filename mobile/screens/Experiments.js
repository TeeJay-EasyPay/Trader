'use strict';
const React = require('react');
const { useEffect, useState } = React;
const { View, Text, TouchableOpacity, ActivityIndicator, StyleSheet, TextInput } = require('react-native');
const { experimentTimeline } = require('../lib/experimentTimeline');
const s = StyleSheet.create({
  card: { backgroundColor: '#FFFFFF', padding: 14, borderWidth: 1, borderColor: '#DCE4E7', borderRadius: 12, gap: 10, marginVertical: 6 },
  title: { fontSize: 22, color: '#102A43', fontWeight: '700' },
  text: { fontSize: 14, color: '#243C60', lineHeight: 21 },
  small: { fontSize: 12, color: '#52637D', lineHeight: 18 },
  button: { borderWidth: 1, borderColor: '#B7CAC6', borderRadius: 8, padding: 12, minHeight: 44 },
  primary: { backgroundColor: '#00563E' },
  buttonText: { color: '#00563E', fontWeight: '700', textAlign: 'center' },
  error: { color: '#B42318', fontSize: 14 },
  input: { borderWidth: 1, borderColor: '#CBD5DE', padding: 10, borderRadius: 6, color: '#102A43' },
});
function Button({ label, onPress, disabled, primary }) {
  return <TouchableOpacity accessibilityRole="button" accessibilityState={{ disabled: !!disabled }} disabled={disabled} onPress={onPress}
    style={[s.button, primary && s.primary, disabled && { opacity: .5 }]}><Text style={[s.buttonText, primary && { color: '#FFFFFF' }]}>{label}</Text></TouchableOpacity>;
}
const human = text => String(text || '').replace(/_/g, ' ');
const money = (n, currency = 'USD') => typeof n === 'number' ? (currency === 'GBP' ? '£' : '$') + n.toFixed(2) : 'Not available';
function TestingJourney({ data }) {
  const time = experimentTimeline(data);
  return <View style={s.card}><Text style={s.title}>Testing journey</Text>
    <Text style={s.text}>Now: {time.stage}</Text>
    <Text style={s.text}>Started: {time.start}{'\n'}Planned observation period: {time.planned}{'\n'}{time.elapsedLabel}: {time.elapsed}</Text>
    <Text style={s.text}>{time.ended ? 'Ended: ' + time.end : 'Next weekly review: ' + time.target}{'\n'}{time.remaining}</Text>
    <Text style={s.small}>Dates and times use your device timezone. Calendar duration includes waiting, closed markets and pauses; it is not time spent placing trades.</Text>
    <Text style={s.text}>1. Record the hypothesis and freeze the rules.{ '\n' }2. Assess new opportunities; record skips or simulate entries.{ '\n' }3. Follow simulated positions and collect outcomes.{ '\n' }4. Evaluate evidence, then request approval only if supported.</Text>
    <Text style={s.small}>Each stage depends on opportunities and market data; there is no promised date for the first simulated trade. Opportunities and completed pairs can include skips, not completed trades.</Text>
    {time.graceEnd && <Text style={s.small}>Unresolved outcomes can have up to 15 extra calendar days, through {time.graceEnd}. If still unresolved then, the next worker review ends the test with insufficient evidence.</Text>}
    {data.spec?.minimum_opportunities && <Text style={s.small}>Minimum evidence: {data.spec.minimum_opportunities} usable paired opportunities across {data.spec.minimum_symbol_days} symbol-days, plus the frozen independence, cost and risk checks.</Text>}
    <Text style={s.text}>Final result: {time.verdict}</Text>
    <Text style={s.small}>The target date is an evaluation checkpoint, not a promise of improved trading. Minimum sample and quality checks must pass; any strategy use still follows its approval process.</Text>
  </View>;
}
function ExperimentDetail({ request, id, onBack }) {
  const [data, setData] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(null), [capital, setCapital] = useState('100');
  async function load() {
    setBusy(true); setError('');
    try { setData(await request('/experiments/detail?id=' + encodeURIComponent(id))); }
    catch (e) { setError(e.message || 'Experiment could not be loaded'); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); }, [id, request]);
  async function approve() {
    setBusy(true); setError('');
    try {
      const scope = confirm === 'enable_paper' ? { max_notional_usd: Number(capital), expires_at: new Date(Date.now() + 7 * 86400000).toISOString() }
        : confirm === 'request_development' ? { requirements: 'Implement reviewed strategy version ' + data.version + ': ' + data.spec.hypothesis,
          acceptance_tests: 'Preserve risk and fee checks; verify execution, exact-version decision attribution and rollback. No live activation.' } : {};
      const result = await request('/experiments/decision', { method: 'POST', body: JSON.stringify({ id, version: data.version,
        revision: data.revision, action: confirm, confirmed: true, scope,
        idempotency_key: id + ':' + data.revision + ':' + confirm }) });
      setData(result); setConfirm(null);
    } catch (e) { setError(e.message || 'Approval not recorded. Refresh before retrying.'); }
    finally { setBusy(false); }
  }
  const actions = data?.status === 'recommended' ? [['approve_library', 'Approve for strategy library'], ['reject', 'Reject recommendation']]
    : ['library_approved', 'ready_for_activation'].includes(data?.status) ? [
      ...(data?.spec?.broker === 'alpaca' && data?.spec?.rule_type === 'minimum_target_r' ? [['enable_paper', 'Review Alpaca paper activation']] : []),
      ...(data?.status === 'library_approved' ? [['request_development', 'Request implementation review']] : []), ['reject', 'Reject']]
    : data?.status === 'implementation_required' ? [['approve_implementation', 'Approve implementation'], ['reject', 'Reject request']]
    : ['shadow_running', 'paper_active'].includes(data?.status) ? [['suspend', 'Suspend']] : [];
  return <View style={s.card}><Button label="Back" onPress={onBack} /><Text style={s.title}>Experiment report</Text>
    {busy && <ActivityIndicator />}{!!error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}
    <Button label="Refresh report" disabled={busy} onPress={load} />
    {data && <><Text style={s.text}>Hypothesis: {data.spec.hypothesis}</Text><Text style={s.small}>{human(data.status)} · {human(data.spec.broker)} · {data.spec.currency || 'USD'} · SIMULATED</Text>
      <Text style={s.text}>Problem: {data.spec.problem || 'See hypothesis'}{'\n'}Intended benefit: {data.spec.expected_benefit || 'Not yet documented'}</Text>
      <Text style={s.small}>Priority {data.spec.priority || 3} (1 is highest). {data.status === 'queued' ? 'Waiting for a resource slot. Testing has not started; dates are set when it starts.' : 'The worker shares a capped daily observation budget across experiments.'}</Text>
      <Text selectable style={s.small}>Version {data.version.slice(0, 12)} · {data.created_at}</Text>
      {data.status !== 'queued' && <TestingJourney data={data} />}
      {!!data.report.reason && <Text style={s.text}>Evaluation note: {data.report.reason}</Text>}
      {!!data.state?.supersedes && <Text style={s.small}>Fresh prospective comparison following an engine update. Previous experiment: {data.state.supersedes}. Its observations are not pooled into this version.</Text>}
      <Text style={s.text}>Baseline: recorded eligibility. Candidate: require target / planned risk of at least {data.spec.threshold}. Targets are not expected returns.</Text>
      <Text style={s.small}>Both portfolios use the same estimated fills and costs. No broker orders are sent by simulations.</Text>
      <Text style={s.small}>{data.spec.rule_type === 'replace_target_r_gate' ? 'Candidate may replace only a recorded target/risk rejection. Unknown reasons or any other failed safeguard still mean skip.' : 'This candidate only filters baseline-eligible entries.'}</Text>
      <Text style={s.text}>{data.report.observations ?? 'Not yet reported'} opportunities · {data.report.completed ?? 'Not yet reported'} resolved pairs (including skips) · {data.report.uncertain ?? 'Not yet reported'} uncertain.</Text>
      <Text style={s.text}>Closed simulated trades: baseline {data.report.closed_trades?.baseline ?? 'Not reported'} / candidate {data.report.closed_trades?.candidate ?? 'Not reported'}{'\n'}Skipped: {data.report.skipped?.baseline ?? 'Not reported'} / {data.report.skipped?.candidate ?? 'Not reported'}</Text>
      <Text style={s.text}>Baseline realised: {money(data.report.baseline?.realised, data.spec.currency)}{ '\n' }Candidate realised: {money(data.report.candidate?.realised, data.spec.currency)}</Text>
      <Text style={s.small}>Virtual equity including open positions: {money(data.report.baseline?.equity, data.spec.currency)} / {money(data.report.candidate?.equity, data.spec.currency)}</Text>
      <View style={s.card}><Text style={s.title}>Simulation versus broker</Text>
        <Text style={s.text}>{human(data.state?.execution_validation?.status || 'not yet compared')}</Text>
        <Text style={s.small}>Matched outcomes: {data.state?.execution_validation?.compared ?? 0}; within tolerance: {data.state?.execution_validation?.within_tolerance ?? 0}; missing costs: {data.state?.execution_validation?.missing_costs ?? 'not checked'}.</Text>
        <Text style={s.small}>Checks entry price, exit price, holding time and costs. Missing/ambiguous matches cannot validate the simulator. Alpaca paper agreement does not establish live execution quality.</Text>
        {(data.state?.execution_validation?.examples || []).map(p => <Text key={p.source_id} style={s.small}>{p.source_id}: entry {p.differences.entry_bps.toFixed(1)} bps, exit {p.differences.exit_bps.toFixed(1)} bps, duration {p.differences.holding_hours.toFixed(1)} hours difference; cost {p.differences.cost_bps == null ? 'unknown' : p.differences.cost_bps.toFixed(1) + ' bps difference'}.</Text>)}
      </View>
      {data.state?.adoption_monitor && <View style={s.card}><Text style={s.title}>Use and monitoring</Text>
        <Text style={s.text}>{human(data.state.adoption_monitor.status)} · {data.state.adoption_monitor.reason || 'Approved paper version checked'}</Text>
        <Text style={s.small}>{data.state.adoption_monitor.decisions} attributed decisions; {data.state.adoption_monitor.completed} completed outcomes; {data.state.adoption_monitor.verified_cost_outcomes} with verified costs. Checked {data.state.adoption_monitor.checked_at}.</Text>
      </View>}
      <Text style={s.small}>Costs: {data.spec.costs_status}. Evaluation after {data.report.evaluate_after || 'the frozen test period'}. {data.report.caveat}</Text>
      <Text style={s.small}>Source outcomes: {data.spec.evidence_ids.join(', ')}. Saving never activates trading. Live activation is disabled for this rollout.</Text>
      {actions.map(([action, label]) => <Button key={action} label={label} disabled={busy} onPress={() => setConfirm(action)} />)}
      {confirm && <View style={s.card}><Text style={s.text}>Confirm: {human(confirm)} for version {data.version.slice(0, 12)}?</Text>
        <Text style={s.small}>Library approval stores acceptance only. Implementation approval permits development, not live trading.</Text>
        {confirm === 'enable_paper' && <><Text style={s.small}>Alpaca paper only · expires in 7 days. Automatically suspend this variant if recorded after-cost losses reach 5% of the per-order cap, cost evidence is missing, or the approved baseline changes. Existing exits stay intact. Maximum notional per order (USD):</Text>
          <TextInput accessibilityLabel="Paper maximum order notional in dollars" keyboardType="numeric" value={capital} onChangeText={setCapital} style={s.input} /></>}
        <Button primary label="Confirm this exact action" disabled={busy} onPress={approve} /><Button label="Cancel" disabled={busy} onPress={() => setConfirm(null)} /></View>}
      <Text style={s.title}>History</Text>{(data.events || []).map((e, i) => <Text key={i} style={s.small}>{e.created_at} · {human(e.action)}</Text>)}
      <Text style={s.title}>Weekly findings</Text>
      {(data.events || []).filter(e => e.action === 'weekly_review').map((event,i) => {
        let review; try { review = JSON.parse(event.payload_json); } catch (_) { return null; }
        return <View key={i} style={s.card}><Text style={s.text}>Week {review.cycle}: {review.what_was_learnt}</Text>
          <Text style={s.small}>{event.interpretation?.status === 'completed' ? "Trader's interpretation: "+event.interpretation.summary : 'AI interpretation '+(event.interpretation?.status || 'pending')+'; numerical findings remain available.'}</Text>
          <Text style={s.small}>{review.future_use}{'\n'}{review.next_review_at ? 'Next review: '+review.next_review_at : 'Review ended the test.'}</Text></View>;
      })}
      <Text style={s.title}>Recent paired opportunities</Text>
      {(data.opportunities || []).map(o => <Text key={o.source_id} style={s.small}>{o.time} · {o.symbol}{'\n'}Baseline: {human(o.arms.baseline.status)} ({o.arms.baseline.reason}); candidate: {human(o.arms.candidate.status)} ({o.arms.candidate.reason}). {o.uncertain ? 'Uncertain: ' + o.quality : ''}</Text>)}
      <Text style={s.small}>Latest 20 opportunities shown; headline totals cover the full experiment.</Text>
      <Text style={s.small}>Approvals and implementation progress share this same record in Learning, Executive Briefing and Notifications.</Text>
    </>}
  </View>;
}
function ExperimentsCard({ request, notifications = false, onBack }) {
  const [data, setData] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(null), [attention, setAttention] = useState(notifications);
  const [section, setSection] = useState('running');
  async function load(more = false) {
    setBusy(true); setError('');
    try {
      const result = await request('/experiments?attention=' + attention + (notifications ? '' : '&view='+section) + (more && data?.next_cursor ? '&before=' + encodeURIComponent(data.next_cursor) : ''));
      setData(old => more ? { ...result, items: [...(old?.items || []), ...result.items] } : result);
    } catch (e) { setError(e.message || 'Experiments unavailable'); } finally { setBusy(false); }
  }
  useEffect(() => { setData(null); load(); }, [attention, section, request]);
  if (selected) return <ExperimentDetail request={request} id={selected} onBack={() => { setSelected(null); load(); }} />;
  return <View style={s.card}>{onBack && <Button label="Back to Executive Briefing" onPress={onBack} />}
    <Text style={s.title}>{notifications ? 'Notifications' : 'Experiments'}</Text>
    <Text style={s.small}>{notifications ? 'Strategy requests and approval history' : 'Evidence → proposed rule → paired simulation → review'}</Text>
    {notifications && <Button label={attention ? 'View history and all experiments' : 'View needs attention'} onPress={() => setAttention(v => !v)} />}
    {!notifications && <View style={{ gap:6 }}>{[['running','Running'],['queued','Queued'],['history','Previous tests'],['attention','Needs attention']].map(([key,label]) =>
      <Button key={key} label={label} primary={section === key} onPress={() => { setSection(key); setAttention(key === 'attention'); }} />)}</View>}
    {busy && <ActivityIndicator />}{!!error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}
    {data && <Text style={s.small}>{data.policy.enabled ? 'Shadow worker enabled within resource limits.' : 'Shadow worker disabled.'} Live activation is disabled.</Text>}
    {!!data?.pipeline?.length && <Text style={s.text}>Pipeline: {data.pipeline.map(p => human(p.status) + ' ' + p.count).join(' · ')}</Text>}
    {!!data?.last_review?.status && <Text style={s.small}>Latest proposal review: {human(data.last_review.status)} · {data.last_review.day}. {data.last_review.reason || ''}</Text>}
    {!!data?.worker?.at && <Text style={s.small}>Worker checked {data.worker.at}: {human(data.worker.status)}.</Text>}
    {!!data?.evidence_coverage?.brokers && <View style={s.card}><Text style={s.title}>Learning evidence coverage</Text>
      {data.evidence_coverage.brokers.map(b => <Text key={b.broker} style={s.small}>{human(b.broker)}: {b.outcomes} outcomes; {b.linked_decisions} linked decisions; {b.canonical_closures} canonical closures; {b.known_costs} with known costs; {b.meaningful_exit_labels} meaningful exit labels.</Text>)}
      <Text style={s.small}>{data.evidence_coverage.caveat} Checked {data.evidence_coverage.checked_at}.</Text>
    </View>}
    {data?.items?.filter(row => notifications || section === 'attention' || (section === 'running' ? row.status === 'shadow_running' : section === 'queued' ? row.status === 'queued' : !['queued','shadow_running'].includes(row.status))).map(row => <View key={row.id} style={s.card}>
      <Button label={human(row.status) + ' · Hypothesis: ' + row.hypothesis} onPress={() => setSelected(row.id)} />
      <Text style={s.small}>{human(row.broker || 'alpaca')} · Priority {row.priority || 3}{'\n'}Problem: {row.problem || row.hypothesis}{'\n'}Intended benefit: {row.expected_benefit || 'See report'}</Text>
      <Text style={s.small}>{row.status === 'queued' ? 'Queued — test has not started. Review date is set when a slot opens.' : row.status !== 'shadow_running' ? 'Ended: ' + experimentTimeline(row).end + '\n' + (row.report?.reason || human(row.status)) : 'Started: ' + experimentTimeline(row).start + '\nNext weekly review: ' + experimentTimeline(row).target + '\n' + experimentTimeline(row).remaining}</Text>
      <Text style={s.small}>Tap the hypothesis for duration, testing stages and results.</Text>
    </View>)}
    {data && !data.items.length && <Text style={s.text}>{attention ? 'No strategy request needs your approval.' : section === 'running' ? 'No experiment recorded yet in Running. Check Queued or Previous tests. Reviews alone do not demonstrate improvement.' : 'No records in this section.'}</Text>}
    <Button label="Refresh" disabled={busy} onPress={() => load()} />
    {!!data?.next_cursor && <Button label="Load older records" disabled={busy} onPress={() => load(true)} />}
  </View>;
}
function ExperimentPrompt({ request, onOpen }) {
  const [count, setCount] = useState(null);
  useEffect(() => { let active = true; request('/experiment-notifications?attention=true').then(d => { if (active) setCount(d.items.length); }).catch(() => { if (active) setCount(null); }); return () => { active = false; }; }, [request]);
  return <View style={s.card}><Text style={s.text}>{count === null ? 'Strategy requests: check notification history.' : count ? count + ' strategy request(s) ready for review.' : 'No strategy approval is pending.'}</Text>
    <Button label="Notifications and strategy approvals" onPress={onOpen} /></View>;
}
module.exports = { ExperimentsCard, ExperimentPrompt, ExperimentDetail, TestingJourney };
