from __future__ import annotations

import argparse
import json
import sys

from .core import MemoryError, MemoryStore


def json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("value must be a JSON object")
    return parsed


def add_scope_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root")
    parser.add_argument("--session-id")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="scoped-memory")
    root.add_argument("--home")
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("project_root", nargs="?", default=".")
    init.add_argument("--name")
    status = sub.add_parser("status")
    status.add_argument("project_root", nargs="?", default=".")
    remember = sub.add_parser("remember")
    remember.add_argument("scope", choices=["user", "project", "session"])
    remember.add_argument("topic")
    remember.add_argument("content")
    add_scope_target(remember)
    remember.add_argument("--tag", action="append", default=[])
    remember.add_argument("--importance", type=int, default=50)
    remember.add_argument("--metadata", type=json_object, default={})
    recall = sub.add_parser("recall")
    recall.add_argument("project_root", nargs="?", default=".")
    recall.add_argument("--session-id")
    recall.add_argument("--query", default="")
    recall.add_argument("--scope", action="append", choices=["user", "project", "session"])
    recall.add_argument("--token-budget", type=int, default=2000)
    recall.add_argument("--inherit-project", action="append", default=[])
    compact = sub.add_parser("recall-compact")
    compact.add_argument("project_root", nargs="?", default=".")
    compact.add_argument("--session-id")
    compact.add_argument("--query", default="")
    compact.add_argument("--scope", action="append", choices=["user", "project", "session"])
    compact.add_argument("--token-budget", type=int, default=2000)
    grant = sub.add_parser("inherit-grant")
    grant.add_argument("project_root")
    grant.add_argument("source_project_id")
    grant.add_argument("expires_at")
    revoke = sub.add_parser("inherit-revoke")
    revoke.add_argument("grant_id")
    task_open = sub.add_parser("task-open")
    task_open.add_argument("project_root", nargs="?", default=".")
    task_context = sub.add_parser("task-context")
    task_context.add_argument("project_root")
    task_context.add_argument("task_id")
    task_context.add_argument("--token-budget", type=int, default=1200)
    task_close = sub.add_parser("task-close")
    task_close.add_argument("project_root")
    task_close.add_argument("task_id")
    task_checkpoint = sub.add_parser("task-checkpoint")
    task_checkpoint.add_argument("project_root")
    task_checkpoint.add_argument("task_id")
    task_checkpoint.add_argument("summary")
    task_checkpoint.add_argument("--decision", action="append", default=[])
    task_checkpoint.add_argument("--constraint", action="append", default=[])
    task_checkpoint.add_argument("--next-step", action="append", default=[])
    task_checkpoint.add_argument("--evidence", action="append", default=[])
    propose = sub.add_parser("pattern-propose")
    propose.add_argument("project_root")
    propose.add_argument("task_type")
    propose.add_argument("features", type=json_object)
    propose.add_argument("script_ref")
    propose.add_argument("--expires-at")
    observe = sub.add_parser("pattern-observe")
    observe.add_argument("project_root")
    observe.add_argument("pattern_id")
    observe.add_argument("outcome", choices=["pass", "fail"])
    observe.add_argument("evidence_ref")
    verify_pattern = sub.add_parser("pattern-verify")
    verify_pattern.add_argument("project_root")
    verify_pattern.add_argument("pattern_id")
    predict = sub.add_parser("pattern-predict")
    predict.add_argument("project_root")
    predict.add_argument("task_type")
    predict.add_argument("features", type=json_object)
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("summary")
    checkpoint.add_argument("--project-root", default=".")
    checkpoint.add_argument("--session-id", required=True)
    checkpoint.add_argument("--decision", action="append", default=[])
    checkpoint.add_argument("--constraint", action="append", default=[])
    checkpoint.add_argument("--next-step", action="append", default=[])
    checkpoint.add_argument("--evidence", action="append", default=[])
    ingest = sub.add_parser("ingest")
    ingest.add_argument("project_root", nargs="?", default=".")
    ingest.add_argument("--max-files", type=int, default=2000)
    ingest.add_argument("--max-file-bytes", type=int, default=256_000)
    engineering = sub.add_parser("engineering-context")
    engineering.add_argument("project_root", nargs="?", default=".")
    engineering.add_argument("--query", default="")
    engineering.add_argument("--token-budget", type=int, default=2000)
    forget = sub.add_parser("forget")
    forget.add_argument("scope", choices=["user", "project", "session"])
    forget.add_argument("topic")
    add_scope_target(forget)
    verify = sub.add_parser("verify")
    rebuild = sub.add_parser("rebuild-audit")
    return root


