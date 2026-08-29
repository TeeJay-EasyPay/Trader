// PALETTE (2026-08-24, Founder-directed): "I like the combination of a lighter blue,
// yellow, red and white... it feels too serious right now."
//
// Light blue and white do ALL the mood work. Green, red and amber are deliberately NOT used
// as decoration anywhere in here -- in a trading app they already carry meaning (money up,
// money down, needs your attention). Spending them on styling would cost the one signal
// that has to be unmissable: that you are losing money.
//
// Aiming for calm and confident rather than cheerful. At 2am with a trade going against
// you, a happy-looking app reads as mocking.
//
// Previous dark palette preserved at styles.js.darkbackup for an easy revert.
import { StyleSheet } from 'react-native';

export const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#eef4fb',
  },
  header: {
    paddingHorizontal: 18,
    paddingTop: 10,
    paddingBottom: 8,
    backgroundColor: '#eef4fb',
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
    color: '#5a7897',
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
    backgroundColor: '#eef4fb',
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
    backgroundColor: '#3d8bfd',
    borderColor: '#3d8bfd',
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
    borderColor: '#3d8bfd',
    backgroundColor: '#dceafc',
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 10,
    marginTop: 10,
  },
  primaryTabActive: {
    backgroundColor: '#3d8bfd',
  },
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
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#cfe0f2',
    padding: 12,
  },
  sectionTitle: {
    fontSize: 17,
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
    color: '#5a7897',
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
    color: '#5a7897',
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
    color: '#5a7897',
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
    backgroundColor: '#3d8bfd',
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
    color: '#5a7897',
    textTransform: 'uppercase',
  },
  tradeTableRow: {
    flexDirection: 'row',
    alignItems: 'center',
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
  cycleStep: {
    borderLeftWidth: 3,
    borderLeftColor: '#dee2e6',
    paddingLeft: 10,
    paddingVertical: 8,
    marginBottom: 10,
  },
  cycleStepHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  cycleStepLabel: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: '#212529',
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
