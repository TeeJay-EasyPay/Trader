import tempfile
import unittest
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.agent import AITradingAgent
from ai_trader.alpaca import MockAlpacaPaperClient
from ai_trader.audit import AuditDatabase
from ai_trader.execution import ExecutionEngine
from ai_trader.models import GuardrailConfig
from ai_trader.proposals import load_proposals, save_proposals


MARKET_TIME = datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("America/New_York"))


class EndToEndTests(unittest.TestCase):
    def test_demo_proposal_executes_and_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            trading_log = Path(tmp) / "TRADING_LOG.md"
            audit = AuditDatabase(Path(tmp) / "audit.sqlite3", trading_log)
            broker = MockAlpacaPaperClient()
            guardrails = GuardrailConfig()
            agent = AITradingAgent(market_data=broker, audit=audit, guardrails=guardrails)
            proposals = agent.propose_trades(["AAPL"], broker.account_context(), demo=True, now=MARKET_TIME)
            self.assertEqual(len(proposals), 1)

            proposal_path = Path(tmp) / "proposals.json"
            save_proposals(proposal_path, proposals)
            loaded = load_proposals(proposal_path)

            engine = ExecutionEngine(broker=broker, audit=audit, guardrails=guardrails)
            results = engine.execute_proposals(loaded, now=MARKET_TIME)

            self.assertEqual(results[0]["status"], "executed")
            rows = audit.rows_for_date("2026")
            self.assertGreaterEqual(len(rows), 2)
            log_text = trading_log.read_text(encoding="utf-8")
            self.assertIn("execution_approved", log_text)
            self.assertIn("AAPL", log_text)


if __name__ == "__main__":
    unittest.main()