def main() -> None:
    args = parser().parse_args()
    store = MemoryStore(args.home)
    try:
        if args.command == "init":
            value = store.init_project(args.project_root, args.name)
        elif args.command == "status":
            value = store.status(args.project_root)
        elif args.command == "remember":
            value = store.remember(
                scope=args.scope, topic=args.topic, content=args.content, project_root=args.project_root,
                session_id=args.session_id, tags=args.tag, importance=args.importance, metadata=args.metadata,
            )
        elif args.command == "recall":
            options = {
                "project_root": args.project_root, "session_id": args.session_id, "query": args.query,
                "inherit_project_ids": args.inherit_project, "token_budget": args.token_budget,
            }
            if args.scope:
                options["scopes"] = args.scope
            value = store.recall(**options)
        elif args.command == "recall-compact":
            options = {"project_root": args.project_root, "session_id": args.session_id,
                       "query": args.query, "token_budget": args.token_budget}
            if args.scope:
                options["scopes"] = args.scope
            value = store.recall_compact(**options)
        elif args.command == "inherit-grant":
            value = store.approve_inheritance(project_root=args.project_root,
                                              source_project_id=args.source_project_id,
                                              expires_at=args.expires_at)
        elif args.command == "inherit-revoke":
            value = store.revoke_inheritance(grant_id=args.grant_id)
        elif args.command == "task-open":
            value = store.open_task(args.project_root)
        elif args.command == "task-context":
            value = store.task_context(project_root=args.project_root, task_id=args.task_id,
                                       token_budget=args.token_budget)
        elif args.command == "task-checkpoint":
            value = store.task_checkpoint(project_root=args.project_root, task_id=args.task_id,
                                          summary=args.summary, decisions=args.decision,
                                          constraints=args.constraint, next_steps=args.next_step,
                                          evidence=args.evidence)
        elif args.command == "task-close":
            value = store.close_task(project_root=args.project_root, task_id=args.task_id)
        elif args.command == "pattern-propose":
            value = store.pattern_propose(project_root=args.project_root, task_type=args.task_type,
                                          features=args.features, script_ref=args.script_ref,
                                          expires_at=args.expires_at)
        elif args.command == "pattern-observe":
            value = store.pattern_observe(project_root=args.project_root, pattern_id=args.pattern_id,
                                          outcome=args.outcome, evidence_ref=args.evidence_ref)
        elif args.command == "pattern-verify":
            value = store.pattern_verify(project_root=args.project_root, pattern_id=args.pattern_id)
        elif args.command == "pattern-predict":
            value = store.pattern_predict(project_root=args.project_root, task_type=args.task_type,
                                          features=args.features)
        elif args.command == "checkpoint":
            value = store.checkpoint(
                summary=args.summary, project_root=args.project_root, session_id=args.session_id,
                decisions=args.decision, constraints=args.constraint, next_steps=args.next_step,
                evidence=args.evidence,
            )
        elif args.command == "ingest":
            value = store.ingest_project(
                args.project_root, max_files=args.max_files, max_file_bytes=args.max_file_bytes,
            )
        elif args.command == "engineering-context":
            value = store.engineering_context(
                args.project_root, query=args.query, token_budget=args.token_budget,
            )
        elif args.command == "forget":
            value = store.forget(
                scope=args.scope, topic=args.topic, project_root=args.project_root, session_id=args.session_id,
            )
        elif args.command == "verify":
            value = store.verify_audit()
        elif args.command == "rebuild-audit":
            value = store.rebuild_audit()
        else:
            raise AssertionError(args.command)
    except MemoryError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
