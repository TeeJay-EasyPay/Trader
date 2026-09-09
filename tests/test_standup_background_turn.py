"""A standup turn that is watched rather than waited on.

2026-09-08, Founder-reported, with a screenshot of two of these in one conversation:

    "after 2 messages or less you provide a message saying 'the rest of that exchange did not
     get through.....' what does that mean and does it mean the conversation has ended?"

    "by the way the app does not speak and the conversation tends to just stop after your
     message above. so it doesn't feel like a free flowing conversation."

Three separate faults, all proven from his own server logs that morning:

  1. THE APP GAVE UP. Claude searches the code and queries the database while it answers, and
     each lookup is another round trip. The three Claude turns in the logs ran 1m 31s, 1m 57s
     and 4m 06s; the app held one request open and gave up at two minutes. So the turn now runs
     in the background and the app polls it -- no wait can end a conversation.
  2. THE SCREEN NEVER SPOKE. Ask reads its answers out loud and reopens the microphone. Standup
     was given a microphone on 2026-09-07 and none of the half that answers back.
  3. IT STOPPED DEAD. Nothing reopened the microphone, and a lost turn took the "whose turn is
     next" pointer with it, so the exchange ended there.

Nothing here spends a penny: the registry is exercised with a plain function, the endpoint with
stubbed speakers, and the wording through node.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

SCREEN = REPO / "mobile" / "screens" / "Standup.js"
SPEAKER = REPO / "mobile" / "lib" / "useSpeaker.js"
WATCHER = REPO / "mobile" / "lib" / "standupTurn.js"

from ai_trader import standup_turns
from ai_trader.standup import CLAUDE, TRADER


def _node(script: str):
    result = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO), timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip())
    return json.loads(result.stdout)


def _wait_for(predicate, timeout=10.0):
    """Poll until true, the way the app does. Never a bare sleep: a fixed pause is either a
    slow test or a flaky one, and on a loaded machine it is both."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class RegistryTests(unittest.TestCase):
    """The background half. A turn is started, watched, and collected."""

    def setUp(self):
        standup_turns.reset_for_tests()

    def test_starting_a_turn_returns_immediately(self):
        """The whole point. If starting blocked until the answer was ready we would have moved
        the two-minute wall rather than removed it."""
        release = threading.Event()
        began = time.monotonic()
        turn_id = standup_turns.start_turn(lambda report: (release.wait(5), {"turns": []})[1])
        self.assertLess(time.monotonic() - began, 1.0, "starting a turn blocked on the work")
        self.assertTrue(turn_id)
        self.assertEqual(standup_turns.turn_state(turn_id)["status"], "running")
        release.set()

    def test_the_answer_comes_back_when_it_is_ready(self):
        turn_id = standup_turns.start_turn(lambda report: {"turns": [{"speaker": "claude"}]})
        self.assertTrue(_wait_for(lambda: standup_turns.turn_state(turn_id)["status"] == "done"))
        state = standup_turns.turn_state(turn_id)
        self.assertEqual(state["result"]["turns"], [{"speaker": "claude"}])

    def test_progress_is_readable_while_the_turn_is_still_running(self):
        """"A spinner says something is happening; it does not say WHAT, or for how long." The
        progress has to be visible BEFORE the answer, or it is not progress."""
        seen = threading.Event()
        release = threading.Event()

        def work(report):
            report({"speaker": "claude", "stage": "looking", "lookups": 5, "max_lookups": 12})
            seen.set()
            release.wait(5)
            return {"turns": []}

        turn_id = standup_turns.start_turn(work)
        self.assertTrue(seen.wait(5))
        state = standup_turns.turn_state(turn_id)
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["progress"]["lookups"], 5)
        self.assertEqual(state["progress"]["stage"], "looking")
        self.assertGreaterEqual(state["elapsed_seconds"], 0)
        release.set()

    def test_progress_updates_merge_rather_than_replace(self):
        """A later update that mentions only the stage must not wipe out who is speaking --
        the line would lose the name halfway through and read as a different turn."""
        done = threading.Event()

        def work(report):
            report({"speaker": "claude", "max_lookups": 12})
            report({"stage": "summarising"})
            done.set()
            return {"turns": []}

        turn_id = standup_turns.start_turn(work)
        self.assertTrue(done.wait(5))
        self.assertTrue(_wait_for(lambda: standup_turns.turn_state(turn_id)["status"] == "done"))
        progress = standup_turns.turn_state(turn_id)["progress"]
        self.assertEqual(progress["speaker"], "claude")
        self.assertEqual(progress["stage"], "summarising")
        self.assertEqual(progress["max_lookups"], 12)

    def test_a_turn_that_crashes_is_reported_rather_than_hanging(self):
        """A thread that dies silently would leave him watching a line that never moves."""
        def work(report):
            raise RuntimeError("the tool loop fell over")

        turn_id = standup_turns.start_turn(work)
        self.assertTrue(_wait_for(lambda: standup_turns.turn_state(turn_id)["status"] == "failed"))
        self.assertIn("still open", standup_turns.turn_state(turn_id)["result"]["message"])

    def test_a_broken_progress_update_cannot_kill_the_turn(self):
        """Progress is a courtesy; the answer is what he is paying for."""
        class Awkward(dict):
            def keys(self):  # noqa: D102 - deliberately hostile
                raise ValueError("no")

        def work(report):
            report(Awkward())
            return {"turns": ["survived"]}

        turn_id = standup_turns.start_turn(work)
        self.assertTrue(_wait_for(lambda: standup_turns.turn_state(turn_id)["status"] == "done"))
        self.assertEqual(standup_turns.turn_state(turn_id)["result"]["turns"], ["survived"])

    def test_an_unknown_id_says_so_instead_of_erroring(self):
        """After a restart the id means nothing. "Ask again" is the honest answer; a wait that
        never ends is not."""
        state = standup_turns.turn_state("nothing-like-this")
        self.assertEqual(state["status"], "unknown")
        self.assertIn("Ask again", state["message"])

    def test_a_finished_turn_is_eventually_forgotten(self):
        """A day of standups must not grow without bound in a process that never restarts."""
        turn_id = standup_turns.start_turn(lambda report: {"turns": []})
        self.assertTrue(_wait_for(lambda: standup_turns.turn_state(turn_id)["status"] == "done"))
        original = standup_turns.KEEP_FINISHED_SECONDS
        try:
            standup_turns.KEEP_FINISHED_SECONDS = -1
            self.assertEqual(standup_turns.turn_state(turn_id)["status"], "unknown")
        finally:
            standup_turns.KEEP_FINISHED_SECONDS = original


