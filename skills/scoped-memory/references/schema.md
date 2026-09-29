# Storage and context contract

## Scopes

- `user`: durable cross-project preferences; no project or session identifier.
- `project`: facts belonging to one stable project UUID.
- `session`: short-lived continuation state bound to one project UUID and session ID. A fresh task from `memory_open_task` has its own server-issued task ID; use task tools for task checkpoints.

Git project identity lives in `scoped-memory-project.json` under the shared Git common directory; it is not committed. Non-Git project identity lives in `.scoped-memory/project.json`. Moving a project preserves identity when the old path no longer exists. Git worktrees sharing the same absolute Git common directory are registered as trusted roots of one project. If another live non-Git path has a copied marker, it is treated as a clone conflict and fails closed; remove the copied marker and initialize the clone to create an independent identity. User scope rejects a project or session ID instead of silently attaching one.

Cross-project recall requires both an explicit source project ID on the call and an unexpired, unrevoked grant created with the **local CLI** `inherit-grant`; `inherit-revoke` takes effect on the next recall. These grants govern memory recall only. They never grant file, experiment, execution, or network access.

## Compact packet SMC/1

`memory_recall_compact` returns one `packet` object, never duplicate `context` and `items`. `packet.v` is `SMC/1`; `packet.r` is a list of rows. Each row is `[scope, topic, content, event_id, project_id, source]`. Scope codes: `u` user, `p` project, `t` session. Source codes: `c` current, `i` inherited. An optional seventh value `x` means content was clipped to fit the budget. `packet.more` signals omitted or clipped facts. The codebook is versioned here, not repeated in every response. The budget applies to the compact packet; MCP envelope metadata costs additional tokens. Token estimates are heuristics, not model tokenizer measurements.

`memory_open_task` issues a fresh ID. `memory_task_checkpoint` and `memory_task_context` require an open task in the same project; `memory_close_task` rejects later task access. Task context includes that task's notes plus current user/project memories explicitly tagged `durable-rule`; ordinary project facts and other tasks are excluded. The tag is a recall hint, not a security authority. Neither old session IDs nor any memory record represent authorization.

## Repeatable task patterns

The local CLI can `pattern-propose`, `pattern-observe`, and `pattern-verify` a project-relative script for an exact canonical task signature. Two **reported** successes with distinct evidence references, no failures, an unchanged script hash, and an unexpired candidate are required before promotion. `memory_pattern_predict` only returns a script reference and fingerprint as an advisory suggestion; it does not run or generate scripts, verify evidence contents, or grant permission. A script change, expiry, or failure invalidates the suggestion. Check the current task's authorization before any separate execution.

## Stable topic examples

- `architecture/database`
- `constraint/no-public-network`
- `decision/model-routing`
- `failure/qwen-context-overflow`
- `checkpoint/latest`

Writing the same topic creates a superseding event. Forgetting creates a tombstone. Both operations preserve prior events for audit.

## Checkpoint v1

```json
{
  "summary": "compact current state",
  "decisions": ["decision + reason"],
  "constraints": ["must/must-not invariant"],
  "next_steps": ["concrete unfinished action"],
  "evidence": ["file:line, command result, or durable identifier"]
}
```

Prefer symbols, IDs, paths, and short factual clauses. Natural-language polish belongs in final user-facing output, not memory.

## Engineering IR v1

`memory_ingest_project` writes one project-isolated index under the store's `engineering/` directory. The index is deterministic JSON and contains no source bodies.

- `p`: repository-relative path.
- `k`: language or file kind.
- `b`: byte size.
- `h`: truncated SHA-256 content fingerprint.
- `sym`: top-level symbols.
- `imp`: imported modules or paths.
- `role`: `test`, `manifest`, `doc`, or `config`.
- `edges`: compact `[source,"imp",target]` relationships.
- `manifests`: dependency and script names from supported manifests.

The latest index digest and statistics are recorded as the project topic `engineering/index/latest`. `memory_engineering_context` returns a query-selected, token-bounded EIR/1 packet. Treat source files as authority and the index as a disposable, rebuildable projection.
