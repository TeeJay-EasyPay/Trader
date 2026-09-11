"""Read-only by default. --repair replays bounded, exact retained Alpaca fills.

No broker/AI calls, no orders, no backup or deletion. Repair events retain previous
fill rows. Historical ambiguity remains visible rather than being guessed away.
"""
import argparse
import json
import os
from pathlib import Path
from ai_trader.config import load_dotenv
from ai_trader import experiments as e
from ai_trader.alpaca_reconciliation import _alpaca_fill_rows, collapse_fills, pair_round_trips, recorded_exit_evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repair', action='store_true')
    args = parser.parse_args()
    load_dotenv()
    if os.getenv('AUDIT_DATABASE_URL'):
        os.environ['DATABASE_URL'] = os.environ['AUDIT_DATABASE_URL']
        os.environ['AI_TRADER_DATABASE_BACKEND'] = 'postgres'
    db = Path('data/audit.sqlite3')
    with e.transaction(db) as conn:
        if e.uses_postgres():
            conn.execute('SET TRANSACTION READ ONLY')
        fills = _alpaca_fill_rows(conn)
        orders = collapse_fills(fills)
        trips, unmatched = pair_round_trips(orders)
        exits = recorded_exit_evidence(conn, [t.exit_order_id for t in trips if t.exit_order_id])
    report = dict(activity_fills=len(fills), orders=len(orders), reporting_outcomes=len(trips), unmatched=len(unmatched),
        explicit_fee_records=sum(f['broker_fee'] is not None and f['exchange_fee'] is not None for f in fills),
        explained_exit_orders=len(exits), repaired=False)
    if args.repair:
        from ai_trader.alpaca_canonical_learning import reconcile_completed
        from ai_trader.alpaca_reconciliation import reconcile_alpaca
        report['reporting_reconciliation'] = reconcile_alpaca(db)
        count = len({t.entry_proposal_id for t in trips if t.entry_proposal_id})
        # At most six batches; never unbounded broker history or workflow calls.
        report['batches'] = [reconcile_completed(db, fills, orders, trips, exits, force=True)
                             for _ in range(min(6, (count + 9) // 10))]
        report['repaired'] = True
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
