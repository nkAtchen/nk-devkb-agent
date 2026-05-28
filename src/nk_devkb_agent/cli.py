from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .pipeline import DEFAULT_NAMESPACE, create_rag_pipeline


def db_path_for_root(root: Path) -> Path:
    return root / ".kb" / "kb.sqlite"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb")
    parser.add_argument("--root", default=".", help="Project root containing the .kb workspace")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(command_parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        command_parser.add_argument("--root", default=argparse.SUPPRESS, help="Project root containing the .kb workspace")
        command_parser.add_argument("--namespace", default=argparse.SUPPRESS)
        return command_parser

    add_common(subparsers.add_parser("init"))

    ingest = add_common(subparsers.add_parser("ingest"))
    ingest_sub = ingest.add_subparsers(dest="ingest_command", required=True)
    ingest_file = add_common(ingest_sub.add_parser("file"))
    ingest_file.add_argument("path")

    ask = add_common(subparsers.add_parser("ask"))
    ask.add_argument("question")

    search = add_common(subparsers.add_parser("search"))
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)

    summarize = add_common(subparsers.add_parser("summarize"))
    summarize.add_argument("target", nargs="?", default="collection", choices=["collection", "file"])
    summarize.add_argument("doc_id", nargs="?")

    add_common(subparsers.add_parser("sources"))
    add_common(subparsers.add_parser("refresh"))

    schedule = add_common(subparsers.add_parser("schedule"))
    schedule_sub = schedule.add_subparsers(dest="schedule_command", required=True)
    schedule_set = add_common(schedule_sub.add_parser("set"))
    schedule_set.add_argument("--daily-at", default="12:00")
    schedule_set.add_argument("--timezone", default="local")
    add_common(schedule_sub.add_parser("list"))
    add_common(schedule_sub.add_parser("run-now"))

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve()
    tool = create_rag_pipeline(db_path=db_path_for_root(root), namespace=args.namespace)

    if args.command == "init":
        tool.init_namespace(args.namespace, root)
        print(f"initialized namespace {args.namespace} at {db_path_for_root(root)}")
        return 0

    if args.command == "ingest":
        if args.ingest_command == "file":
            source_id = tool.ingest_file(args.path, args.namespace)
            print(f"ingested {source_id}")
            return 0

    if args.command == "search":
        results = tool.search(args.query, args.namespace, args.top_k)
        for result in results:
            heading = " / ".join(result.heading_path)
            print(f"{result.score:.2f}\t{result.title}\t{heading}\t{result.text[:160]}")
        return 0

    if args.command == "ask":
        answer = tool.ask(args.question, args.namespace)
        print(answer.text)
        print(
            "reflection: "
            + json.dumps(
                {
                    "passed": answer.reflection.passed,
                    "reasons": answer.reflection.reasons,
                    "suggested_action": answer.reflection.suggested_action,
                    "used_rag": answer.used_rag,
                    "no_rag_context": answer.no_rag_context,
                },
                ensure_ascii=False,
            )
        )
        if answer.citations:
            print("citations:")
            for citation in answer.citations:
                print(json.dumps(citation, ensure_ascii=False))
        return 0

    if args.command == "summarize":
        print(tool.summarize(args.namespace, target=args.target, doc_id=args.doc_id))
        return 0

    if args.command == "sources":
        for source in tool.sources(args.namespace):
            print(f"{source.status}\t{source.title}\t{source.locator}")
        return 0

    if args.command == "refresh":
        print(tool.refresh(args.namespace))
        return 0

    if args.command == "schedule":
        if args.schedule_command == "set":
            schedule = tool.configure_daily_schedule(
                namespace=args.namespace,
                daily_at=args.daily_at,
                timezone=args.timezone,
            )
            print(f"schedule {schedule.schedule_id}: {schedule.cron_expr} {schedule.timezone}")
            return 0
        if args.schedule_command == "list":
            for schedule in tool.schedules(args.namespace):
                enabled = "enabled" if schedule.enabled else "disabled"
                print(f"{schedule.schedule_id}\t{schedule.cron_expr}\t{schedule.timezone}\t{enabled}")
            return 0
        if args.schedule_command == "run-now":
            print(tool.run_scheduled_collection(args.namespace))
            return 0

    parser.error("unsupported command")
    return 2
