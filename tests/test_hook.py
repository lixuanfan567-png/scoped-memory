import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scoped_memory.core import MemoryStore


class HookTests(unittest.TestCase):
    def test_session_start_injects_only_current_project(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            store_home = temp_path / "store"
            project_a, project_b = temp_path / "a", temp_path / "b"
            store = MemoryStore(store_home, owner_id="tester")
            store.init_project(str(project_a), "A")
            store.init_project(str(project_b), "B")
            store.remember(scope="project", topic="a", content="alpha-only", project_root=str(project_a))
            store.remember(scope="project", topic="b", content="beta-only", project_root=str(project_b))
            env = dict(os.environ, SCOPED_MEMORY_HOME=str(store_home), SCOPED_MEMORY_OWNER="tester", PYTHONPATH=str(root))
            hook_input = {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": str(project_a), "source": "startup"}
            proc = subprocess.run(
                [sys.executable, str(root / "scripts" / "memory_hook.py"), "SessionStart"],
                input=json.dumps(hook_input), text=True, capture_output=True, env=env, check=True, timeout=10,
            )
        output = json.loads(proc.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("alpha-only", context)
        self.assertNotIn("beta-only", context)

    def test_uninitialized_project_is_silent(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, SCOPED_MEMORY_HOME=str(Path(temp) / "store"), PYTHONPATH=str(root))
            hook_input = {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": temp, "source": "startup"}
            proc = subprocess.run(
                [sys.executable, str(root / "scripts" / "memory_hook.py"), "SessionStart"],
                input=json.dumps(hook_input), text=True, capture_output=True, env=env, check=True, timeout=10,
            )
        self.assertEqual(json.loads(proc.stdout), {"continue": True})


if __name__ == "__main__":
    unittest.main()
