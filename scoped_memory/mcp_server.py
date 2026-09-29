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
        "name": "memory_recall_compact",
        "description": "Return a single SMC/1 packet; no duplicate items/context representation.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "properties": {
            "project_root": {"type": "string"}, "session_id": {"type": "string"}, "query": {"type": "string"},
            "scopes": {"type": "array", "items": {"type": "string", "enum": ["user", "project", "session"]}},
            "token_budget": {"type": "integer", "minimum": 128, "maximum": 100000}}, "additionalProperties": False},
    },
    {
        "name": "memory_open_task",
        "description": "Create a fresh task identity for an initialized project; no previous task is inherited.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["project_root"], "properties": {
            "project_root": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "memory_task_checkpoint",
        "description": "Write one checkpoint to an open task in this project.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["project_root", "task_id", "summary"], "properties": {
            "project_root": {"type": "string"}, "task_id": {"type": "string"}, "summary": {"type": "string"},
            "decisions": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "next_steps": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False},
    },
    {
        "name": "memory_task_context",
        "description": "Read one open task as SMC/1 with explicitly tagged durable user/project reminders; other task facts are excluded.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["project_root", "task_id"], "properties": {
            "project_root": {"type": "string"}, "task_id": {"type": "string"},
            "token_budget": {"type": "integer", "minimum": 128, "maximum": 100000}}, "additionalProperties": False},
    },
    {
        "name": "memory_close_task",
        "description": "Close a task so its task tools cannot read or update it.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["project_root", "task_id"], "properties": {
            "project_root": {"type": "string"}, "task_id": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "memory_pattern_predict",
        "description": "Suggest only an exact-match locally verified script reference; never execute it or grant access.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["project_root", "task_type", "features"], "properties": {
            "project_root": {"type": "string"}, "task_type": {"type": "string"},
            "features": {"type": "object"}}, "additionalProperties": False},
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
        "name": "memory_ingest_project",
        "description": "Scan a project deterministically into compact EIR/1 facts and dependency edges; no model summary is used.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["project_root"], "properties": {
            "project_root": {"type": "string"},
            "max_files": {"type": "integer", "minimum": 1, "maximum": 100000},
            "max_file_bytes": {"type": "integer", "minimum": 1024, "maximum": 10000000}},
            "additionalProperties": False},
    },
    {
        "name": "memory_engineering_context",
        "description": "Read a bounded EIR/1 engineering packet. Returns machine-readable facts without natural-language translation.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["project_root"], "properties": {
            "project_root": {"type": "string"}, "query": {"type": "string"},
            "token_budget": {"type": "integer", "minimum": 128, "maximum": 100000}},
            "additionalProperties": False},
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


def result(value: Any, *, compact: bool = False) -> dict[str, Any]:
    options = {"ensure_ascii": False, "sort_keys": True}
    if compact:
        options["separators"] = (",", ":")
    else:
        options["indent"] = 2
    return {"content": [{"type": "text", "text": json.dumps(value, **options)}]}


def dispatch(store: MemoryStore, name: str, args: dict[str, Any]) -> dict[str, Any]:
    calls: dict[str, Callable[..., Any]] = {
        "memory_init_project": store.init_project,
        "memory_remember": store.remember,
        "memory_recall": store.recall,
        "memory_recall_compact": store.recall_compact,
        "memory_open_task": store.open_task,
        "memory_task_checkpoint": store.task_checkpoint,
        "memory_task_context": store.task_context,
        "memory_close_task": store.close_task,
        "memory_pattern_predict": store.pattern_predict,
        "memory_checkpoint": store.checkpoint,
        "memory_ingest_project": store.ingest_project,
        "memory_engineering_context": store.engineering_context,
        "memory_forget": store.forget,
    }
    if name == "memory_status":
        status = store.status(**args)
        status["integrity"] = store.verify_audit()
        return result(status)
    if name not in calls:
        raise MemoryError(f"unknown tool: {name}")
    return result(calls[name](**args), compact=name in {
        "memory_recall_compact", "memory_task_context", "memory_pattern_predict"})


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
