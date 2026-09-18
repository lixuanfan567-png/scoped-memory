# Storage and context contract

## Scopes

- `user`: durable cross-project preferences; no project or session identifier.
- `project`: facts belonging to one stable project UUID.
- `session`: short-lived continuation state bound to one project UUID and session ID.

Git project identity lives in `scoped-memory-project.json` under the shared Git common directory; it is not committed. Non-Git project identity lives in `.scoped-memory/project.json`. Moving a project preserves identity when the old path no longer exists. Git worktrees sharing the same absolute Git common directory are registered as trusted roots of one project. If another live non-Git path has a copied marker, it is treated as a clone conflict and fails closed; remove the copied marker and initialize the clone to create an independent identity.

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
