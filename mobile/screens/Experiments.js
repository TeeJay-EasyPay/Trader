'use strict';
const React = require('react');
const { useEffect, useState } = React;
const { View, Text, TouchableOpacity, ActivityIndicator, StyleSheet, TextInput } = require('react-native');
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
const money = n => typeof n === 'number' ? '$' + n.toFixed(2) : 'Not available';
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
      const scope = confirm === 'enable_paper' ? { max_notional_usd: Number(capital), expires_at: new Date(Date.now() + 7 * 86400000).toISOString() } : {};
      const result = await request('/experiments/decision', { method: 'POST', body: JSON.stringify({ id, version: data.version,
        revision: data.revision, action: confirm, confirmed: true, scope,
        idempotency_key: id + ':' + data.revision + ':' + confirm }) });
      setData(result); setConfirm(null);
    } catch (e) { setError(e.message || 'Approval not recorded. Refresh before retrying.'); }
    finally { setBusy(false); }
  }
  const actions = data?.status === 'recommended' ? [['approve_library', 'Approve for strategy library'], ['reject', 'Reject recommendation']]
    : ['library_approved', 'ready_for_activation'].includes(data?.status) ? [['enable_paper', 'Review Alpaca paper activation'], ['reject', 'Reject']]
    : data?.status === 'implementation_required' ? [['approve_implementation', 'Approve implementation'], ['reject', 'Reject request']]
    : ['shadow_running', 'paper_active'].includes(data?.status) ? [['suspend', 'Suspend']] : [];
  return <View style={s.card}><Button label="Back" onPress={onBack} /><Text style={s.title}>Experiment report</Text>
    {busy && <ActivityIndicator />}{!!error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}
    <Button label="Refresh report" disabled={busy} onPress={load} />
    {data && <><Text style={s.text}>{data.spec.hypothesis}</Text><Text style={s.small}>{human(data.status)} · Alpaca · SIMULATED</Text>
      <Text selectable style={s.small}>Version {data.version.slice(0, 12)} · {data.created_at}</Text>
      <Text style={s.text}>Baseline: recorded eligibility. Candidate: require target / planned risk of at least {data.spec.threshold}. Targets are not expected returns.</Text>
      <Text style={s.small}>Both portfolios use the same estimated fills and costs. No broker orders are sent by simulations.</Text>
      <Text style={s.text}>{data.report.observations || 0} opportunities · {data.report.completed || 0} completed pairs · {data.report.uncertain || 0} uncertain.</Text>
      <Text style={s.text}>Baseline realised: {money(data.report.baseline?.realised)}{ '\n' }Candidate realised: {money(data.report.candidate?.realised)}</Text>
      <Text style={s.small}>Virtual equity including open positions: {money(data.report.baseline?.equity)} / {money(data.report.candidate?.equity)}</Text>
      <Text style={s.small}>Costs: {data.spec.costs_status}. Evaluation after {data.report.evaluate_after || 'the frozen test period'}. {data.report.caveat}</Text>
      <Text style={s.small}>Source outcomes: {data.spec.evidence_ids.join(', ')}. Saving never activates trading. Live activation is disabled for this rollout.</Text>
      {actions.map(([action, label]) => <Button key={action} label={label} disabled={busy} onPress={() => setConfirm(action)} />)}
      {confirm && <View style={s.card}><Text style={s.text}>Confirm: {human(confirm)} for version {data.version.slice(0, 12)}?</Text>
        <Text style={s.small}>Library approval stores acceptance only. Implementation approval permits development, not live trading.</Text>
        {confirm === 'enable_paper' && <><Text style={s.small}>Alpaca paper only · expires in 7 days. Maximum notional per order (USD):</Text>
          <TextInput accessibilityLabel="Paper maximum order notional in dollars" keyboardType="numeric" value={capital} onChangeText={setCapital} style={s.input} /></>}
        <Button primary label="Confirm this exact action" disabled={busy} onPress={approve} /><Button label="Cancel" disabled={busy} onPress={() => setConfirm(null)} /></View>}
      <Text style={s.title}>History</Text>{(data.events || []).map((e, i) => <Text key={i} style={s.small}>{e.created_at} · {human(e.action)}</Text>)}
      <Text style={s.small}>Approvals and implementation progress share this same record in Learning, Executive Briefing and Notifications.</Text>
    </>}
  </View>;
}
function ExperimentsCard({ request, notifications = false, onBack }) {
  const [data, setData] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(null), [attention, setAttention] = useState(notifications);
  async function load(more = false) {
    setBusy(true); setError('');
    try {
      const result = await request('/experiments?attention=' + attention + (more && data?.next_cursor ? '&before=' + encodeURIComponent(data.next_cursor) : ''));
      setData(old => more ? { ...result, items: [...(old?.items || []), ...result.items] } : result);
    } catch (e) { setError(e.message || 'Experiments unavailable'); } finally { setBusy(false); }
  }
  useEffect(() => { setData(null); load(); }, [attention, request]);
  if (selected) return <ExperimentDetail request={request} id={selected} onBack={() => { setSelected(null); load(); }} />;
  return <View style={s.card}>{onBack && <Button label="Back to Executive Briefing" onPress={onBack} />}
    <Text style={s.title}>{notifications ? 'Notifications' : 'Experiments'}</Text>
    <Text style={s.small}>{notifications ? 'Strategy requests and approval history' : 'Evidence → proposed rule → paired simulation → review'}</Text>
    {notifications && <Button label={attention ? 'View history and all experiments' : 'View needs attention'} onPress={() => setAttention(v => !v)} />}
    {busy && <ActivityIndicator />}{!!error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}
    {data && <Text style={s.small}>{data.policy.enabled ? 'Shadow worker enabled within resource limits.' : 'Shadow worker disabled.'} Live activation is disabled.</Text>}
    {!!data?.last_review?.status && <Text style={s.small}>Latest proposal review: {human(data.last_review.status)} · {data.last_review.day}. {data.last_review.reason || ''}</Text>}
    {!!data?.worker?.at && <Text style={s.small}>Worker checked {data.worker.at}: {human(data.worker.status)}.</Text>}
    {data?.items?.map(row => <Button key={row.id} label={human(row.status) + ' · ' + row.hypothesis} onPress={() => setSelected(row.id)} />)}
    {data && !data.items.length && <Text style={s.text}>{attention ? 'No strategy request needs your approval.' : 'No experiment recorded yet. Reviews alone do not demonstrate improvement.'}</Text>}
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
module.exports = { ExperimentsCard, ExperimentPrompt, ExperimentDetail };