class EndpointTests(unittest.TestCase):
    """The route. Asking for a background turn must hand back an id, not an answer."""

    def setUp(self):
        standup_turns.reset_for_tests()

    def _service(self, tmp):
        from ai_trader.api import LocalApiService
        from ai_trader.config import Settings
        from ai_trader.models import AutoTradeConfig, GuardrailConfig

        root = Path(tmp)
        service = LocalApiService(Settings(
            alpaca_api_key=None, alpaca_secret_key=None,
            alpaca_paper_base_url="https://paper-api.alpaca.markets",
            alpaca_data_base_url="https://data.alpaca.markets",
            openai_api_key=None, openai_model="gpt-4.1-mini",
            db_path=root / "audit.sqlite3", output_dir=root,
            trading_log_path=root / "TRADING_LOG.md",
            guardrails=GuardrailConfig(), auto_trade=AutoTradeConfig(),
        ))
        self.reported = []

        def _fake(who):
            def speak(history, prompt, report=None):
                if report:
                    report({"speaker": who, "stage": "looking", "lookups": 3, "max_lookups": 12})
                    self.reported.append(who)
                return {"text": f"{who} says something", "status": "answered", "model": "stub"}
            return speak

        service._trader_turn = _fake(TRADER)
        service._claude_turn = _fake(CLAUDE)
        return service

    def test_a_background_request_answers_with_an_id_not_an_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = self._service(tmp).post("/standup", {
                "message": "Claude, why is that slow?", "exchange_budget": 0,
                "max_replies": 1, "background": True,
            })
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "started")
            self.assertTrue(payload["turn_id"])
            self.assertNotIn("turns", payload, "the answer is not ready yet and must not be faked")

    def test_the_answer_arrives_on_the_polling_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            _, started = service.post("/standup", {
                "message": "Claude, why is that slow?", "exchange_budget": 0,
                "max_replies": 1, "background": True,
            })
            turn_id = started["turn_id"]

            def finished():
                _, state = service.get("/standup/turn", {"turn_id": [turn_id]})
                return state["status"] == "done"

            self.assertTrue(_wait_for(finished), "the turn never finished")
            _, state = service.get("/standup/turn", {"turn_id": [turn_id]})
            self.assertEqual(state["result"]["turns"][0]["speaker"], CLAUDE)

    def test_the_turn_reports_who_is_working(self):
        """Without this the app is back to a spinner, which is what he stopped."""
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            _, started = service.post("/standup", {
                "message": "Claude, why is that slow?", "exchange_budget": 0,
                "max_replies": 1, "background": True,
            })
            turn_id = started["turn_id"]
            self.assertTrue(_wait_for(
                lambda: service.get("/standup/turn", {"turn_id": [turn_id]})[1]["status"] == "done"
            ))
            _, state = service.get("/standup/turn", {"turn_id": [turn_id]})
            self.assertEqual(state["progress"]["speaker"], CLAUDE)
            self.assertEqual(state["progress"]["max_lookups"], 12)

    def test_the_synchronous_path_is_untouched(self):
        """Tests and scripts want to wait. Only the app asked for the other behaviour, and
        breaking the waiting path to fix the app would be a poor trade."""
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = self._service(tmp).post("/standup", {
                "message": "Claude, why is that slow?", "exchange_budget": 0, "max_replies": 1,
            })
            self.assertEqual(status, 200)
            self.assertEqual(payload["turns"][0]["speaker"], CLAUDE)

    def test_a_stand_in_speaker_that_takes_no_reporter_still_works(self):
        """Every existing test substitutes a two-argument speaker. Passing a reporter it never
        asked for would break all of them, which is exactly what it did on the first attempt."""
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            service._claude_turn = lambda history, prompt: {
                "text": "answered anyway", "status": "answered",
            }
            _, payload = service.post("/standup", {
                "message": "Claude, why is that slow?", "exchange_budget": 0, "max_replies": 1,
            })
            self.assertEqual(payload["turns"][0]["text"], "answered anyway")


