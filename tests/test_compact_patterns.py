import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scoped_memory.core import MemoryError, MemoryStore, estimate_tokens


class CompactAndPatternTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.a, self.b = base / "a", base / "b"
        self.a.mkdir()
        self.b.mkdir()
        self.script = self.a / "repeat.py"
        self.script.write_text("print('synthetic')\n", encoding="utf-8")
        self.store = MemoryStore(base / "memory", owner_id="synthetic-owner")
        self.store.init_project(str(self.a))
        self.store.init_project(str(self.b))

    def tearDown(self):
        self.temp.cleanup()

    def test_compact_payload_has_single_copy_and_bounds(self):
        self.store.remember(scope="project", topic="route", content="verified-synthetic-fact",
                            project_root=str(self.a))
        old = self.store.recall(project_root=str(self.a), scopes=["project"])
        compact = self.store.recall_compact(project_root=str(self.a), scopes=["project"], token_budget=256)
        wire = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(compact["packet"]["v"], "SMC/1")
        self.assertEqual(compact["packet"]["r"][0][2], "verified-synthetic-fact")
        self.assertEqual(wire.count("verified-synthetic-fact"), 1)
        self.assertLess(estimate_tokens(wire), estimate_tokens(json.dumps(old, ensure_ascii=False)))
        self.assertLessEqual(compact["estimated_tokens"], 256)
        self.store.remember(scope="project", topic="long", content="x" * 10000,
                            project_root=str(self.a))
        bounded = self.store.recall_compact(project_root=str(self.a), scopes=["project"], token_budget=128)
        self.assertLessEqual(bounded["estimated_tokens"], 128)
        self.assertTrue(bounded["truncated"])

    def test_new_task_is_clean_and_cannot_cross_project_or_reopen(self):
        self.store.remember(scope="user", topic="boundary", content="stable-user-rule",
                            tags=["durable-rule"])
        self.store.remember(scope="project", topic="project-boundary", content="stable-project-rule",
                            project_root=str(self.a), tags=["durable-rule"])
        self.store.remember(scope="project", topic="temporary", content="old-task-fact",
                            project_root=str(self.a))
        self.store.remember(scope="project", topic="other-boundary", content="other-project-rule",
                            project_root=str(self.b), tags=["durable-rule"])
        first = self.store.open_task(str(self.a))["task_id"]
        second = self.store.open_task(str(self.a))["task_id"]
        self.store.task_checkpoint(project_root=str(self.a), task_id=first, summary="first-only")
        self.assertIn("first-only", json.dumps(self.store.task_context(project_root=str(self.a), task_id=first)))
        clean = json.dumps(self.store.task_context(project_root=str(self.a), task_id=second), ensure_ascii=False)
        self.assertIn("stable-user-rule", clean)
        self.assertIn("stable-project-rule", clean)
        self.assertNotIn("first-only", clean)
        self.assertNotIn("old-task-fact", clean)
        self.assertNotIn("other-project-rule", clean)
        with self.assertRaises(MemoryError):
            self.store.task_context(project_root=str(self.b), task_id=first)
        self.store.close_task(project_root=str(self.a), task_id=first)
        with self.assertRaises(MemoryError):
            self.store.task_context(project_root=str(self.a), task_id=first)
        with self.assertRaises(MemoryError):
            self.store.task_checkpoint(project_root=str(self.a), task_id=first, summary="reuse")

    def test_user_scope_rejects_accidental_project_attachment(self):
        with self.assertRaises(MemoryError):
            self.store.remember(scope="user", topic="x", content="y", project_root=str(self.a))

    def test_prediction_requires_distinct_evidence_and_unchanged_script(self):
        features = {"kind": "synthetic", "version": 1}
        candidate = self.store.pattern_propose(project_root=str(self.a), task_type="repeat",
                                               features=features, script_ref="repeat.py")
        pid = candidate["pattern_id"]
        self.assertEqual(self.store.pattern_predict(project_root=str(self.a), task_type="repeat",
                                                     features=features)["status"], "no_verified_match")
        self.store.pattern_observe(project_root=str(self.a), pattern_id=pid,
                                   outcome="pass", evidence_ref="evidence-1")
        with self.assertRaises(MemoryError):
            self.store.pattern_observe(project_root=str(self.a), pattern_id=pid,
                                       outcome="pass", evidence_ref="evidence-1")
        with self.assertRaises(MemoryError):
            self.store.pattern_verify(project_root=str(self.a), pattern_id=pid)
        self.store.pattern_observe(project_root=str(self.a), pattern_id=pid,
                                   outcome="pass", evidence_ref="evidence-2")
        self.store.pattern_verify(project_root=str(self.a), pattern_id=pid)
        match = self.store.pattern_predict(project_root=str(self.a), task_type="repeat", features=features)
        self.assertEqual(match["status"], "verified_match")
        self.assertTrue(match["advisory_only"])
        self.assertEqual(self.store.pattern_predict(project_root=str(self.b), task_type="repeat",
                                                     features=features)["status"], "no_verified_match")
        self.script.write_text("print('changed')\n", encoding="utf-8")
        self.assertEqual(self.store.pattern_predict(project_root=str(self.a), task_type="repeat",
                                                     features=features)["status"], "no_verified_match")

    def test_path_traversal_failure_and_expiry(self):
        with self.assertRaises(MemoryError):
            self.store.pattern_propose(project_root=str(self.a), task_type="repeat", features={},
                                       script_ref="../outside.py")
        with self.assertRaises(MemoryError):
            self.store.pattern_propose(project_root=str(self.a), task_type="repeat", features={},
                                       script_ref="repeat.py", expires_at="2000-01-01T00:00:00Z")
        candidate = self.store.pattern_propose(project_root=str(self.a), task_type="repeat",
                                               features={}, script_ref="repeat.py")
        self.store.pattern_observe(project_root=str(self.a), pattern_id=candidate["pattern_id"],
                                   outcome="fail", evidence_ref="failure-1")
        with self.assertRaises(MemoryError):
            self.store.pattern_verify(project_root=str(self.a), pattern_id=candidate["pattern_id"])

    def test_inheritance_expiry_and_prediction_expiry(self):
        source = self.store.resolve_project(str(self.b), required=True)
        grant = self.store.approve_inheritance(
            project_root=str(self.a), source_project_id=source.project_id,
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
        with self.store._write_connection() as conn:
            conn.execute("UPDATE inheritance_grants SET expires_at=? WHERE grant_id=?",
                         ("2000-01-01T00:00:00+00:00", grant["grant_id"]))
        with self.assertRaises(MemoryError):
            self.store.recall(project_root=str(self.a), scopes=["project"],
                              inherit_project_ids=[source.project_id])
        candidate = self.store.pattern_propose(
            project_root=str(self.a), task_type="short", features={}, script_ref="repeat.py",
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
        for n in (1, 2):
            self.store.pattern_observe(project_root=str(self.a), pattern_id=candidate["pattern_id"],
                                       outcome="pass", evidence_ref=f"ev-{n}")
        self.store.pattern_verify(project_root=str(self.a), pattern_id=candidate["pattern_id"])
        with self.store._write_connection() as conn:
            conn.execute("UPDATE patterns SET expires_at=? WHERE pattern_id=?",
                         ("2000-01-01T00:00:00+00:00", candidate["pattern_id"]))
        self.assertEqual(self.store.pattern_predict(project_root=str(self.a), task_type="short",
                                                     features={})["status"], "no_verified_match")


if __name__ == "__main__":
    unittest.main()
