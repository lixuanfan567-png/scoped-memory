import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import shutil
import subprocess

from scoped_memory.core import MemoryError, MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "store"
        self.project_a = root / "a"
        self.project_b = root / "b"
        self.store = MemoryStore(self.home, owner_id="tester")
        self.a = self.store.init_project(str(self.project_a), "A")
        self.b = self.store.init_project(str(self.project_b), "B")

    def tearDown(self):
        self.tmp.cleanup()

    def test_project_isolation_and_explicit_inheritance(self):
        self.store.remember(scope="project", topic="secret-a", content="alpha", project_root=str(self.project_a))
        self.store.remember(scope="project", topic="fact-b", content="beta", project_root=str(self.project_b))
        local = self.store.recall(project_root=str(self.project_a), scopes=["project"])
        self.assertIn("alpha", local["context"])
        self.assertNotIn("beta", local["context"])
        inherited = self.store.recall(project_root=str(self.project_a), scopes=["project"],
                                      inherit_project_ids=[self.b["project_id"]])
        self.assertIn("beta", inherited["context"])
        beta = next(item for item in inherited["items"] if item["content"] == "beta")
        self.assertEqual(beta["source"], "inherited")

    def test_session_isolation(self):
        self.store.remember(scope="session", topic="scratch", content="one", project_root=str(self.project_a), session_id="s1")
        other = self.store.recall(project_root=str(self.project_a), session_id="s2", scopes=["session"])
        self.assertEqual(other["items"], [])

    def test_supersede_and_forget_are_append_only(self):
        first = self.store.remember(scope="project", topic="decision", content="old", project_root=str(self.project_a))
        second = self.store.remember(scope="project", topic="decision", content="new", project_root=str(self.project_a))
        self.assertEqual(second["kind"], "supersede")
        self.assertEqual(second["replaces_event_id"], first["event_id"])
        recalled = self.store.recall(project_root=str(self.project_a), scopes=["project"])
        self.assertIn("new", recalled["context"])
        self.assertNotIn('"content":"old"', recalled["context"])
        self.store.forget(scope="project", topic="decision", project_root=str(self.project_a))
        self.assertEqual(self.store.recall(project_root=str(self.project_a), scopes=["project"])["items"], [])
        with closing(self.store.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 3)
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM events")

    def test_checkpoint_and_budget(self):
        self.store.checkpoint(summary="state", project_root=str(self.project_a), session_id="s1",
                              decisions=["keep official models"], next_steps=["test"])
        result = self.store.recall(project_root=str(self.project_a), session_id="s1", token_budget=128)
        self.assertLessEqual(result["estimated_tokens"], 128)
        self.assertEqual(result["items"][0]["topic"], "checkpoint/latest")

    def test_cjk_context_respects_budget(self):
        self.store.remember(scope="project", topic="中文", content="记忆" * 1000, project_root=str(self.project_a))
        result = self.store.recall(project_root=str(self.project_a), scopes=["project"], token_budget=128)
        self.assertLessEqual(result["estimated_tokens"], 128)
        self.assertTrue(result["truncated"])

    def test_uninitialized_project_fails_closed(self):
        with self.assertRaises(MemoryError):
            self.store.remember(scope="project", topic="x", content="y", project_root=str(Path(self.tmp.name) / "missing"))

    def test_audit_integrity_and_rebuild(self):
        self.store.remember(scope="user", topic="preference", content="concise")
        self.assertTrue(self.store.verify_audit()["ok"])
        self.store.audit_path.unlink()
        self.assertFalse(self.store.verify_audit()["ok"])
        rebuilt = self.store.rebuild_audit()
        self.assertEqual(rebuilt["events"], 1)
        event = json.loads(self.store.audit_path.read_text(encoding="utf-8"))
        self.assertEqual(event["topic"], "preference")
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_project_identity_survives_move(self):
        moved = Path(self.tmp.name) / "moved-a"
        shutil.move(self.project_a, moved)
        project = self.store.resolve_project(str(moved), required=True)
        self.assertEqual(project.project_id, self.a["project_id"])
        self.assertEqual(project.root, str(moved.resolve()))

    def test_copied_project_identity_fails_closed(self):
        clone = Path(self.tmp.name) / "clone-a"
        shutil.copytree(self.project_a, clone)
        with self.assertRaisesRegex(MemoryError, "clone"):
            self.store.resolve_project(str(clone), required=True)

    def test_git_worktree_shares_project_identity(self):
        base = Path(self.tmp.name) / "repo"
        worktree = Path(self.tmp.name) / "repo-worktree"
        base.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=base, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=base, check=True)
        subprocess.run(["git", "config", "user.name", "Scoped Memory Tests"], cwd=base, check=True)
        project = self.store.init_project(str(base), "worktree-project")
        self.assertTrue(Path(project["marker"]).is_relative_to(base / ".git"))
        self.assertFalse((base / ".scoped-memory" / "project.json").exists())
        (base / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=base, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=base, check=True, capture_output=True)
        subprocess.run(["git", "worktree", "add", "-b", "feature", str(worktree)], cwd=base, check=True, capture_output=True)

        resolved = self.store.resolve_project(str(worktree), required=True)
        self.assertEqual(resolved.project_id, project["project_id"])
        self.assertEqual(resolved.git_common_dir, project["git_common_dir"])
        self.store.remember(scope="project", topic="shared", content="visible-in-worktree", project_root=str(base))
        recalled = self.store.recall(project_root=str(worktree), scopes=["project"])
        self.assertIn("visible-in-worktree", recalled["context"])
        status = self.store.status(str(worktree))
        self.assertEqual(len(status["current_project_roots"]), 2)

    def test_concurrent_writers_keep_audit_in_database_order(self):
        package_root = Path(__file__).resolve().parents[1]
        code = (
            "from scoped_memory import MemoryStore; import os; "
            "MemoryStore(os.environ['STORE'], owner_id='tester').remember("
            "scope='user', topic=os.environ['TOPIC'], content=os.environ['TOPIC'])"
        )
        processes = []
        for index in range(8):
            env = dict(os.environ, STORE=str(self.home), TOPIC=f"concurrent-{index}", PYTHONPATH=str(package_root))
            processes.append(subprocess.Popen([sys.executable, "-c", code], env=env))
        statuses = [process.wait(timeout=15) for process in processes]
        self.assertEqual(statuses, [0] * len(processes))
        verification = self.store.verify_audit()
        self.assertTrue(verification["ok"], verification)


if __name__ == "__main__":
    unittest.main()
