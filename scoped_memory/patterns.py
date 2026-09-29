"""Local advisory table for repeatable tasks; it never runs a script."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import MemoryError, utc_now


def signature(task_type: str, features: dict[str, Any]) -> tuple[str, str]:
    task_type = task_type.strip()
    if not task_type or not isinstance(features, dict):
        raise MemoryError("task_type and an object of features are required")
    try:
        data = json.dumps(features, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MemoryError("features must be finite JSON values") from exc
    digest = hashlib.sha256((task_type + "\0" + data).encode("utf-8")).hexdigest()
    return digest, data


def script_fingerprint(root: str, script_ref: str) -> str:
    relative = Path(script_ref)
    if not script_ref or "\\" in script_ref or relative.is_absolute() or ".." in relative.parts:
        raise MemoryError("script_ref must be a project-relative script path")
    base = Path(root).resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.suffix not in {".py", ".sh", ".ps1", ".mjs", ".js"}:
        raise MemoryError("script_ref must name an existing script inside this project")
    try:
        if path.stat().st_size > 2_000_000:
            raise MemoryError("script is too large for fingerprinting")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise MemoryError("script is unreadable") from exc


def propose(store, *, project_root: str, task_type: str, features: dict[str, Any],
            script_ref: str, expires_at: str | None = None) -> dict[str, Any]:
    project = store.resolve_project(project_root, required=True)
    digest, encoded = signature(task_type, features)
    fingerprint = script_fingerprint(project.root, script_ref)
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MemoryError("expires_at must be an ISO-8601 timestamp") from exc
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise MemoryError("expires_at must be a future timestamp with timezone")
        expires_at = expiry.astimezone(timezone.utc).isoformat()
    pattern_id = str(uuid.uuid4())
    with store._write_connection() as conn:
        conn.execute(
            """INSERT INTO patterns(pattern_id,owner_id,project_id,task_type,signature,features_json,
               script_ref,script_sha256,state,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (pattern_id, store.owner_id, project.project_id, task_type.strip(), digest, encoded,
             script_ref, fingerprint, "candidate", utc_now(), expires_at),
        )
    return {"pattern_id": pattern_id, "state": "candidate", "signature": digest,
            "script_ref": script_ref, "script_sha256": fingerprint}


def observe(store, *, project_root: str, pattern_id: str, outcome: str, evidence_ref: str) -> dict[str, Any]:
    project = store.resolve_project(project_root, required=True)
    evidence_ref = evidence_ref.strip()
    if outcome not in {"pass", "fail"} or not evidence_ref:
        raise MemoryError("outcome must be pass/fail and evidence_ref must be nonempty")
    with store._write_connection() as conn:
        row = conn.execute("SELECT state FROM patterns WHERE pattern_id=? AND project_id=? AND owner_id=?",
                           (pattern_id, project.project_id, store.owner_id)).fetchone()
        if row is None:
            raise MemoryError("pattern is not in this project")
        try:
            conn.execute("INSERT INTO pattern_observations VALUES(?,?,?,?,?)",
                         (str(uuid.uuid4()), pattern_id, outcome, evidence_ref, utc_now()))
        except sqlite3.IntegrityError as exc:
            # Replaying one observation must never increase the promotion count.
            raise MemoryError("evidence_ref has already been recorded for this pattern") from exc
        if outcome == "fail":
            conn.execute("UPDATE patterns SET state='stale', verified_at=NULL WHERE pattern_id=?", (pattern_id,))
    return {"pattern_id": pattern_id, "outcome": outcome, "state": "stale" if outcome == "fail" else row["state"]}


def verify(store, *, project_root: str, pattern_id: str) -> dict[str, Any]:
    """Explicit local promotion after two reported successes and zero failures."""
    project = store.resolve_project(project_root, required=True)
    with store._write_connection() as conn:
        row = conn.execute("SELECT * FROM patterns WHERE pattern_id=? AND project_id=? AND owner_id=?",
                           (pattern_id, project.project_id, store.owner_id)).fetchone()
        if row is None or row["state"] == "stale":
            raise MemoryError("pattern is missing or stale; propose a new version")
        successes, failures = conn.execute(
            "SELECT SUM(outcome='pass'),SUM(outcome='fail') FROM pattern_observations WHERE pattern_id=?",
            (pattern_id,),
        ).fetchone()
        if (successes or 0) < 2 or (failures or 0):
            raise MemoryError("two distinct success evidence references and no failures are required")
        if script_fingerprint(project.root, row["script_ref"]) != row["script_sha256"]:
            raise MemoryError("script changed; propose a new pattern version")
        if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            raise MemoryError("pattern expired")
        conn.execute("UPDATE patterns SET state='verified',verified_at=? WHERE pattern_id=?",
                     (utc_now(), pattern_id))
    return {"pattern_id": pattern_id, "state": "verified", "success_reports": successes}


def predict(store, *, project_root: str, task_type: str, features: dict[str, Any]) -> dict[str, Any]:
    """Return an exact-match suggestion only; permissions and execution stay elsewhere."""
    project = store.resolve_project(project_root, required=True)
    digest, _ = signature(task_type, features)
    with store._connection() as conn:
        rows = conn.execute(
            """SELECT * FROM patterns WHERE owner_id=? AND project_id=? AND signature=?
               AND state='verified' ORDER BY verified_at DESC""",
            (store.owner_id, project.project_id, digest),
        ).fetchall()
    for row in rows:
        if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            continue
        try:
            if script_fingerprint(project.root, row["script_ref"]) != row["script_sha256"]:
                continue
        except (OSError, MemoryError):
            continue
        return {"status": "verified_match", "pattern_id": row["pattern_id"], "signature": digest,
                "script_ref": row["script_ref"], "script_sha256": row["script_sha256"],
                "verified_at": row["verified_at"], "advisory_only": True}
    return {"status": "no_verified_match", "signature": digest, "advisory_only": True}
