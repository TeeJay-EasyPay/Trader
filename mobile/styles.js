import { StyleSheet } from 'react-native';

export const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#0b1220',
  },
  header: {
    paddingHorizontal: 18,
    paddingTop: 10,
    paddingBottom: 8,
    backgroundColor: '#0b1220',
    borderBottomColor: '#1f2937',
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
    color: '#f8fafc',
  },
  subtitle: {
    marginTop: 2,
    fontSize: 13,
    color: '#94a3b8',
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
    color: '#1f6feb',
    marginTop: 6,
  },
  tabs: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    padding: 10,
    backgroundColor: '#0b1220',
  },
  tab: {
    flexGrow: 1,
    flexBasis: '30%',
    minHeight: 48,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#334155',
    backgroundColor: '#111827',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 6,
  },
  activeTab: {
    backgroundColor: '#1f6feb',
    borderColor: '#1f6feb',
  },
  tabText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#cbd5e1',
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
    borderColor: '#1f6feb',
    backgroundColor: '#13294b',
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 10,
    marginTop: 10,
  },
  primaryTabActive: {
    backgroundColor: '#1f6feb',
  },
  primaryTabText: {
    fontSize: 15,
    fontWeight: '800',
    color: '#e2e8f0',
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
    borderColor: '#d9e2ec',
    padding: 12,
  },
  sectionTitle: {
    fontSize: 17,
    fontWeight: '800',
    color: '#17202a',
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
    color: '#667085',
    marginLeft: 6,
  },
  collapsibleBody: {
    marginTop: 8,
  },
  summaryCard: {
    backgroundColor: '#ffffff',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#d9e2ec',
    padding: 14,
    marginBottom: 14,
  },
  summaryReason: {
    marginTop: 4,
    marginBottom: 10,
    fontSize: 14,
    lineHeight: 20,
    color: '#243142',
  },
  metric: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 7,
    borderBottomColor: '#e6e9ee',
    borderBottomWidth: 1,
  },
  metricLabel: {
    flex: 1,
    fontSize: 13,
    color: '#667085',
    fontWeight: '700',
  },
  metricValue: {
    flex: 1,
    fontSize: 13,
    color: '#17202a',
    textAlign: 'right',
  },
  bodyText: {
    fontSize: 13,
    lineHeight: 19,
    color: '#243142',
  },
  linkText: {
    color: '#1f6feb',
    fontWeight: '800',
  },
  textBlock: {
    marginTop: 8,
  },
  compactRow: {
    borderBottomColor: '#e6e9ee',
    borderBottomWidth: 1,
    paddingVertical: 8,
  },
  recommendationHeader: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#dde1e7',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
  },
  smallText: {
    marginTop: 3,
    fontSize: 12,
    lineHeight: 17,
    color: '#667085',
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
    backgroundColor: '#1f6feb',
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
    borderColor: '#dde1e7',
    padding: 12,
    marginBottom: 12,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '800',
    color: '#17202a',
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
    color: '#111827',
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
    borderColor: '#dde1e7',
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
    color: '#667085',
    textTransform: 'uppercase',
  },
  tradeTableRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomColor: '#e6e9ee',
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
    color: '#17202a',
  },
  tradeTableCellTextRight: {
    fontSize: 12,
    color: '#17202a',
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
});
