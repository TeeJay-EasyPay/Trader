"""Small read-only reconciliation evidence. Never changes a trading allowance."""
from contextlib import closing
from .database import connect, row_values


def kraken_capital_evidence(db):
    with closing(connect(db)) as c:
        cash, allocation = row_values(c.execute("""SELECT COALESCE(SUM(amount_gbp),0) AS cash,
            COALESCE(SUM(CASE WHEN entry_type='founder_allocation' THEN amount_gbp ELSE 0 END),0) AS allocation
            FROM KRAKEN_AI_CAPITAL_LEDGER""").fetchone())
        net, owned_open = row_values(c.execute("""SELECT
            COALESCE(SUM(CASE WHEN terminal=1 THEN net_pnl ELSE 0 END),0) AS net,
            COALESCE(SUM(CASE WHEN terminal=0 THEN remaining_quantity*average_entry_price ELSE 0 END),0) AS owned_open
            FROM LOGICAL_TRADES WHERE broker='kraken' AND logical_trade_id IN
            (SELECT logical_trade_id FROM KRAKEN_AI_ORDER_OWNERSHIP)""").fetchone())
        managed = row_values(c.execute("""SELECT COALESCE(SUM(quantity*entry_price),0)
            FROM MANAGED_TRADE_EXITS WHERE broker='kraken' AND status='open'""").fetchone())[0]
    return dict(available=True, currency='GBP', personal_holdings_included=False,
        founder_allocation=float(allocation), ledger_cash=float(cash), realised_net=float(net),
        owned_open_entry_value=float(owned_open), managed_control_entry_value=float(managed),
        status='requires_reconciliation' if abs(float(owned_open)-float(managed))>.02 else 'entry_values_close_not_broker_verified',
        risk_equity_basis='Existing sizing uses min(configured allocation, broker GBP cash); not whole-account portfolio equity.',
        limitation='Ledger cash, allocation, position value and risk equity are different fields. These are stored entry values, not current broker marks. Do not increase capital or infer buying power from a larger figure.')
