# Security Policy

## Scope

Scoped Memory stores local agent memory and exposes local MCP tools. Relevant security issues include project-boundary bypasses, unintended cross-project recall, audit-log tampering, unsafe path handling, command execution, secret disclosure, and denial of service through malformed records.

## Reporting

Please use the repository's private [security advisory form](https://github.com/lixuanfan567-png/scoped-memory/security/advisories/new). Do not publish suspected vulnerabilities or sensitive reproduction data in a public issue.

## Data handling

Never attach a real `memory.sqlite3`, `events.jsonl`, `.scoped-memory/project.json`, or `.git/scoped-memory-project.json` to a public issue. Create a minimal temporary store with synthetic data instead.

The software is local-first, but local storage is not encryption. Anyone who can read the configured data directory can read stored memory. Do not store passwords, API keys, access tokens, personal data, full transcripts, or raw command output.
