"""2026-08-25, Founder-directed: a microphone on Ask AI Trader, "so I don't need to type
stuff, I can just press it and ask the app something verbally and submit it".

Every case here is a way the recording can fail. The rule they all share: a failed voice
question must leave the Founder able to type instead, never staring at an error or a stack
trace. Voice is a convenience on top of Ask, and it must never become a way to lose the
question.
"""

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.ai import MAX_TRANSCRIPTION_BYTES
from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.models import GuardrailConfig
from dataclasses import replace


def settings_for(tmp: str) -> Settings:
    root = Path(tmp)
    return Settings(
        alpaca_api_key=None, alpaca_secret_key=None,
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        alpaca_data_base_url="https://data.alpaca.markets",
        openai_api_key=None, openai_model="gpt-4.1-mini",
        db_path=root / "audit.sqlite3", output_dir=root,
        trading_log_path=root / "TRADING_LOG.md", guardrails=GuardrailConfig(),
    )


class VoiceQuestionTests(unittest.TestCase):
    def test_a_recording_becomes_the_question_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(replace(settings_for(tmp), openai_api_key="test-key"))
            audio = base64.b64encode(b"fake-audio-bytes").decode()

            with patch("ai_trader.api.OpenAITranscriber.transcribe", return_value="How is XRP doing?"):
                status, payload = service.post("/transcribe-question", {"audio_base64": audio})

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "transcribed")
            self.assertEqual(payload["text"], "How is XRP doing?")

    def test_a_transcription_failure_never_surfaces_a_stack_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(replace(settings_for(tmp), openai_api_key="test-key"))
            audio = base64.b64encode(b"fake-audio-bytes").decode()

            with patch("ai_trader.api.OpenAITranscriber.transcribe", side_effect=RuntimeError("boom")):
                status, payload = service.post("/transcribe-question", {"audio_base64": audio})

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "failed")
            self.assertNotIn("boom", payload["message"])
            self.assertIn("type the question", payload["message"])

    def test_silence_is_reported_as_silence_not_as_a_question(self):
        """An empty transcription must not be sent to Ask as an empty question."""
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(replace(settings_for(tmp), openai_api_key="test-key"))
            audio = base64.b64encode(b"fake-audio-bytes").decode()

            with patch("ai_trader.api.OpenAITranscriber.transcribe", return_value="   "):
                _, payload = service.post("/transcribe-question", {"audio_base64": audio})

            self.assertEqual(payload["status"], "empty")
            self.assertEqual(payload["text"], "")

    def test_a_corrupt_recording_is_refused_politely(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(replace(settings_for(tmp), openai_api_key="test-key"))

            _, payload = service.post("/transcribe-question", {"audio_base64": "not-valid-base64!!"})

            self.assertEqual(payload["status"], "invalid_audio")
            self.assertEqual(payload["text"], "")

    def test_an_oversized_recording_is_refused_before_it_is_uploaded(self):
        """Guarding the upload, not just the API's own limit: a long accidental recording
        should cost nothing and say so."""
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(replace(settings_for(tmp), openai_api_key="test-key"))
            audio = base64.b64encode(b"x" * (MAX_TRANSCRIPTION_BYTES + 1)).decode()

            with patch("ai_trader.api.OpenAITranscriber.transcribe", side_effect=AssertionError("must not upload")):
                _, payload = service.post("/transcribe-question", {"audio_base64": audio})

            self.assertEqual(payload["status"], "too_large")

    def test_without_an_openai_key_it_says_so_instead_of_failing_obscurely(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            audio = base64.b64encode(b"fake-audio-bytes").decode()

            _, payload = service.post("/transcribe-question", {"audio_base64": audio})

            self.assertEqual(payload["status"], "not_configured")
            self.assertIn("Type the question instead", payload["message"])

    def test_no_recording_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            _, payload = service.post("/transcribe-question", {})

            self.assertEqual(payload["status"], "no_audio")


if __name__ == "__main__":
    unittest.main()
