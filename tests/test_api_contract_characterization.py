"""Stage 0.3 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md, section 6.3):
response-shape characterisation tests for the 17 named mobile-consumed endpoints.

These tests exist to *pin current behaviour* before any future extraction of api.py's
routing/handlers into src/api and src/application -- they are not a judgement on whether
the current behaviour is correct. A future refactor that changes any assertion here has
changed an observable contract and must be treated as a deliberate decision, not an
accident.

Two layers are characterised, matching how ApiHandler.do_GET/do_POST actually work
(api.py:4426-4459): first that the path requires authentication (ApiHandler._authorized),
then that an already-authorized call into LocalApiService.get/post returns the current
status code and top-level response shape. A real HTTP round trip is not used here --
tests/test_developer_experience.py's test_api_token_authorization_accepts_bearer_or_api_key
and test_repeated_auth_failures_lock_out_the_source_ip already characterise the auth
mechanism itself in full (including per-IP lockout); this file only needs to confirm none
of the 17 paths is accidentally exempt the way /healthz deliberately is.

--- Mobile endpoint cross-check (2026-08-02) ---

Traced mobile/App.js's `request`/`optional`/`command` wrappers (the only three call sites
that reach the hosted API) by grepping every literal and template-literal path argument
passed to them, rather than relying on the static best-effort grep the discovery pack used.

Confirmed: mobile calls all 17 endpoints listed below. Two are notable:
- /start-trading is the PRIMARY call for the "Resume All Trading" button; /resume-trading
  is only used as a fallback if /start-trading responds with a "not_found" error
  (mobile/App.js line ~1313: `onCommand('/start-trading', {}, '/resume-trading')`).
- /founder-evidence is fetched via a query string
  (`/founder-evidence?period=${activityPeriod}&trade_limit=100`), which the discovery
  pack's simpler literal-string grep did not catch.

One additional endpoint outside the named 17 is also called by mobile and was not on the
plan's list: /benchmark-daily-brief?date=... (mobile/App.js, fetched via the same
`optional()` best-effort wrapper as /founder-brief, /intelligence/companies,
/intelligence/themes, /notifications -- i.e. treated as non-critical/best-effort by the
app itself, unlike the primary /founder-evidence call).

Confirmed NOT called by mobile (so not characterised here): /status, /brokers, /portfolio,
/operations-health, /activity/*, /phase5-status, /sprint6-status, /kraken-reconciliation
(bare GET), /developer-status, /scheduler-status, /job-runs, /shadow-trades,
/research-funnel, /decision-journal, /operational-events, /world-class-evidence,
/performance-attribution, /founder/trades, /benchmark-traders,
/register-push-token, /notifications/ack. Everything the founder-facing screens need
from these is served pre-nested inside the /founder-evidence payload instead. `/recommendations`
became mobile-consumed in the 2026-08-06 egress remediation, but only while that screen is open.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import ApiHandler, LocalApiService
from ai_trader.config import Settings
from ai_trader.models import GuardrailConfig


def settings_for(tmp: str) -> Settings:
    root = Path(tmp)
    return Settings(
        alpaca_api_key=None,
        alpaca_secret_key=None,
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        alpaca_data_base_url="https://data.alpaca.markets",
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        db_path=root / "audit.sqlite3",
        output_dir=root,
        trading_log_path=root / "TRADING_LOG.md",
        guardrails=GuardrailConfig(),
    )


class _Headers:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=""):
        return self.values.get(key, default)


NAMED_MOBILE_ENDPOINTS = [
    "/founder-evidence",
    "/recommendations",
    "/founder-brief",
    "/intelligence/companies",
    "/intelligence/themes",
    "/trading-report",
    "/notifications",
    "/run-analysis",
    "/run-crypto-analysis",
    "/start-trading",
    "/resume-trading",
    "/stop-trading",
    "/auto-execute-recommendations",
    "/approve-and-execute",
    "/broker-auto-trading",
    "/force-managed-exit",
    "/kraken-reconciliation/replay",
    "/generate-report",
    "/ask-ai-trader",
]


class ApiContractCharacterizationTests(unittest.TestCase):
    def test_none_of_the_17_named_endpoints_are_exempt_from_authorization(self):
        # /healthz is the one deliberate exemption (api.py:4506); every mobile-consumed
        # endpoint must require the bearer token like everything else.
        handler = object.__new__(ApiHandler)
        handler.api_token = "secret"
        handler.headers = _Headers({})
        handler.client_address = ("203.0.113.50", 4321)

        for path in NAMED_MOBILE_ENDPOINTS:
            with self.subTest(path=path):
                self.assertFalse(handler._authorized(path))

    def test_founder_evidence_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.get("/founder-evidence", {"period": ["24h"], "trade_limit": ["100"]})

            self.assertEqual(status, 200)
            for key in ("generated_at", "period", "status", "summary", "portfolio", "brokers", "why_no_trade"):
                self.assertIn(key, payload)
            self.assertIsInstance(payload["brokers"], list)
            self.assertIsInstance(payload["status"], dict)
            self.assertIn("state", payload["status"])

    def test_recommendations_route_bounds_and_forwards_requested_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            with unittest.mock.patch.object(service, "recommendations", return_value=[]) as recommendations:
                status, payload = service.get("/recommendations", {"limit": ["500"]})

            self.assertEqual(status, 200)
            self.assertEqual(payload, {"recommendations": []})
            recommendations.assert_called_once_with(limit=50)

    def test_founder_brief_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.get("/founder-brief", {})

            self.assertEqual(status, 200)
            self.assertIsInstance(payload, dict)

    def test_intelligence_companies_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.get("/intelligence/companies", {})

            self.assertEqual(status, 200)
            self.assertIn("companies", payload)
            self.assertIsInstance(payload["companies"], list)

    def test_intelligence_themes_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.get("/intelligence/themes", {})

            self.assertEqual(status, 200)
            self.assertIn("themes", payload)
            self.assertIsInstance(payload["themes"], list)

    def test_trading_report_top_level_shape_with_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.get(
                "/trading-report", {"date": ["2026-08-01"], "broker": ["all"], "type": ["daily"]}
            )

            self.assertEqual(status, 200)
            self.assertIn("report_markdown", payload)
            self.assertIsInstance(payload["report_markdown"], str)

    def test_notifications_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.get("/notifications", {"unread_only": ["false"]})

            self.assertEqual(status, 200)
            self.assertIn("notifications", payload)
            self.assertIsInstance(payload["notifications"], list)

    def test_run_analysis_top_level_shape_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/run-analysis", {})

            self.assertEqual(status, 200)
            self.assertIn("status", payload)
            self.assertEqual(payload["status"], "not_available")

    def test_run_crypto_analysis_top_level_shape_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/run-crypto-analysis", {})

            self.assertEqual(status, 200)
            self.assertIn("status", payload)
            self.assertEqual(payload["status"], "not_available")
            self.assertIn("message", payload)

    def test_start_trading_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/start-trading", {})

            self.assertEqual(status, 200)
            self.assertEqual(payload, {"status": "running", "command": "start-trading"})

    def test_resume_trading_top_level_shape(self):
        # Mobile only calls this as a fallback when /start-trading 404s -- both endpoints
        # currently exist and behave identically apart from the "command" field, so this
        # locks in that /resume-trading is not itself a dead/unused route.
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/resume-trading", {})

            self.assertEqual(status, 200)
            self.assertEqual(payload, {"status": "running", "command": "resume-trading"})

    def test_stop_trading_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/stop-trading", {})

            self.assertEqual(status, 200)
            self.assertEqual(payload, {"status": "stopped", "command": "stop-trading"})

    def test_auto_execute_recommendations_top_level_shape_with_no_recommendations(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/auto-execute-recommendations", {})

            self.assertEqual(status, 200)
            self.assertIn("status", payload)

    def test_approve_and_execute_top_level_shape_without_proposal_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/approve-and-execute", {})

            self.assertEqual(status, 200)
            self.assertIn("status", payload)
            self.assertIn("message", payload)
            self.assertIn(payload["status"], {"blocked", "rejected"})

    def test_broker_auto_trading_top_level_shape_without_broker(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/broker-auto-trading", {})

            self.assertEqual(status, 200)
            self.assertEqual(payload, {"status": "rejected", "message": "broker is required."})

    def test_force_managed_exit_top_level_shape_without_managed_exit_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/force-managed-exit", {})

            self.assertEqual(status, 200)
            self.assertEqual(payload, {"status": "rejected", "message": "managed_exit_id is required."})

    def test_kraken_reconciliation_replay_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/kraken-reconciliation/replay", {"limit": 10})

            self.assertEqual(status, 200)
            self.assertIsInstance(payload, dict)

    def test_generate_report_top_level_shape_with_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post(
                "/generate-report", {"date": "2026-08-01", "broker": "all", "type": "daily"}
            )

            self.assertEqual(status, 200)
            self.assertIn("status", payload)
            self.assertIn("report_markdown", payload)

    def test_ask_ai_trader_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/ask-ai-trader", {"question": "What is my current balance?"})

            self.assertEqual(status, 200)
            for key in ("status", "answer", "read_only"):
                self.assertIn(key, payload)
            self.assertIsInstance(payload["answer"], str)
            self.assertTrue(payload["read_only"])

    def test_unknown_path_error_envelope_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            get_status, get_payload = service.get("/this-path-does-not-exist", {})
            post_status, post_payload = service.post("/this-path-does-not-exist", {})

            self.assertEqual(get_status, 404)
            self.assertEqual(get_payload, {"error": "not_found", "path": "/this-path-does-not-exist"})
            self.assertEqual(post_status, 404)
            self.assertEqual(post_payload, {"error": "not_found", "path": "/this-path-does-not-exist"})


if __name__ == "__main__":
    unittest.main()
