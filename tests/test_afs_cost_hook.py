"""tools/afs-cost-hook (ADR-0021 phase 1): token usage from a Copilot session log into a cost record."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HOOK = pathlib.Path(__file__).resolve().parent.parent / "tools/afs-cost-hook"


def run(cwd, payload, env_extra=None, event="sessionEnd"):
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITHUB_COPILOT_GIT_TOKEN", "COPILOT_AGENT_PROMPT", "GITHUB_ACTIONS", "RUNNER_TEMP")}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(HOOK), "--event", event], cwd=cwd, input=json.dumps(payload),
                          capture_output=True, text=True, env=env)


def log(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


class CostHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, sid):
        return json.loads((self.dir / ".migration/costs" / f"{sid}.json").read_text())

    def test_shutdown_model_metrics_are_authoritative(self):
        t = log(self.dir / "t/events.jsonl", [
            {"type": "session.start", "data": {}},
            {"type": "assistant.message", "data": {"outputTokens": 5}},
            {"type": "session.shutdown", "data": {"totalPremiumRequests": 1, "totalApiDurationMs": 900, "modelMetrics": {
                "claude-sonnet-4.6": {"requests": {"count": 12}, "usage": {
                    "inputTokens": 1000, "outputTokens": 200, "cacheReadTokens": 700, "cacheWriteTokens": 50}}}}}])
        r = run(self.dir, {"sessionId": "s1", "transcriptPath": str(t)})
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record("s1")
        self.assertEqual(rec["usage_source"], "session.shutdown.modelMetrics")
        self.assertEqual(rec["models"]["claude-sonnet-4.6"], {"input": 1000, "output": 200, "cache_read": 700,
                                                             "cache_write": 50, "reasoning": 0, "requests": 12})
        self.assertEqual(rec["totalPremiumRequests"], 1)
        self.assertEqual(rec["diagnostics"]["event_types"]["assistant.message"], 1)
        self.assertEqual(rec["surface"], "local")

    def test_time_window_data_keys_and_runner_surface(self):
        t = log(self.dir / "t/events.jsonl", [
            {"type": "session.start", "timestamp": "2026-11-02T21:36:40Z", "data": {"selectedModel": "m", "cwd": "/x"}},
            {"type": "assistant.message", "timestamp": "2026-11-02T22:12:00Z", "data": {"outputTokens": 9}}])
        run(self.dir, {"sessionId": "w1", "transcriptPath": str(t)}, {"GITHUB_ACTIONS": "true"})
        rec = self.record("w1")
        self.assertEqual((rec["started_at"], rec["ended_at"]), ("2026-11-02T21:36:40Z", "2026-11-02T22:12:00Z"))
        self.assertEqual(rec["diagnostics"]["data_keys"]["session.start"], ["cwd", "selectedModel"])
        self.assertEqual(rec["surface"], "coding-agent")

    def test_per_call_usage_then_output_only_fallbacks(self):
        home = self.dir / "home"
        log(home / "session-state/s2/events.jsonl", [
            {"type": "assistant.usage", "data": {"model": "gpt-5", "inputTokens": 10, "outputTokens": 3}},
            {"type": "assistant.usage", "data": {"model": "gpt-5", "inputTokens": 20, "outputTokens": 4}}])
        run(self.dir, {"session_id": "s2"}, {"COPILOT_HOME": str(home)})          # VS Code payload shape
        rec = self.record("s2")
        self.assertEqual(rec["usage_source"], "assistant.usage")
        self.assertEqual(rec["models"]["gpt-5"]["input"], 30)
        self.assertEqual(rec["models"]["gpt-5"]["requests"], 2)
        log(home / "session-state/s3/events.jsonl", [
            {"type": "session.model_change", "data": {"newModel": "m1"}},
            {"type": "assistant.message", "data": {"outputTokens": 7}}])
        run(self.dir, {"sessionId": "s3"}, {"COPILOT_HOME": str(home)})
        rec = self.record("s3")
        self.assertIn("partial", rec["usage_source"])
        self.assertEqual(rec["models"]["m1"]["output"], 7)

    def test_never_fails_the_session(self):
        r = run(self.dir, {"sessionId": "s4"}, {"COPILOT_HOME": str(self.dir / "empty")})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.record("s4")["models"], {})
        bad = subprocess.run([sys.executable, str(HOOK), "--event", "agentStop"], cwd=self.dir, input="not json",
                             capture_output=True, text=True, env={**os.environ, "COPILOT_HOME": str(self.dir / "x")})
        self.assertEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
