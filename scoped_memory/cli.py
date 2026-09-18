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
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("summary")
    checkpoint.add_argument("--project-root", default=".")
    checkpoint.add_argument("--session-id", required=True)
    checkpoint.add_argument("--decision", action="append", default=[])
    checkpoint.add_argument("--constraint", action="append", default=[])
    checkpoint.add_argument("--next-step", action="append", default=[])
    checkpoint.add_argument("--evidence", action="append", default=[])
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
        elif args.command == "checkpoint":
            value = store.checkpoint(
                summary=args.summary, project_root=args.project_root, session_id=args.session_id,
                decisions=args.decision, constraints=args.constraint, next_steps=args.next_step,
                evidence=args.evidence,
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