@unittest.skipUnless(shutil.which("node"), "node is required to exercise the mobile helpers")
class WaitingWordsTests(unittest.TestCase):
    """What he reads while it works. The wording IS the feature: a line that cannot be told
    apart from a hang is what made him stop a turn that was working."""

    def _line(self, progress, seconds):
        return _node(
            "const w = require('./mobile/lib/standupTurn.js');"
            f"console.log(JSON.stringify({{line: w.progressLine({json.dumps(progress)}, {seconds})}}));"
        )["line"]

    def test_it_names_who_is_working(self):
        self.assertIn("Claude", self._line({"speaker": "claude", "stage": "thinking"}, 12))
        self.assertIn("Trader", self._line({"speaker": "trader", "stage": "thinking"}, 12))

    def test_it_says_what_the_lookup_actually_is(self):
        """"reading the code" is a thing he can picture. "tool_use" is not."""
        line = self._line(
            {"speaker": "claude", "stage": "looking", "lookups": 5, "max_lookups": 12,
             "last_tool": "read_source_file"}, 80)
        self.assertIn("reading the code", line)
        self.assertNotIn("read_source_file", line, "that is our word, not his")

    def test_the_wait_is_shown_as_bounded(self):
        """"lookup 6 of 12" says the waiting ends. "Thinking..." says nothing at all."""
        line = self._line(
            {"speaker": "claude", "stage": "looking", "lookups": 5, "max_lookups": 12,
             "last_tool": "search_source"}, 80)
        self.assertIn("6 of 12", line)

    def test_the_count_never_goes_backwards_between_lookups(self):
        """Between two lookups the stage is "thinking" again. Dropping back to a bare
        "thinking" would read as the progress having been lost."""
        line = self._line(
            {"speaker": "claude", "stage": "thinking", "lookups": 6, "max_lookups": 12}, 90)
        self.assertIn("6", line)

    def test_the_clock_reads_like_a_wait_not_a_stopwatch(self):
        self.assertIn("1m 20s", self._line({"speaker": "claude", "stage": "thinking"}, 80))
        self.assertIn("45s", self._line({"speaker": "claude", "stage": "thinking"}, 45))

    def test_an_empty_report_still_says_something_true(self):
        """A turn reports nothing until its first update lands."""
        line = self._line({}, 3)
        self.assertTrue(line.strip())
        self.assertIn("3s", line)


