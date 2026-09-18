from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import contextlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCOPES = {"user", "project", "session"}
LIVE_KINDS = {"remember", "checkpoint", "supersede"}


class MemoryError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def estimate_tokens(text: str) -> int:
    """Conservative dependency-free estimate: non-ASCII text is charged per codepoint."""
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii_count = len(text) - ascii_count
    return (ascii_count + 3) // 4 + non_ascii_count


def canonical_path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve()


def default_home() -> Path:
    if value := os.environ.get("SCOPED_MEMORY_HOME"):
        return canonical_path(value)
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "scoped-memory"


def find_git_root(path: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return canonical_path(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return path


def git_common_dir(path: Path) -> str | None:
    """Return the shared Git directory used to distinguish worktrees from clones."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return str(canonical_path(result.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        return None


def marker_path(root: Path) -> Path:
    common_dir = git_common_dir(root)
    if common_dir:
        return Path(common_dir) / "scoped-memory-project.json"
    return root / ".scoped-memory" / "project.json"


@dataclass(frozen=True)
class Project:
    project_id: str
    root: str
    name: str
    git_common_dir: str | None = None


class MemoryStore:
    """Append-only memory store with deterministic, scope-aware retrieval."""

    def __init__(self, home: str | os.PathLike[str] | None = None, owner_id: str | None = None):
        self.home = canonical_path(home or default_home())
        self.owner_id = owner_id or os.environ.get("SCOPED_MEMORY_OWNER") or os.environ.get("USER") or "local-user"
        self.home.mkdir(parents=True, exist_ok=True)
        self.db_path = self.home / "memory.sqlite3"
        self.audit_path = self.home / "events.jsonl"
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS projects (
          project_id TEXT PRIMARY KEY,
          canonical_root TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          created_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_roots (
          project_id TEXT NOT NULL,
          canonical_root TEXT NOT NULL UNIQUE,
          git_common_dir TEXT,
          created_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(project_id, canonical_root),
          FOREIGN KEY(project_id) REFERENCES projects(project_id)
        );
        CREATE INDEX IF NOT EXISTS idx_project_roots_project ON project_roots(project_id);
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('remember','checkpoint','supersede','forget')),
          scope TEXT NOT NULL CHECK(scope IN ('user','project','session')),
          owner_id TEXT NOT NULL,
          project_id TEXT,
          session_id TEXT,
          topic TEXT NOT NULL,
          content TEXT NOT NULL,
          tags_json TEXT NOT NULL,
          importance INTEGER NOT NULL CHECK(importance BETWEEN 0 AND 100),
          replaces_event_id TEXT,
          metadata_json TEXT NOT NULL,
          checksum TEXT NOT NULL,
          FOREIGN KEY(project_id) REFERENCES projects(project_id),
          FOREIGN KEY(replaces_event_id) REFERENCES events(event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_events_scope ON events(owner_id, scope, project_id, session_id, topic, seq);
        CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
          BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
          BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
        """
        with self._file_lock(self.home / "write.lock"):
            with self.connect() as conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(schema)
                # Migrate v0.1 stores without changing their event history.
                for row in conn.execute("SELECT project_id, canonical_root, created_at, last_seen_at FROM projects"):
                    root = Path(row["canonical_root"])
                    conn.execute(
                        """INSERT OR IGNORE INTO project_roots
                           (project_id, canonical_root, git_common_dir, created_at, last_seen_at)
                           VALUES(?,?,?,?,?)""",
                        (
                            row["project_id"], row["canonical_root"], git_common_dir(root) if root.exists() else None,
                            row["created_at"], row["last_seen_at"],
                        ),
                    )

    def init_project(self, project_root: str, name: str | None = None) -> dict[str, Any]:
        root = find_git_root(canonical_path(project_root))
        root.mkdir(parents=True, exist_ok=True)
        marker = marker_path(root)
        legacy_marker = root / ".scoped-memory" / "project.json"
        if marker != legacy_marker and not marker.exists() and legacy_marker.exists():
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(legacy_marker.read_text(encoding="utf-8"), encoding="utf-8")
            legacy_marker.unlink()
            try:
                legacy_marker.parent.rmdir()
            except OSError:
                pass
        if marker.exists():
            data = json.loads(marker.read_text(encoding="utf-8"))
            project_id = data["project_id"]
            project_name = name or data.get("name") or root.name
        else:
            project_id = str(uuid.uuid4())
            project_name = name or root.name
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps({"version": 1, "project_id": project_id, "name": project_name}, indent=2) + "\n",
                encoding="utf-8",
            )
        now = utc_now()
        common_dir = git_common_dir(root)
        with self._write_connection() as conn:
            path_owner = conn.execute(
                "SELECT project_id FROM project_roots WHERE canonical_root = ?", (str(root),)
            ).fetchone()
            if path_owner and path_owner["project_id"] != project_id:
                raise MemoryError("target path is already registered to another project identity")

            existing = conn.execute("SELECT canonical_root FROM projects WHERE project_id = ?", (project_id,)).fetchone()
            registered = conn.execute(
                "SELECT canonical_root, git_common_dir FROM project_roots WHERE project_id = ?", (project_id,)
            ).fetchall()
            already_registered = any(row["canonical_root"] == str(root) for row in registered)
            if existing and not already_registered:
                live_roots = [row for row in registered if Path(row["canonical_root"]).exists()]
                same_repository = bool(common_dir) and any(row["git_common_dir"] == common_dir for row in live_roots)
                if same_repository:
                    # A Git worktree is another trusted root of the same project, not cross-project inheritance.
                    conn.execute(
                        """INSERT INTO project_roots
                           (project_id, canonical_root, git_common_dir, created_at, last_seen_at)
                           VALUES(?,?,?,?,?)""",
                        (project_id, str(root), common_dir, now, now),
                    )
                elif live_roots:
                    raise MemoryError(
                        "project identity is already active in another repository; this looks like a clone, not a Git worktree. "
                        "Remove the copied .scoped-memory/project.json and initialize the clone as a new project."
                    )
                else:
                    # Every prior root disappeared, so this is a directory move.
                    conn.execute("DELETE FROM project_roots WHERE project_id = ?", (project_id,))
                    conn.execute(
                        """INSERT INTO project_roots
                           (project_id, canonical_root, git_common_dir, created_at, last_seen_at)
                           VALUES(?,?,?,?,?)""",
                        (project_id, str(root), common_dir, now, now),
                    )
                    conn.execute(
                        "UPDATE projects SET canonical_root = ?, name = ?, last_seen_at = ? WHERE project_id = ?",
                        (str(root), project_name, now, project_id),
                    )
            elif existing:
                conn.execute(
                    "UPDATE project_roots SET git_common_dir = ?, last_seen_at = ? WHERE project_id = ? AND canonical_root = ?",
                    (common_dir, now, project_id, str(root)),
                )
                conn.execute(
                    "UPDATE projects SET name = ?, last_seen_at = ? WHERE project_id = ?",
                    (project_name, now, project_id),
                )
            else:
                conn.execute(
                    "INSERT INTO projects(project_id, canonical_root, name, created_at, last_seen_at) VALUES(?,?,?,?,?)",
                    (project_id, str(root), project_name, now, now),
                )
                conn.execute(
                    """INSERT INTO project_roots
                       (project_id, canonical_root, git_common_dir, created_at, last_seen_at)
                       VALUES(?,?,?,?,?)""",
                    (project_id, str(root), common_dir, now, now),
                )
        return {
            "project_id": project_id, "root": str(root), "name": project_name,
            "marker": str(marker), "git_common_dir": common_dir,
        }

    def resolve_project(self, project_root: str | None, required: bool = False) -> Project | None:
        if not project_root:
            if required:
                raise MemoryError("project_root is required for project or session memory")
            return None
        start = canonical_path(project_root)
        root = find_git_root(start)
        candidates = [marker_path(root), root / ".scoped-memory" / "project.json"]
        if root != start:
            candidates.append(start / ".scoped-memory" / "project.json")
        marker = next((p for p in candidates if p.exists()), None)
        if marker is None:
            if required:
                raise MemoryError("project is not initialized; call memory_init_project first")
            return None
        data = json.loads(marker.read_text(encoding="utf-8"))
        project_id = str(data["project_id"])
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
        if row is None:
            initialized = self.init_project(str(root), data.get("name"))
            return Project(initialized["project_id"], initialized["root"], initialized["name"], initialized["git_common_dir"])
        initialized = self.init_project(str(root), data.get("name") or row["name"])
        return Project(project_id, str(root), initialized["name"], initialized["git_common_dir"])

    @staticmethod
    def _checksum(event: dict[str, Any]) -> str:
        raw = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _latest(self, *, scope: str, topic: str, project_id: str | None, session_id: str | None) -> sqlite3.Row | None:
        query = """SELECT * FROM events WHERE owner_id=? AND scope=? AND topic=?
                   AND project_id IS ? AND session_id IS ? ORDER BY seq DESC LIMIT 1"""
        with self.connect() as conn:
            return conn.execute(query, (self.owner_id, scope, topic, project_id, session_id)).fetchone()

    def remember(
        self,
        *,
        scope: str,
        topic: str,
        content: str,
        project_root: str | None = None,
        session_id: str | None = None,
        tags: Iterable[str] = (),
        importance: int = 50,
        metadata: dict[str, Any] | None = None,
        kind: str = "remember",
    ) -> dict[str, Any]:
        if scope not in SCOPES:
            raise MemoryError(f"invalid scope: {scope}")
        if kind not in LIVE_KINDS:
            raise MemoryError(f"invalid live event kind: {kind}")
        topic, content = topic.strip(), content.strip()
        if not topic or not content:
            raise MemoryError("topic and content must be non-empty")
        if not 0 <= int(importance) <= 100:
            raise MemoryError("importance must be between 0 and 100")
        project = self.resolve_project(project_root, required=scope in {"project", "session"})
        if scope == "session" and not session_id:
            raise MemoryError("session_id is required for session memory")
        project_id = project.project_id if project else None
        effective_session = session_id if scope == "session" else None
        previous = self._latest(scope=scope, topic=topic, project_id=project_id, session_id=effective_session)
        event = {
            "event_id": str(uuid.uuid4()),
            "created_at": utc_now(),
            "kind": "supersede" if previous and previous["kind"] != "forget" and kind == "remember" else kind,
            "scope": scope,
            "owner_id": self.owner_id,
            "project_id": project_id,
            "session_id": effective_session,
            "topic": topic,
            "content": content,
            "tags": sorted(set(str(t).strip() for t in tags if str(t).strip())),
            "importance": int(importance),
            "replaces_event_id": previous["event_id"] if previous else None,
            "metadata": metadata or {},
        }
        event["checksum"] = self._checksum(event)
        with self._write_connection() as conn:
            conn.execute(
                """INSERT INTO events(event_id,created_at,kind,scope,owner_id,project_id,session_id,topic,content,
                   tags_json,importance,replaces_event_id,metadata_json,checksum) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event["event_id"], event["created_at"], event["kind"], event["scope"], event["owner_id"],
                    event["project_id"], event["session_id"], event["topic"], event["content"],
                    json.dumps(event["tags"], ensure_ascii=False), event["importance"], event["replaces_event_id"],
                    json.dumps(event["metadata"], ensure_ascii=False, sort_keys=True), event["checksum"],
                ),
            )
        self.rebuild_audit()
        return event

    def forget(self, *, scope: str, topic: str, project_root: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        project = self.resolve_project(project_root, required=scope in {"project", "session"})
        project_id = project.project_id if project else None
        effective_session = session_id if scope == "session" else None
        previous = self._latest(scope=scope, topic=topic, project_id=project_id, session_id=effective_session)
        if previous is None or previous["kind"] == "forget":
            raise MemoryError("no active memory exists for that topic and scope")
        event = {
            "event_id": str(uuid.uuid4()), "created_at": utc_now(), "kind": "forget", "scope": scope,
            "owner_id": self.owner_id, "project_id": project_id, "session_id": effective_session,
            "topic": topic, "content": "", "tags": [], "importance": 0,
            "replaces_event_id": previous["event_id"], "metadata": {},
        }
        event["checksum"] = self._checksum(event)
        with self._write_connection() as conn:
            conn.execute(
                """INSERT INTO events(event_id,created_at,kind,scope,owner_id,project_id,session_id,topic,content,
                   tags_json,importance,replaces_event_id,metadata_json,checksum) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event["event_id"], event["created_at"], event["kind"], event["scope"], event["owner_id"],
                 event["project_id"], event["session_id"], event["topic"], "", "[]", 0,
                 event["replaces_event_id"], "{}", event["checksum"]),
            )
        self.rebuild_audit()
        return event

    def checkpoint(
        self,
        *,
        summary: str,
        project_root: str,
        session_id: str,
        decisions: list[str] | None = None,
        constraints: list[str] | None = None,
        next_steps: list[str] | None = None,
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "summary": summary.strip(),
            "decisions": decisions or [],
            "constraints": constraints or [],
            "next_steps": next_steps or [],
            "evidence": evidence or [],
        }
        return self.remember(
            scope="session", topic="checkpoint/latest", content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            project_root=project_root, session_id=session_id, tags=["checkpoint"], importance=90,
            metadata={"format": "checkpoint-v1"}, kind="checkpoint",
        )

    def recall(
        self,
        *,
        project_root: str | None = None,
        session_id: str | None = None,
        query: str = "",
        scopes: Iterable[str] = ("user", "project", "session"),
        inherit_project_ids: Iterable[str] = (),
        token_budget: int = 2000,
    ) -> dict[str, Any]:
        requested = list(dict.fromkeys(scopes))
        invalid = set(requested) - SCOPES
        if invalid:
            raise MemoryError(f"invalid scopes: {sorted(invalid)}")
        project = self.resolve_project(project_root, required=bool(set(requested) & {"project", "session"}))
        current_project_id = project.project_id if project else None
        inherited = list(dict.fromkeys(str(x) for x in inherit_project_ids if str(x)))
        if current_project_id in inherited:
            inherited.remove(current_project_id)
        if not 128 <= int(token_budget) <= 100_000:
            raise MemoryError("token_budget must be between 128 and 100000")

        clauses, params = [], []
        if "user" in requested:
            clauses.append("(scope='user' AND project_id IS NULL AND session_id IS NULL)")
        if "project" in requested and current_project_id:
            ids = [current_project_id, *inherited]
            placeholders = ",".join("?" for _ in ids)
            clauses.append(f"(scope='project' AND project_id IN ({placeholders}) AND session_id IS NULL)")
            params.extend(ids)
        if "session" in requested and current_project_id and session_id:
            clauses.append("(scope='session' AND project_id=? AND session_id=?)")
            params.extend([current_project_id, session_id])
        if not clauses:
            return {"context": "", "items": [], "estimated_tokens": 0, "truncated": False}

        sql = f"""SELECT * FROM (
          SELECT e.*, ROW_NUMBER() OVER (
            PARTITION BY scope, owner_id, COALESCE(project_id,''), COALESCE(session_id,''), topic ORDER BY seq DESC
          ) AS rank_in_topic
          FROM events e WHERE owner_id=? AND ({' OR '.join(clauses)})
        ) WHERE rank_in_topic=1 AND kind!='forget'"""
        with self.connect() as conn:
            rows = conn.execute(sql, [self.owner_id, *params]).fetchall()

        terms = [part.casefold() for part in query.split() if part.strip()]
        items = []
        for row in rows:
            haystack = f"{row['topic']} {row['content']} {row['tags_json']}".casefold()
            if terms and not all(term in haystack for term in terms):
                continue
            source = "current"
            if row["scope"] == "project" and row["project_id"] != current_project_id:
                source = "inherited"
            items.append({
                "event_id": row["event_id"], "created_at": row["created_at"], "scope": row["scope"],
                "project_id": row["project_id"], "session_id": row["session_id"], "topic": row["topic"],
                "content": row["content"], "tags": json.loads(row["tags_json"]),
                "importance": row["importance"], "source": source,
            })
        items.sort(key=lambda item: (-item["importance"], item["scope"] != "session", item["topic"], item["created_at"]), reverse=False)

        selected, used_tokens = [], 0
        for item in items:
            rendered = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            rendered_tokens = estimate_tokens(rendered + ("\n" if selected else ""))
            if selected and used_tokens + rendered_tokens > int(token_budget):
                continue
            if rendered_tokens > int(token_budget) and not selected:
                clipped = dict(item)
                clipped["truncated"] = True
                low, high, best = 0, len(item["content"]), None
                while low <= high:
                    midpoint = (low + high) // 2
                    clipped["content"] = item["content"][:midpoint]
                    candidate = json.dumps(clipped, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    if estimate_tokens(candidate) <= int(token_budget):
                        best = dict(clipped)
                        low = midpoint + 1
                    else:
                        high = midpoint - 1
                if best is not None:
                    selected.append(best)
                break
            selected.append(item)
            used_tokens += rendered_tokens
        context = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in selected)
        return {
            "context": context,
            "items": selected,
            "estimated_tokens": estimate_tokens(context),
            "truncated": len(selected) < len(items) or any(item.get("truncated", False) for item in selected),
            "available_items": len(items),
            "current_project_id": current_project_id,
            "inherited_project_ids": inherited,
        }

    def ingest_project(
        self,
        project_root: str,
        *,
        max_files: int = 2000,
        max_file_bytes: int = 256_000,
    ) -> dict[str, Any]:
        """Build a deterministic engineering IR without asking a model to summarize source files."""
        if not 1 <= int(max_files) <= 100_000:
            raise MemoryError("max_files must be between 1 and 100000")
        if not 1_024 <= int(max_file_bytes) <= 10_000_000:
            raise MemoryError("max_file_bytes must be between 1024 and 10000000")
        project = self.resolve_project(project_root, required=True)
        from .engineering import EIR_VERSION, build_engineering_index

        index = build_engineering_index(
            Path(project.root), max_files=int(max_files), max_file_bytes=int(max_file_bytes),
        )
        index_dir = self.home / "engineering"
        index_dir.mkdir(parents=True, exist_ok=True)
        index_path = index_dir / f"{project.project_id}.json"
        temp = index_dir / f"{project.project_id}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        with self._file_lock(self.home / "engineering.lock"):
            try:
                with temp.open("w", encoding="utf-8", newline="\n") as output:
                    json.dump(index, output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
                temp.replace(index_path)
            finally:
                if temp.exists():
                    temp.unlink()

        marker = {
            "v": EIR_VERSION,
            "digest": index["digest"],
            "rev": index.get("rev"),
            "dirty": index.get("dirty", 0),
            "stats": index["stats"],
        }
        event = self.remember(
            scope="project",
            topic="engineering/index/latest",
            content=json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            project_root=project.root,
            tags=["engineering-ir", "index"],
            importance=85,
            metadata={"format": EIR_VERSION, "index_file": index_path.name},
        )
        return {
            "format": EIR_VERSION,
            "project_id": project.project_id,
            "index": str(index_path),
            "digest": index["digest"],
            "revision": index.get("rev"),
            "dirty": index.get("dirty", 0),
            "stats": index["stats"],
            "event_id": event["event_id"],
        }

    def engineering_context(
        self,
        project_root: str,
        *,
        query: str = "",
        token_budget: int = 2000,
    ) -> dict[str, Any]:
        """Return a bounded machine-readable engineering packet from the latest project index."""
        if not 128 <= int(token_budget) <= 100_000:
            raise MemoryError("token_budget must be between 128 and 100000")
        project = self.resolve_project(project_root, required=True)
        index_path = self.home / "engineering" / f"{project.project_id}.json"
        if not index_path.exists():
            raise MemoryError("engineering index is missing; call memory_ingest_project first")
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MemoryError(f"engineering index is unreadable: {exc}") from exc
        from .engineering import bounded_engineering_context

        result = bounded_engineering_context(index, query.strip(), int(token_budget))
        result.update({"project_id": project.project_id, "index": str(index_path)})
        return result

    def status(self, project_root: str | None = None) -> dict[str, Any]:
        project = self.resolve_project(project_root, required=False)
        with self.connect() as conn:
            event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            project_count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            active_count = conn.execute(
                """SELECT COUNT(*) FROM (SELECT kind, ROW_NUMBER() OVER (
                PARTITION BY scope,owner_id,COALESCE(project_id,''),COALESCE(session_id,''),topic ORDER BY seq DESC) r
                FROM events WHERE owner_id=?) WHERE r=1 AND kind!='forget'""", (self.owner_id,)
            ).fetchone()[0]
            roots = []
            if project:
                roots = [dict(row) for row in conn.execute(
                    """SELECT canonical_root, git_common_dir, created_at, last_seen_at
                       FROM project_roots WHERE project_id = ? ORDER BY canonical_root""",
                    (project.project_id,),
                )]
        return {
            "home": str(self.home), "database": str(self.db_path), "audit_log": str(self.audit_path),
            "owner_id": self.owner_id, "projects": project_count, "events": event_count,
            "active_memories": active_count, "current_project": project.__dict__ if project else None,
            "current_project_roots": roots,
        }

    def verify_audit(self) -> dict[str, Any]:
        checked, invalid = 0, []
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
        expected_audit = []
        for row in rows:
            event = {
                "event_id": row["event_id"], "created_at": row["created_at"], "kind": row["kind"],
                "scope": row["scope"], "owner_id": row["owner_id"], "project_id": row["project_id"],
                "session_id": row["session_id"], "topic": row["topic"], "content": row["content"],
                "tags": json.loads(row["tags_json"]), "importance": row["importance"],
                "replaces_event_id": row["replaces_event_id"], "metadata": json.loads(row["metadata_json"]),
            }
            checked += 1
            if self._checksum(event) != row["checksum"]:
                invalid.append(row["event_id"])
            expected_audit.append((row["event_id"], row["checksum"]))
        audit_error = None
        actual_audit = []
        try:
            if self.audit_path.exists():
                with self.audit_path.open("r", encoding="utf-8") as source:
                    for line_number, line in enumerate(source, 1):
                        if not line.strip():
                            continue
                        entry = json.loads(line)
                        actual_audit.append((entry.get("event_id"), entry.get("checksum")))
            elif expected_audit:
                audit_error = "audit log is missing"
        except (OSError, json.JSONDecodeError) as exc:
            audit_error = f"audit log is unreadable: {exc}"
        if audit_error is None and actual_audit != expected_audit:
            audit_error = "audit log does not match the database event sequence"
        return {
            "ok": not invalid and audit_error is None,
            "checked": checked,
            "invalid_event_ids": invalid,
            "audit_log_matches": audit_error is None,
            "audit_error": audit_error,
        }

    def rebuild_audit(self) -> dict[str, Any]:
        count = 0
        with self._audit_lock():
            temp = self.home / f"events.{os.getpid()}.{uuid.uuid4().hex}.tmp"
            try:
                with self.connect() as conn, temp.open("w", encoding="utf-8", newline="\n") as output:
                    for row in conn.execute("SELECT * FROM events ORDER BY seq"):
                        event = self._row_event(row)
                        output.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                        count += 1
                    output.flush()
                    os.fsync(output.fileno())
                temp.replace(self.audit_path)
            finally:
                if temp.exists():
                    temp.unlink()
        return {"events": count, "audit_log": str(self.audit_path)}

    @contextlib.contextmanager
    def _audit_lock(self):
        with self._file_lock(self.home / "events.lock"):
            yield

    @contextlib.contextmanager
    def _write_connection(self):
        with self._file_lock(self.home / "write.lock"):
            with self.connect() as conn:
                yield conn

    @contextlib.contextmanager
    def _file_lock(self, lock_path: Path):
        with lock_path.open("a+b") as lock:
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _row_event(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"], "created_at": row["created_at"], "kind": row["kind"],
            "scope": row["scope"], "owner_id": row["owner_id"], "project_id": row["project_id"],
            "session_id": row["session_id"], "topic": row["topic"], "content": row["content"],
            "tags": json.loads(row["tags_json"]), "importance": row["importance"],
            "replaces_event_id": row["replaces_event_id"], "metadata": json.loads(row["metadata_json"]),
            "checksum": row["checksum"],
        }
