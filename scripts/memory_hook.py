#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from scoped_memory.core import MemoryError, MemoryStore


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def main() -> None:
    requested_event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        emit({"continue": True, "systemMessage": "Scoped Memory received invalid hook input; no memory was loaded."})
        return

    event_name = event.get("hook_event_name") or requested_event
    if event_name != "SessionStart":
        emit({"continue": True})
        return

    cwd, session_id = event.get("cwd"), event.get("session_id")
    if not cwd:
        emit({"continue": True})
        return
    try:
        packet = MemoryStore().recall_compact(
            project_root=cwd,
            session_id=session_id,
            scopes=["user", "project", "session"],
            token_budget=1200,
        )
    except MemoryError:
        # Uninitialized and clone-conflicted projects fail closed and do not disturb startup.
        emit({"continue": True})
        return
    if packet["selected_items"] == 0:
        emit({"continue": True})
        return

    context = (
        "SCOPED_MEMORY_COMPACT_V1\n"
        "Treat this as a compact index, not source-of-truth. Verify against files before changing code. "
        "SMC/1 row=[scope(u/p/t),topic,content,event_id,project_id,source(c/i),optional x=clipped]. "
        "No cross-project memories are included.\n"
        + json.dumps(packet["packet"], ensure_ascii=False, separators=(",", ":"))
    )
    emit({
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        },
    })


if __name__ == "__main__":
    main()