@unittest.skipUnless(shutil.which("node"), "node is required to exercise the mobile helpers")
class GivingUpTests(unittest.TestCase):
    """When to stop waiting. Both mistakes are bad in opposite directions: giving up on a turn
    that is working is what he reported, and waiting forever on one that is never coming is
    what the old code would now do if this were wrong."""

    def _decide(self, state, elapsed_ms):
        return _node(
            "const w = require('./mobile/lib/standupTurn.js');"
            f"console.log(JSON.stringify(w.pollOutcome({json.dumps(state)}, {elapsed_ms})));"
        )

    def test_a_running_turn_is_waited_on_however_long_it_takes(self):
        """His longest real turn was 4m 06s. Four minutes must not be treated as a failure."""
        self.assertEqual(self._decide({"status": "running"}, 250000)["action"], "wait")

    def test_a_finished_turn_hands_back_the_answer(self):
        outcome = self._decide({"status": "done", "result": {"turns": [1]}}, 5000)
        self.assertEqual(outcome["action"], "finished")
        self.assertEqual(outcome["result"]["turns"], [1])

    def test_a_forgotten_turn_says_it_was_lost_rather_than_waiting(self):
        outcome = self._decide({"status": "unknown"}, 5000)
        self.assertEqual(outcome["action"], "failed")
        self.assertIn("lost", outcome["message"])

    def test_there_is_still_an_outer_limit(self):
        """Ten minutes is far past any real turn, so only a dead server reaches it."""
        self.assertEqual(self._decide({"status": "running"}, 601000)["action"], "failed")


