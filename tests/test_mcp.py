import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class MCPTests(unittest.TestCase):
    def test_stdio_protocol(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, SCOPED_MEMORY_HOME=str(Path(temp) / "store"), PYTHONPATH=str(root))
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_status", "arguments": {}}},
            ]
            proc = subprocess.run(
                [str(root / "scripts" / "launch_scoped_memory")],
                input="".join(json.dumps(m) + "\n" for m in messages), text=True, capture_output=True,
                env=env, timeout=10, check=True,
            )
        replies = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([reply["id"] for reply in replies], [1, 2, 3])
        names = {tool["name"] for tool in replies[1]["result"]["tools"]}
        self.assertIn("memory_recall", names)
        self.assertIn("memory_checkpoint", names)
        self.assertIn("memory_ingest_project", names)
        self.assertIn("memory_engineering_context", names)
        tools = {tool["name"]: tool for tool in replies[1]["result"]["tools"]}
        self.assertTrue(tools["memory_status"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["memory_status"]["annotations"]["openWorldHint"])
        self.assertTrue(tools["memory_forget"]["annotations"]["destructiveHint"])
        self.assertTrue(tools["memory_engineering_context"]["annotations"]["readOnlyHint"])
        self.assertFalse(replies[2]["result"]["isError"] if "isError" in replies[2]["result"] else False)


if __name__ == "__main__":
    unittest.main()
