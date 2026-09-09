// 2026-09-09 Founder-approved warm palette and British racing-green controls.
// Exchange tint denotes identity, never profit or health. Keep semantic warning,
// loss, recording and disabled states distinct and preserve their explicit labels.
//
// Previous dark palette preserved at styles.js.darkbackup for an easy revert.
import { StyleSheet } from 'react-native';
import { palette } from './lib/palette';

export const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: palette.canvas,
  },
  header: {
    paddingHorizontal: 18,
    paddingTop: 10,
    paddingBottom: 8,
    backgroundColor: palette.canvas,
    borderBottomColor: '#cfe0f2',
    borderBottomWidth: 1,
  },
  headerTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    fontSize: 24,
    fontWeight: '800',
    color: '#123a63',
  },
  subtitle: {
    marginTop: 2,
    fontSize: 13,
    color: '#476582',
  },
  cacheBanner: {
    marginTop: 8,
    padding: 10,
    borderRadius: 8,
    backgroundColor: '#fef3c7',
    borderWidth: 1,
    borderColor: '#d97706',
  },
  cacheBannerHeadline: {
    fontSize: 13,
    fontWeight: '800',
    color: '#78350f',
  },
  cacheBannerDetail: {
    fontSize: 12,
    color: '#78350f',
    marginTop: 2,
  },
  cacheBannerRetry: {
    fontSize: 12,
    fontWeight: '800',
    color: '#3d8bfd',
    marginTop: 6,
  },
  tabs: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    padding: 10,
    backgroundColor: palette.canvas,
  },
  tab: {
    flexGrow: 1,
    flexBasis: '30%',
    minHeight: 48,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#c3d9f0',
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 6,
  },
  activeTab: {
    backgroundColor: palette.primary,
    borderColor: palette.primary,
  },
  tabText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#1f4c78',
    textAlign: 'center',
  },
  activeTabText: {
    color: '#ffffff',
  },
  // AT-ED-015 Section 11: the Executive Briefing is the app's primary landing entry, not one
  // equal-weight tab among several - a distinct, full-width button rendered above the regular
  // tab row so the Founder always sees it first.
  primaryTab: {
    minHeight: 56,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: palette.primary,
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 10,
    marginTop: 10,
  },
  primaryTabActive: {
    backgroundColor: palette.primary,
  },
  controlPressed: { backgroundColor: palette.pressed, borderColor: palette.pressed },
  primaryTabText: {
    fontSize: 15,
    fontWeight: '800',
    color: '#123a63',
    letterSpacing: 0.3,
  },
  primaryTabTextActive: {
    color: '#ffffff',
  },
  loading: {
    paddingVertical: 6,
    alignItems: 'center',
  },
  loadingText: {
    marginTop: 6,
    textAlign: 'center',
  },
  content: {
    padding: 14,
    paddingBottom: 32,
  },
  section: {
    marginBottom: 14,
    backgroundColor: '#ffffff',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#cfe0f2',
    padding: 16,
  },
  sectionTitle: {
    fontSize: 21,
    fontWeight: '800',
    color: '#16324f',
    marginBottom: 8,
  },
  collapsibleHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
  },
  collapsibleHeaderText: {
    flex: 1,
  },
  collapsibleChevron: {
    fontSize: 13,
    color: '#476582',
    marginLeft: 6,
  },
  collapsibleBody: {
    marginTop: 8,
  },
  summaryCard: {
    backgroundColor: '#ffffff',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#cfe0f2',
    padding: 14,
    marginBottom: 14,
  },
  greetingCard: { backgroundColor: palette.greeting, borderColor: palette.greetingBorder, overflow: 'hidden', minHeight: 148, padding: 20 },
  portfolioLinkSpacing: { marginTop: 4, marginBottom: 20 },
  greetingHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  greetingTitle: { flex: 1, fontSize: 23, paddingRight: 42 },
  greetingSun: { fontSize: 32, color: '#B77400' },
  bareSection: { marginBottom: 18 },
  accountMetricGrid: { flexDirection: 'row', flexWrap: 'wrap', borderTopWidth: 1, borderTopColor: '#DADDE8', marginTop: 10, paddingTop: 6 },
  accountMetricTile: { flexGrow: 1, flexBasis: '48%', minWidth: 120, paddingVertical: 8, paddingRight: 8 },
  accountMetricValue: { color: '#16324F', fontWeight: '800', fontSize: 22, marginTop: 3 },
  cycleButtonStack: { gap: 10, marginTop: 14 },
  cycleWarning: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#FFF2DD', padding: 14, borderRadius: 14, marginTop: 12 },
  cycleWarningIcon: { color: '#78350F', fontSize: 26, fontWeight: '800' },
  cycleWarningText: { flex: 1, color: '#78350F', fontSize: 14, lineHeight: 21 },
  bubbleHeading: { flexDirection: 'row', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 6 },
  bubbleTimestamp: { fontSize: 12, color: '#476582' },
  composerInput: { width: '100%', minHeight: 92, maxHeight: 160, textAlignVertical: 'top', borderWidth: 1, borderColor: '#CFE0F2', backgroundColor: '#FFFFFF', borderRadius: 12, padding: 12, color: '#16324F', fontSize: 16 },
  exchangeCard: { borderWidth: 1, borderRadius: 14, padding: 12, marginTop: 14 },
  summaryReason: {
    marginTop: 4,
    marginBottom: 10,
    fontSize: 14,
    lineHeight: 20,
    color: '#1f4c78',
  },
  metric: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 7,
    borderBottomColor: '#dce8f5',
    borderBottomWidth: 1,
  },
  metricLabel: {
    flex: 1,
    fontSize: 13,
    color: '#476582',
    fontWeight: '700',
  },
  metricValue: {
    flex: 1,
    fontSize: 13,
    color: '#16324f',
    textAlign: 'right',
  },
  bodyText: {
    fontSize: 13,
    lineHeight: 19,
    color: '#1f4c78',
  },
  linkText: {
    color: '#3d8bfd',
    fontWeight: '800',
  },
  textBlock: {
    marginTop: 8,
  },
  compactRow: {
    borderBottomColor: '#dce8f5',
    borderBottomWidth: 1,
    paddingVertical: 8,
  },
  recommendationHeader: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#cfe0f2',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
  },
  smallText: {
    marginTop: 3,
    fontSize: 12,
    lineHeight: 17,
    color: '#476582',
  },
  buttonGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 16,
  },
  button: {
    minHeight: 42,
    borderRadius: 8,
    paddingHorizontal: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primary: {
    backgroundColor: palette.primary,
  },
  warn: {
    backgroundColor: '#9a6700',
  },
  danger: {
    backgroundColor: '#cf222e',
  },
  neutral: {
    backgroundColor: '#57606a',
  },
  // An emoji paints its own colours and ignores buttonText, so an icon needs a LIGHT ground to
  // be legible -- on the dark neutral button only the microphone's blue tip showed.
  iconButton: {
    backgroundColor: '#e6eefb',
    borderWidth: 1,
    borderColor: '#b9cdea',
    paddingHorizontal: 16,
  },
  iconButtonText: {
    fontSize: 22,
    lineHeight: 26,
  },
  buttonText: {
    color: '#ffffff',
    fontSize: 13,
    fontWeight: '800',
  },
  disabledButton: {
    backgroundColor: '#98a2b3',
  },
  card: {
    backgroundColor: '#ffffff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#cfe0f2',
    padding: 12,
    marginBottom: 12,
  },
  // 2026-09-04, Founder-directed: "the conversations and the questions and answers should also
  // be scrollable because this list is gonna get long, and it's gonna be very tedious scrolling
  // up and down the screen."
  //
  // A fixed height, not maxHeight: on Android a nested ScrollView with no height of its own
  // grows to fit its content and never scrolls, which is the bug this is meant to fix. 420
  // shows roughly one full exchange, so the newest answer is readable without the card taking
  // over the screen.
  askConversationScroll: {
    height: 420,
    marginTop: 4,
  },
  chatExchange: {
    marginBottom: 10,
    paddingBottom: 6,
    borderBottomWidth: 1,
    borderBottomColor: '#eef1f6',
  },
  // 2026-09-06, Founder-directed: a WhatsApp-style day stamp in the chat, so it is obvious
  // which conversation happened when. Centred and quiet on purpose -- it is a signpost between
  // exchanges, not a message, and it must not compete with what was actually said.
  // 2026-09-07: the three-way standup. Mode row, start/end, and speaker-labelled bubbles --
  // in a conversation with two AI participants the LABEL is load-bearing, because two replies
  // in the same colour one after the other are unreadable without knowing who is speaking.
  standupModeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 12, marginBottom: 8 },
  standupMode: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 4,
    minHeight: 48,
    justifyContent: 'center',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#d6dbe4',
    alignItems: 'center',
    backgroundColor: '#f7f9fc',
  },
  standupModeActive: { backgroundColor: palette.primary, borderColor: palette.primary },
  standupModeText: { fontSize: 13, fontWeight: '600', color: '#41506a', textAlign: 'center' },
  standupModeTextActive: { color: '#ffffff' },
  standupStart: {
    marginTop: 10,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: palette.primary,
    alignItems: 'center',
  },
  standupStartText: { color: '#ffffff', fontWeight: '700', fontSize: 15 },
  // Picking up an exchange that was cut off mid-way. 2026-09-08: a lost turn used to end the
  // conversation because the app forgot whose turn was next. Outlined rather than filled -- it
  // is an offer, not the main thing to do, and the main thing is still to say something.
  standupResume: {
    marginTop: 8,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#1f6feb',
    backgroundColor: '#eef4ff',
    alignItems: 'center',
  },
  standupResumeText: { color: '#1f3f75', fontWeight: '600', fontSize: 14 },
  standupEnd: {
    marginTop: 10,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: '#b3261e',
    alignItems: 'center',
  },
  standupEndText: { color: '#ffffff', fontWeight: '700', fontSize: 15 },
  standupComposer: { gap: 12, backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#CFE0F2', borderRadius: 16, padding: 14, marginBottom: 16 },
  standupSend: {
    // flex:1 so it fills the row beside the microphone. Without it the button collapses to its
    // own text width and the padding squeezes "Send" over its own edges -- which is exactly
    // what it did the moment the mic was put next to it, caught on the device rather than in
    // a test, because no test looks at whether a word fits inside its box.
    flex: 1,
    height: 48,
    justifyContent: 'center',
    borderRadius: 8,
    backgroundColor: palette.primary,
    alignItems: 'center',
  },
  // The X. 2026-09-07, Founder-directed: a way out mid-sentence, before the words are sent.
  // Deliberately quiet grey rather than red -- red is the End Conversation button, and two red
  // buttons side by side is how someone ends the wrong thing.
  standupCancel: {
    width: 48,
    height: 48,
    borderRadius: 10,
    backgroundColor: '#e6e8ec',
    alignItems: 'center',
    justifyContent: 'center',
  },
  standupCancelText: { fontSize: 18, color: '#3d4757', fontWeight: '700' },
  standupSendBusy: { backgroundColor: '#66748c' },
  standupSendText: { color: '#ffffff', fontWeight: '700', fontSize: 15 },
  // The microphone, beside Send rather than hidden in it. 2026-09-07: the screen had none at
  // all, so speaking into it did nothing and looked identical to a fault.
  standupActions: { flexDirection: 'row', alignItems: 'stretch', gap: 8, minWidth: 122 },
  standupMic: {
    width: 56,
    height: 48,
    borderRadius: 10,
    backgroundColor: '#eef1f6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  // Red while recording. Colour plus the ticking counter in the status line: two independent
  // signals that it is listening, because one of them silently failing is how we got here.
  standupMicRecording: { backgroundColor: '#b3261e' },
  standupMicText: { fontSize: 20 },
  standupSpeaker: { fontSize: 11, fontWeight: '700', color: '#5a6b86', marginBottom: 3 },
  standupMine: {
    alignSelf: 'flex-end',
    maxWidth: '86%',
    backgroundColor: '#E7F2FF',
    borderRadius: 12,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginBottom: 6,
  },
  standupMineText: { color: '#16324F', fontSize: 15, lineHeight: 22 },
  standupTheirs: {
    alignSelf: 'flex-start',
    maxWidth: '92%',
    backgroundColor: '#eef1f6',
    borderRadius: 12,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginBottom: 6,
  },
  standupTheirsText: { color: '#1f2d3d', fontSize: 14, lineHeight: 20 },

  // 2026-09-07, Founder-directed: "each of us needs a different chat bubble colour so that
  // it's easy to understand who is asking the questions and who is answering."
  //
  // Three voices, three colours. The two AIs used to share one grey, so a standup read as an
  // undifferentiated wall -- exactly the problem the speaker labels were only half solving.
  //
  // Colour carries the meaning at a glance and the label confirms it. Both are kept, because
  // colour alone fails for a colour-blind reader and in bright sunlight; the pairing is the
  // point. The two AI colours are separated in hue AND lightness for the same reason -- green
  // against amber survives the most common form of colour blindness where green against red
  // would not.
  standupTrader: {
    alignSelf: 'flex-start',
    maxWidth: '92%',
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#CFE0F2',
    borderRadius: 12,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginBottom: 6,
  },
  standupTraderText: { color: '#16324F', fontSize: 15, lineHeight: 22 },
  standupTraderSpeaker: { fontSize: 13, fontWeight: '700', color: '#16324F', marginBottom: 3 },
  standupClaude: {
    alignSelf: 'flex-start',
    maxWidth: '92%',
    backgroundColor: '#F5F1FF',
    borderWidth: 1,
    borderColor: '#D8CBFF',
    borderRadius: 12,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginBottom: 6,
  },
  standupClaudeText: { color: '#16324F', fontSize: 15, lineHeight: 22 },
  standupClaudeSpeaker: { fontSize: 13, fontWeight: '700', color: '#65459B', marginBottom: 3 },
  chatDayStampRow: {
    alignItems: 'center',
    marginTop: 4,
    marginBottom: 10,
  },
  chatDayStamp: {
    fontSize: 11,
    fontWeight: '600',
    color: '#6b7280',
    backgroundColor: '#eef1f6',
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 10,
    overflow: 'hidden',
  },
  brokerStandingBlock: { marginTop: 14 },
  cardTitle: {
    fontSize: 16,
    fontWeight: '800',
    color: '#16324f',
    marginBottom: 8,
  },
  statusPill: {
    alignSelf: 'flex-start',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
    marginBottom: 8,
  },
  pillGood: {
    backgroundColor: '#dcfce7',
  },
  pillWarn: {
    backgroundColor: '#fef3c7',
  },
  pillDanger: {
    backgroundColor: '#fee2e2',
  },
  pillNeutral: {
    backgroundColor: '#e5e7eb',
  },
  statusPillText: {
    fontSize: 12,
    fontWeight: '800',
    // 2026-08-24 Founder-reported: this was white, which vanished against the pale pill
    // backgrounds once the app went light. Each tone now carries its own dark ink so the
    // pill still reads as green/amber/red at a glance AND the word is legible.
    color: '#16324f',
  },
  pillGoodText: {
    color: '#14532d',
  },
  pillWarnText: {
    color: '#78350f',
  },
  pillDangerText: {
    color: '#7f1d1d',
  },
  pillNeutralText: {
    color: '#334155',
  },
  input: {
    minHeight: 42,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#cfd6df',
    backgroundColor: '#ffffff',
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginVertical: 12,
    fontSize: 14,
  },
  multilineInput: {
    minHeight: 92,
    textAlignVertical: 'top',
  },
  chatTurn: {
    marginBottom: 8,
  },
  chatBubble: {
    width: '100%',
    borderRadius: 8,
    borderWidth: 1,
    padding: 10,
    marginBottom: 10,
  },
  chatUser: {
    backgroundColor: '#e7f0ff',
    borderColor: '#b9d3ff',
  },
  chatAssistant: {
    backgroundColor: '#ffffff',
    borderColor: '#cfe0f2',
  },
  // Trade History table (2026-08-21 Founder request - real aligned columns instead of a
  // sentence per trade; Commission %/Commission columns added same day). Column flex ratios
  // are tuned for a ~360-400dp phone width: Symbol gets the most room since Kraken pair names
  // ("XETHZGBP") run long, Side is the narrowest since it is always 3-4 letters, and the two
  // commission columns are narrow since their values ("0.80%", "£0.02") are always short -
  // Date/Symbol/Price/P&L were each trimmed slightly to make room for them without the row
  // growing unreadably dense.
  tradeTable: {
    marginTop: 4,
  },
  tradeTableHeaderRow: {
    flexDirection: 'row',
    borderBottomColor: '#adb5bd',
    borderBottomWidth: 1,
    paddingBottom: 6,
    marginBottom: 2,
  },
  tradeTableHeaderText: {
    fontSize: 11,
    fontWeight: '800',
    color: '#476582',
    textTransform: 'uppercase',
  },
  tradeTableRow: {
    flexDirection: 'column',
    alignItems: 'stretch',
    borderBottomColor: '#dce8f5',
    borderBottomWidth: 1,
    paddingVertical: 9,
  },
  tradeTableRowTouchable: {
    flex: 1,
    flexDirection: 'column',
  },
  tradeTableRowCells: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  tradeTableCellDate: {
    flex: 1.15,
  },
  tradeTableCellSymbol: {
    flex: 1.35,
  },
  tradeTableCellSide: {
    flex: 0.7,
  },
  tradeTableCellPrice: {
    flex: 1.2,
  },
  // 2026-08-23 Founder request: how much money was actually committed per trade. Given a
  // little more room than Price because it is the column being read for sizing.
  tradeTableCellAmount: {
    flex: 1.2,
  },
  tradeTableCellCommissionPct: {
    flex: 0.85,
  },
  tradeTableCellCommission: {
    flex: 0.95,
  },
  tradeTableCellPnl: {
    flex: 1.2,
  },
  tradeTableCellText: {
    fontSize: 12,
    color: '#16324f',
  },
  tradeTableCellTextRight: {
    fontSize: 12,
    color: '#16324f',
    textAlign: 'right',
  },
  tradeTablePnlPositive: {
    color: '#1a7f37',
    fontWeight: '800',
  },
  tradeTablePnlNegative: {
    color: '#cf222e',
    fontWeight: '800',
  },
  tradeTableExpandedDetail: {
    paddingTop: 4,
    paddingBottom: 4,
  },
  tradeTableFootnote: {
    fontSize: 12,
    color: '#6c757d',
    paddingTop: 6,
    fontStyle: 'italic',
  },
  // Run-a-cycle screen (2026-08-29). Each step is a bordered block rather than a plain row:
  // the summaries run to two lines and without separation they read as one paragraph.
  // The conversation now lives inside the Ask card rather than in a card of its own
  // (Founder, 2026-09-01). A rule above it separates the answers from the controls without
  // needing a second heading.
  askConversation: {
    borderTopWidth: 1,
    borderTopColor: '#e9ecef',
    marginTop: 14,
    paddingTop: 12,
  },
  cycleStep: {
    borderTopWidth: 1,
    borderTopColor: '#DFE7F0',
    paddingVertical: 14,
  },
  cycleStepHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  cycleStepLabel: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: '#16324F',
  },
  cycleStepSummary: {
    fontSize: 13,
    color: '#495057',
    paddingTop: 4,
    lineHeight: 18,
  },
  cycleStepPending: {
    fontSize: 13,
    color: '#6c757d',
    paddingTop: 4,
    fontStyle: 'italic',
  },
  cycleConclusion: {
    fontSize: 15,
    fontWeight: '600',
    color: '#212529',
    lineHeight: 21,
    paddingBottom: 6,
  },
  cycleBusyRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingTop: 10,
  },
  // Deliberately the accent blue rather than the muted grey the other header subtitles use:
  // this line is the answer to "is my cycle still running?", so it has to be findable at a
  // glance from any screen, not blend into the timestamps above it.
  cycleHeaderLine: {
    fontSize: 12,
    color: '#1971c2',
    fontWeight: '600',
    paddingTop: 2,
  },
  cycleError: {
    fontSize: 13,
    color: '#c92a2a',
    paddingTop: 10,
    lineHeight: 18,
  },
});