class ScreenWiringTests(unittest.TestCase):
    """The screen. Asserted on the source because a React screen cannot be rendered here --
    stated plainly rather than dressed up: these prove the wiring exists, not that it works on
    a device, and the device check is a separate job."""

    def test_the_screen_polls_instead_of_holding_one_request_open(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("background: true", source)
        self.assertIn("/standup/turn?turn_id=", source)
        self.assertNotIn("TURN_TIMEOUT_MS", source,
                         "the two-minute wall is the thing being removed")

    def test_it_still_works_against_a_server_that_has_not_been_updated(self):
        """The app and the server are deployed separately, and the app updates over the air.
        A version skew must not take the conversation down."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("if (!started || !started.turn_id) return started || {};", source)

    def test_a_dropped_poll_is_retried_rather_than_ending_the_turn(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("MAX_POLL_FAILURES", source)

    def test_the_replies_are_read_out_loud(self):
        """"by the way the app does not speak." Ask spoke; this screen never did."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("useSpeaker", source)
        self.assertIn("speaker.speak(`${SPEAKER_LABEL[turn.speaker] || 'AI'}: ${turn.text}`)", source)

    def test_the_microphone_reopens_when_they_have_finished_talking(self):
        """"the conversation tends to just stop after your message above." Nothing handed the
        floor back, so every turn needed a tap."""
        source = SCREEN.read_text(encoding="utf-8")
        block = source[source.index("const speaker = useSpeaker"):]
        block = block[:block.index("});")]
        self.assertIn("onFinished", block)
        self.assertIn("voice.start()", block)

    def test_a_phone_that_cannot_play_audio_still_gets_the_floor_back(self):
        """Otherwise a spoken conversation stops dead on exactly the devices that can least
        afford another silent failure."""
        source = SCREEN.read_text(encoding="utf-8")
        # Queue-idle works both without native audio and when clips finish before
        # the model exchange. Behaviour is exercised in the Node hook/floor tests.
        self.assertIn("speaker.isIdle()", source)
        final = source[source.index("} finally {"):source.index("}, [mode, request")]
        self.assertIn("voice.start()", final)
        self.assertLess(final.index("busyRef.current = false"), final.index("voice.start()"))

    def test_typing_ends_the_hands_free_run(self):
        """He has moved to the keyboard. A microphone opening after the next reply would be a
        surprise rather than a convenience."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("if (!resume && !spoken) handsFreeRef.current = false;", source)

    def test_ending_stops_the_voice_as_well_as_the_microphone(self):
        source = SCREEN.read_text(encoding="utf-8")
        block = source[source.index("const end = useCallback"):]
        block = block[:block.index("}, [")]
        self.assertIn("voice.cancel()", block)
        self.assertIn("speaker.stop()", block)

    def test_a_lost_turn_can_be_picked_up_rather_than_ending_the_exchange(self):
        """The pointer to whose turn was next used to die with the request."""
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("setResumable(body)", source)
        self.assertIn("standupResume", source)
        self.assertIn("{ resume: resumable }", source)

    def test_the_screen_says_out_loud_that_it_speaks(self):
        """Shipping a half and not saying which half is the specific habit being broken."""
        source = SCREEN.read_text(encoding="utf-8")
        introduction = source[source.index('<Section title="Standup">'):][:600].lower()
        self.assertIn("replies are read aloud", introduction)
        self.assertIn("does not place trades", introduction)


class SpeakingHookTests(unittest.TestCase):
    def test_replies_are_queued_rather_than_joined(self):
        """A standup produces more than one reply. Joined into one block the second speaker
        would fall past the 700-character spoken cap and be silently swallowed."""
        source = SPEAKER.read_text(encoding="utf-8")
        self.assertIn("queueRef", source)
        self.assertIn("queueRef.current.push", source)

    def test_the_floor_comes_back_only_once_the_room_has_finished(self):
        source = SPEAKER.read_text(encoding="utf-8")
        block = source[source.index("if (said === undefined)"):]
        self.assertIn("finishedRef.current()", block[:400])

    def test_a_clip_that_fails_does_not_strand_the_queue(self):
        """A swallowed failure that stops the queue would leave the floor with nobody."""
        source = SPEAKER.read_text(encoding="utf-8")
        self.assertIn("const carryOn = ()", source)
        self.assertIn("carryOn();", source)

    def test_leaving_the_screen_stops_the_voice(self):
        """A reply still being read aloud on a screen he has left is the same class of failure
        as a microphone left running on a closed conversation."""
        source = SPEAKER.read_text(encoding="utf-8")
        self.assertIn("mountedRef.current = false", source)

    def test_a_binary_without_audio_is_handled_rather_than_crashing(self):
        """2026-08-25: an unguarded require took the Executive Briefing down entirely."""
        source = SPEAKER.read_text(encoding="utf-8")
        self.assertIn("requireOptionalNativeModule", source)
        self.assertIn("function canSpeak", source)


if __name__ == "__main__":
    unittest.main()
