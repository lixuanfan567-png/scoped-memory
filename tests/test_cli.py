import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CLITests(unittest.TestCase):
    def run_cli(self, root: Path, home: Path, *args: str, expected: int = 0):
        repo = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(repo))
        proc = subprocess.run(
            [sys.executable, "-m", "scoped_memory.cli", "--home", str(home), *args],
            cwd=root, env=env, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(proc.returncode, expected, proc.stderr)
        return json.loads(proc.stdout if expected == 0 else proc.stderr)

    def test_complete_cli_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project, home = base / "project", base / "store"
            project.mkdir()
            initialized = self.run_cli(project, home, "init", ".", "--name", "demo")
            self.assertEqual(initialized["name"], "demo")

            remembered = self.run_cli(
                project, home, "remember", "project", "decision/runtime", "Use stdio MCP",
                "--project-root", ".", "--tag", "architecture", "--importance", "80",
                "--metadata", '{"source":"test"}',
            )
            self.assertEqual(remembered["tags"], ["architecture"])

            checkpoint = self.run_cli(
                project, home, "checkpoint", "CLI lifecycle works", "--project-root", ".",
                "--session-id", "session-1", "--decision", "Keep append-only events",
                "--next-step", "Publish after review",
            )
            self.assertEqual(checkpoint["kind"], "checkpoint")

            (project / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            ingested = self.run_cli(project, home, "ingest", ".")
            self.assertEqual(ingested["format"], "eir/1")
            engineering = self.run_cli(
                project, home, "engineering-context", ".", "--query", "run", "--token-budget", "256",
            )
            self.assertEqual(engineering["format"], "eir/1")
            self.assertLessEqual(engineering["estimated_tokens"], 256)

            recalled = self.run_cli(
                project, home, "recall", ".", "--session-id", "session-1", "--scope", "project",
                "--scope", "session",
            )
            self.assertIn("decision/runtime", [item["topic"] for item in recalled["items"]])
            self.assertIn("checkpoint/latest", [item["topic"] for item in recalled["items"]])

            forgotten = self.run_cli(
                project, home, "forget", "project", "decision/runtime", "--project-root", ".",
            )
            self.assertEqual(forgotten["kind"], "forget")
            verified = self.run_cli(project, home, "verify")
            self.assertTrue(verified["ok"])

    def test_cli_errors_are_structured(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project, home = base / "project", base / "store"
            project.mkdir()
            error = self.run_cli(
                project, home, "remember", "session", "topic", "content", expected=2,
            )
            self.assertIn("project_root is required", error["error"])

    def test_task_and_pattern_cli_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project, home = base / "project", base / "store"
            project.mkdir()
            (project / "repeat.py").write_text("print('synthetic')\n", encoding="utf-8")
            self.run_cli(project, home, "init", ".")
            task_id = self.run_cli(project, home, "task-open", ".")["task_id"]
            self.run_cli(project, home, "task-checkpoint", ".", task_id, "synthetic-state")
            self.assertIn("synthetic-state", json.dumps(
                self.run_cli(project, home, "task-context", ".", task_id)))
            self.assertEqual(self.run_cli(project, home, "recall-compact", ".")["packet"]["v"], "SMC/1")
            pattern_id = self.run_cli(project, home, "pattern-propose", ".", "repeat",
                                      '{"kind":"synthetic"}', "repeat.py")["pattern_id"]
            for n in (1, 2):
                self.run_cli(project, home, "pattern-observe", ".", pattern_id, "pass", f"evidence-{n}")
            self.run_cli(project, home, "pattern-verify", ".", pattern_id)
            suggestion = self.run_cli(project, home, "pattern-predict", ".", "repeat",
                                      '{"kind":"synthetic"}')
            self.assertEqual(suggestion["status"], "verified_match")
            self.run_cli(project, home, "task-close", ".", task_id)
            error = self.run_cli(project, home, "task-context", ".", task_id, expected=2)
            self.assertIn("closed", error["error"])


if __name__ == "__main__":
    unittest.main()
