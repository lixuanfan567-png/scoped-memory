# Contributing

Scoped Memory favors a small, inspectable core over implicit retrieval behavior.

## Development setup

Python 3.10 or newer is required. The runtime has no third-party dependencies.

```bash
python3 -m unittest discover -s tests -v
python3 -m build
```

Run both commands before submitting a change.

## Invariants

Changes must preserve these properties:

- No cross-project recall without explicit project IDs.
- Independent clones do not silently share a project identity.
- Git worktrees for one repository do share identity.
- Memory history is append-only; corrections supersede and deletions append tombstones.
- Recall is deterministic and token bounded.
- Hooks fail closed and never block Codex startup.
- Credentials, transcripts, and raw tool output are not memory payloads.

Add a regression test for every bug fix. Changes to the event schema require a migration test from the previous released schema.

## Pull requests

Keep pull requests focused. Explain the behavior change, its isolation and privacy impact, and the verification performed. Do not include a developer's real memory database, JSONL audit log, project marker, or credentials in fixtures.
