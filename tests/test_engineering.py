import json
import tempfile
import unittest
from pathlib import Path

from scoped_memory.core import MemoryError, MemoryStore


class EngineeringIRTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "store"
        self.project = base / "project"
        self.project.mkdir()
        (self.project / "app.py").write_text(
            "from lib.helper import answer\n\nclass App:\n    pass\n\ndef main():\n    return answer()\n",
            encoding="utf-8",
        )
        (self.project / "lib").mkdir()
        (self.project / "lib" / "helper.py").write_text(
            "def answer():\n    return 42\n", encoding="utf-8",
        )
        (self.project / "tests").mkdir()
        (self.project / "tests" / "test_app.py").write_text(
            "from app import main\n\ndef test_main():\n    assert main() == 42\n", encoding="utf-8",
        )
        (self.project / "package.json").write_text(
            json.dumps({"scripts": {"test": "pytest"}, "dependencies": {"demo": "1.0"}}),
            encoding="utf-8",
        )
        (self.project / ".env").write_text("PASSWORD=do-not-index\n", encoding="utf-8")
        self.store = MemoryStore(self.home, owner_id="tester")
        self.store.init_project(str(self.project), "demo")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingest_builds_machine_ir_without_source_or_secrets(self):
        result = self.store.ingest_project(str(self.project))
        self.assertEqual(result["format"], "eir/1")
        self.assertEqual(result["stats"]["files"], 4)
        index = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
        self.assertEqual(index["v"], "eir/1")
        self.assertNotIn("do-not-index", json.dumps(index))
        paths = {item["p"] for item in index["files"]}
        self.assertNotIn(".env", paths)
        app = next(item for item in index["files"] if item["p"] == "app.py")
        self.assertEqual(app["sym"], ["App", "main"])
        self.assertIn(["app.py", "imp", "lib/helper.py"], index["edges"])
        test = next(item for item in index["files"] if item["p"] == "tests/test_app.py")
        self.assertIn("test", test["role"])
        marker = self.store.recall(project_root=str(self.project), scopes=["project"])
        self.assertIn("engineering/index/latest", [item["topic"] for item in marker["items"]])

    def test_engineering_context_is_queryable_and_bounded(self):
        self.store.ingest_project(str(self.project))
        result = self.store.engineering_context(str(self.project), query="helper", token_budget=256)
        packet = json.loads(result["context"])
        self.assertLessEqual(result["estimated_tokens"], 256)
        self.assertTrue(any(item["p"] == "lib/helper.py" for item in packet["files"]))
        self.assertNotIn("return 42", result["context"])

    def test_project_without_index_fails_closed(self):
        other = Path(self.tmp.name) / "other"
        self.store.init_project(str(other), "other")
        with self.assertRaisesRegex(MemoryError, "ingest"):
            self.store.engineering_context(str(other))


if __name__ == "__main__":
    unittest.main()
