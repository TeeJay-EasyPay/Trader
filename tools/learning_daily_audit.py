"""Explicit read-only daily audit; returns aggregates only, never triggers research/trades."""
import json
import os
from pathlib import Path

from ai_trader.config import load_dotenv


def main():
    load_dotenv()
    # Use a dedicated read-only connection; never change application runtime settings.
    import psycopg
    from ai_trader import learning_monitor
    def readonly_connect(_):
        return psycopg.connect(os.environ['AUDIT_DATABASE_URL'], connect_timeout=15,
                               options='-c default_transaction_read_only=on -c statement_timeout=20000')
    print(json.dumps(learning_monitor.learning_health_snapshot(Path('.'), connection_factory=readonly_connect, placeholder='%s'), default=str))


if __name__ == '__main__':
    main()
