---
name: scoped-memory
description: Maintain local user, project, and task memory with strict project isolation, explicit inheritance, and compact continuation checkpoints. Use when work should remember decisions, constraints, evidence, failed approaches, or next steps across Codex tasks.
---

# Scoped Memory

Use the `scoped_memory` MCP tools as the durable memory control plane.

## Boundaries

- Treat raw task history and source files as truth; memory is a compact index, not authority.
- Keep project memories isolated by default. Never pass `inherit_project_ids` unless the user explicitly requests reuse from named projects and a current local inheritance grant exists.
- User scope is only for durable preferences that genuinely apply across projects. Do not put project facts there.
- Store secrets, credentials, personal data, entire transcripts, and large tool outputs nowhere in memory.
- Append new facts or tombstones. Never edit the SQLite database or JSONL log directly.

## Workflow

1. Call `memory_init_project` once when the current project has no identity.
2. At task start, use the bounded SMC/1 context supplied by the `SessionStart` hook. Call `memory_open_task` for a fresh task identity and `memory_task_context` for task-only recall. Call `memory_recall_compact` for a focused query or a different budget.
3. For repository work, call `memory_ingest_project` after meaningful file changes, then use `memory_engineering_context` for compact EIR/1 facts. Consume the JSON directly; do not translate it into prose before reasoning.
4. During work, save only stable decisions, constraints, verified evidence, and expensive-to-rediscover failures. Use stable topic keys so newer facts supersede older ones.
5. Before context becomes crowded or when a task reaches a meaningful boundary, call `memory_checkpoint`. Write terse model-readable facts rather than conversational prose.
6. Before final delivery, checkpoint unresolved next steps if continuation is likely. Do not claim a checkpoint was saved unless the tool succeeds. Close completed tasks.
7. For repeated work, use `memory_pattern_predict` only as a hint to an existing reviewed script. It never authorizes execution. Pattern promotion is a separate local CLI action, and reported evidence must be independently checked.

For the storage contract and checkpoint shape, read [references/schema.md](references/schema.md).
