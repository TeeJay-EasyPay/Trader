'use strict';
const React = require('react');
const { View, Text, TextInput, TouchableOpacity } = require('react-native');
function StrategyImports({ request }) {
  const [open,setOpen]=React.useState(false), [items,setItems]=React.useState([]);
  const [error,setError]=React.useState(''), [busy,setBusy]=React.useState(false);
  const [draft,setDraft]=React.useState('');
  async function load() {
    setBusy(true);setError('');
    try { const data=await request('/experiments?view=queued');setItems(data.source_intake || []); }
    catch(e) {setError('Source records could not be loaded.');} finally {setBusy(false);}
  }
  async function action(body) {
    setBusy(true);setError('');
    try {await request('/experiments/decision',{method:'POST',body:JSON.stringify({...body,confirmed:true})});await load();}
    catch(e) {setError(String(e.message || 'Import could not be validated.'));} finally {setBusy(false);}
  }
  const button=(label,fn)=> <TouchableOpacity accessibilityRole="button" disabled={busy} onPress={fn} style={{padding:12,borderWidth:1,borderColor:'#CBD5DE',borderRadius:8}}><Text>{label}</Text></TouchableOpacity>;
  return <View style={{gap:8}}>
    {button(open ? 'Hide external strategy intake' : 'External strategy intake',()=>{setOpen(!open);if(!open)load();})}
    {open && <View style={{gap:8}}><Text>Curated imports only. No TradingView API connection or automatic copying. Importing does not activate trading.</Text>
      {items.map(item=><View key={item.id}><Text>{item.title} — {item.status.replace(/_/g,' ')}</Text><Text>{item.purpose}</Text><Text selectable>{item.url}</Text><Text>{item.limitations}</Text>
        {item.status==='eligible_for_testing' && button('Queue validated shadow test',()=>action({action:'queue_source',source_id:item.id}))}
        {item.linked_experiment && <Text>Linked experiment: {item.linked_experiment}</Text>}</View>)}
      <Text>Developer-curated import record (JSON). Include URL, author, title, purpose, broker, precise rules, license basis and review checks. Missing checks remain blocked.</Text>
      <TextInput accessibilityLabel="Curated strategy import JSON" multiline value={draft} onChangeText={setDraft} maxLength={18000} style={{minHeight:100,borderWidth:1,padding:8}} />
      {button('Save reviewed import record',()=>{try {action({action:'import_source',source:JSON.parse(draft)});}catch(e){setError('Enter valid JSON first.');}})}
      {busy && <Text>Working…</Text>}{!!error && <Text accessibilityRole="alert">{error}</Text>}
    </View>}
  </View>;
}
module.exports={StrategyImports};
