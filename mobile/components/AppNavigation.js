'use strict';
const React = require('react');
const { useState, useRef } = React;
const { View, Text, Image, Modal, Pressable, ScrollView, AccessibilityInfo, findNodeHandle } = require('react-native');
const { StatusPill } = require('./shared');
const ITEMS = [['ExecutiveBriefing','Executive Briefing'],['Portfolio','Portfolio'],
  ['Standup','Standup'],['RunCycle','Run a Cycle'],['Learning','Learning'],
  ['ExperimentNotifications','Notifications']];
function AppNavigation({ screen, onNavigate, badge }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef(null), first = useRef(null);
  const focus = ref => { const id = findNodeHandle(ref.current); if (id) AccessibilityInfo.setAccessibilityFocus(id); };
  const close = () => { setOpen(false); setTimeout(() => focus(trigger), 100); };
  return <View>
    <View style={{ flexDirection:'row', alignItems:'center', justifyContent:'space-between', gap:12 }}>
      <Pressable ref={trigger} accessibilityRole="button" accessibilityLabel="Open navigation menu"
        accessibilityState={{ expanded:open }} onPress={() => setOpen(true)}
        style={{ minWidth:48, minHeight:48, justifyContent:'center', alignItems:'center' }}>
        <Text accessible={false} style={{ fontSize:30, color:'#16324F' }}>☰</Text>
      </Pressable>
      <View style={{ flex:1, alignItems:'center' }} accessibilityLabel={'Application connection: '+badge.label}>
        <StatusPill label={badge.label} tone={badge.tone} />
      </View>
      <Image source={require('../assets/icon.png')} accessibilityLabel="AI Trader"
        style={{ width:44, height:44, borderRadius:10 }} resizeMode="contain" />
    </View>
    <Text accessibilityRole="header" style={{ color:'#16324F', fontSize:18, fontWeight:'700', marginBottom:4 }}>
      {ITEMS.find(i => i[0] === screen)?.[1] || screen}
    </Text>
    <Modal visible={open} transparent animationType="fade" onRequestClose={close} onShow={() => focus(first)}>
      <Pressable accessibilityLabel="Close navigation menu" onPress={close}
        style={{ flex:1, backgroundColor:'rgba(0,0,0,.35)', justifyContent:'center', padding:24 }}>
        <View accessibilityViewIsModal onStartShouldSetResponder={() => true}
          style={{ backgroundColor:'white', borderRadius:16, padding:16, maxHeight:'85%' }}>
          <ScrollView>
            <Text accessibilityRole="header" style={{ fontSize:22, marginBottom:12 }}>Navigate</Text>
            {ITEMS.map(([key,label], index) => <Pressable key={key} ref={index === 0 ? first : undefined}
              accessibilityRole="button" accessibilityState={{ selected:screen===key }}
              onPress={() => { onNavigate(key); close(); }}
              style={{ minHeight:48, padding:14, borderRadius:8, backgroundColor:screen===key?'#00563E':'white' }}>
              <Text style={{ color:screen===key?'white':'#16324F', fontWeight:'600' }}>{label}</Text>
            </Pressable>)}
            <Pressable accessibilityRole="button" onPress={close} style={{ padding:14, minHeight:48 }}><Text>Close menu</Text></Pressable>
          </ScrollView>
        </View>
      </Pressable>
    </Modal>
  </View>;
}
module.exports = { AppNavigation, ITEMS };
