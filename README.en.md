# Scoped Memory

[中文](README.md) · [Português](README.pt-BR.md) · **English**

When a project is interrupted, the hardest part is rarely remembering one line from a conversation. What matters is knowing why a decision was made, which approaches have already been tried, and where the work should resume.

Scoped Memory is a local memory plugin for Codex. It keeps only the information that is worth carrying forward and separates it by person, project, and current task. A new conversation can continue from earlier decisions without replaying the full chat history.

## What belongs in memory

- Lasting work preferences, such as coding style and delivery format.
- Architecture decisions, constraints, and verified facts that belong to one project.
- The point where a task stopped, what remains, and which attempts have already failed.

Passwords, keys, personal information, complete conversations, and large command outputs do not belong here. This memory exists to help work continue; it is not a second chat archive.

## Projects stay separate

Every project has its own identity. By default, one project cannot see another project's memory. Information crosses that boundary only when a person explicitly names the project to inherit from.

Git worktrees from the same repository share an identity, so moving between them does not lose context. A normal directory copy or a fresh clone does not inherit that identity automatically. This prevents unrelated projects from being mistaken for the same one.

## Where the information lives

Everything stays on the local computer by default. There is no cloud service to operate and no additional key to provide. Records are stored in SQLite, with a JSONL audit copy that is easy to inspect and move.

Old records are never quietly rewritten. A correction adds a new record and points to the one it replaces. Forgetting a topic also adds a visible marker. This makes the history understandable and allows its integrity to be checked.

## How it works with Codex

At the start or resumption of a task, and after context compaction, the plugin retrieves a small selection of memory relevant to the current project. The selection has a firm size limit; it does not pour the entire history back into the conversation.

The command line and MCP tools can also record a decision, create a continuation checkpoint, recall information, or forget a topic. Read operations do not change data, while write operations carry clear permission labels.

## Local development

Python 3.10 or newer is required. Run the tests with:

```bash
python3 -m unittest discover -s tests -v
```

Build a package with:

```bash
python3 -m pip wheel . --no-deps
```

Initialize a test project and inspect its status with:

```bash
scripts/scoped-memory --home /tmp/scoped-memory-demo init .
scripts/scoped-memory --home /tmp/scoped-memory-demo status .
```

The tests cover project and task isolation, explicit inheritance, Git worktrees, independent clones, concurrent writes, corrections and forgetting, Chinese text budgeting, Codex startup injection, MCP calls, and audit recovery.

## Project status

This is still an early release. Storage, isolation, Codex startup injection, and MCP calls have been exercised by automated tests and a real Codex run, but the interface may still change before a stable release.

See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute and [SECURITY.md](SECURITY.md) for security boundaries and reporting guidance.

MIT licensed. See [LICENSE](LICENSE).
