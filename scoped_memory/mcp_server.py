from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable

from . import __version__
from .core import MemoryError, MemoryStore


TOOLS = [
    {
        "name": "memory_init_project",
        "description": "Create or reuse a stable project identity in .scoped-memory/project.json.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["project_root"], "properties": {
            "project_root": {"type": "string"}, "name": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "memory_remember",
        "description": "Append a user, project, or session memory. Reusing a topic supersedes it without rewriting history.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["scope", "topic", "content"], "properties": {
            "scope": {"type": "string", "enum": ["user", "project", "session"]},
            "topic": {"type": "string"}, "content": {"type": "string"}, "project_root": {"type": "string"},
            "session_id": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}},
            "importance": {"type": "integer", "minimum": 0, "maximum": 100},
            "metadata": {"type": "object"}}, "additionalProperties": False},
    },
    {
        "name": "memory_recall",
        "description": "Build a deterministic token-budgeted context packet. Other projects are excluded unless their IDs are explicitly inherited.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "properties": {
            "project_root": {"type": "string"}, "session_id": {"type": "string"}, "query": {"type": "string"},
            "scopes": {"type": "array", "items": {"type": "string", "enum": ["user", "project", "session"]}},
            "inherit_project_ids": {"type": "array", "items": {"type": "string"}},
            "token_budget": {"type": "integer", "minimum": 128, "maximum": 100000}}, "additionalProperties": False},
    },
    {
        "name": "memory_checkpoint",
        "description": "Store a structured task checkpoint for later continuation. Use concise model-readable facts, not conversation prose.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["summary", "project_root", "session_id"], "properties": {
            "summary": {"type": "string"}, "project_root": {"type": "string"}, "session_id": {"type": "string"},
            "decisions": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "next_steps": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False},
    },
    {
        "name": "memory_forget",
        "description": "Append a tombstone for a topic; prior history remains auditable.",
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["scope", "topic"], "properties": {
            "scope": {"type": "string", "enum": ["user", "project", "session"]}, "topic": {"type": "string"},
            "project_root": {"type": "string"}, "session_id": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "memory_status",
        "description": "Show store paths, counts, current project identity, and append-log integrity.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "properties": {"project_root": {"type": "string"}}, "additionalProperties": False},
    },
]


def result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)}]}


def dispatch(store: MemoryStore, name: str, args: dict[str, Any]) -> dict[str, Any]:
    calls: dict[str, Callable[..., Any]] = {
        "memory_init_project": store.init_project,
        "memory_remember": store.remember,
        "memory_recall": store.recall,
        "memory_checkpoint": store.checkpoint,
        "memory_forget": store.forget,
    }
    if name == "memory_status":
        status = store.status(**args)
        status["integrity"] = store.verify_audit()
        return result(status)
    if name not in calls:
        raise MemoryError(f"unknown tool: {name}")
    return result(calls[name](**args))


def reply(message_id: Any, *, value: Any = None, error: dict[str, Any] | None = None) -> None:
    payload = {"jsonrpc": "2.0", "id": message_id}
    payload["error" if error else "result"] = error or value
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    store = MemoryStore()
    for raw in sys.stdin:
        try:
            message = json.loads(raw)
            method, message_id = message.get("method"), message.get("id")
            if method == "initialize":
                reply(message_id, value={"protocolVersion": message.get("params", {}).get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}}, "serverInfo": {"name": "scoped-memory", "version": __version__}})
            elif method in {"notifications/initialized", "notifications/cancelled"}:
                continue
            elif method == "ping":
                reply(message_id, value={})
            elif method == "tools/list":
                reply(message_id, value={"tools": TOOLS})
            elif method == "tools/call":
                params = message.get("params", {})
                reply(message_id, value=dispatch(store, params.get("name", ""), params.get("arguments") or {}))
            elif message_id is not None:
                reply(message_id, error={"code": -32601, "message": f"method not found: {method}"})
        except (MemoryError, TypeError, ValueError) as exc:
            reply(message.get("id") if isinstance(message, dict) else None,
                  error={"code": -32602, "message": str(exc)})
        except Exception as exc:  # fail closed without corrupting stdout protocol
            traceback.print_exc(file=sys.stderr)
            reply(message.get("id") if isinstance(message, dict) else None,
                  error={"code": -32603, "message": f"internal error: {exc}"})


if __name__ == "__main__":
    main()
