#!/usr/bin/env python3
"""
cli/main.py — Agent Lab Platform CLI
"""
import argparse
import json
import sys
from typing import Optional
from domain.sessions.models import SessionStatus
from services.orchestrator.orchestrator import ResearchSessionService, OrchestratorError


def format_table(headers, rows):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    sep = "  ".join("-" * w for w in widths)
    lines = [fmt.format(*headers), sep]
    for row in rows:
        lines.append(fmt.format(*[str(v) for v in row]))
    return "\n".join(lines)


def cmd_create(service: ResearchSessionService, args):
    try:
        session = service.create_session(
            objective=args.objective,
            session_id=args.id,
            target=args.target,
            atespace=args.atespace,
            idempotency_key=args.idempotency_key,
        )
        print(f"Research Session '{session.id}' successfully created and queued on AX.")
        print(f"Status:       {session.status.value}")
        print(f"Active Task:  {session.active_task_id}")
        print(f"Objective:    {session.objective}")
    except OrchestratorError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(service: ResearchSessionService, args):
    status_filter = SessionStatus(args.status) if args.status else None
    sessions = service.list_sessions(status_filter)
    if not sessions:
        print("No research sessions found.")
        return

    headers = ["SESSION ID", "STATUS", "TASK ID", "WORKER IP", "VERSION", "CREATED AT"]
    rows = []
    for s in sessions:
        rows.append([
            s.id,
            s.status.value,
            s.active_task_id or "-",
            s.active_worker_ip or "-",
            s.version,
            s.created_at[:19].replace("T", " "),
        ])
    print(format_table(headers, rows))


def cmd_status(service: ResearchSessionService, args):
    session = service.get_session(args.id, sync=True)
    if not session:
        print(f"Error: Session '{args.id}' not found.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(session.to_dict(), indent=2))
        return

    print("=== Research Session Details ===")
    print(f"ID:              {session.id}")
    print(f"Status:          {session.status.value}")
    print(f"Active Task:     {session.active_task_id or '-'}")
    print(f"Active Worker:   {session.active_worker_ip or '-'}")
    print(f"Objective:       {session.objective}")
    print(f"Target:          {session.target}")
    print(f"Concurrency Ver: {session.version}")
    print(f"Created At:      {session.created_at}")
    print(f"Updated At:      {session.updated_at}")
    checkpoints = service.store.list_checkpoints(session.id)
    if checkpoints:
        print("")
        print("--- Checkpoints ---")
        for cp in checkpoints:
            ts = cp.created_at[:19].replace("T", " ")
            print(f"[{ts}] {cp.id} | Workspace: {cp.workspace_version} | Task: {cp.task_id}")

    print("")
    print("--- Recent Audit Trail ---")
    for event in session.audit_trail[-5:]:
        ts = event.timestamp[:19].replace("T", " ")
        print(f"[{ts}] {event.from_status} -> {event.to_status} ({event.reason}) by {event.actor}")


def cmd_suspend(service: ResearchSessionService, args):
    try:
        session = service.suspend_session(
            session_id=args.id,
            reason=args.reason or "Operator manual suspend via CLI",
            idempotency_key=args.idempotency_key,
        )
        print(f"Session '{session.id}' successfully suspended.")
        print(f"Status:  {session.status.value}")
        print("Compute capacity reclaimed in Substrate worker pool.")
    except OrchestratorError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_resume(service: ResearchSessionService, args):
    try:
        session = service.resume_session(
            session_id=args.id,
            reason="Operator manual resume via CLI",
            idempotency_key=args.idempotency_key,
        )
        print(f"Session '{session.id}' successfully resumed onto active worker.")
        print(f"Status:  {session.status.value}")
        print(f"Worker:  {session.active_worker_ip or 'Allocating'}")
    except OrchestratorError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_report(service: ResearchSessionService, args):
    content = service.read_session_artifact(args.id, relative_path=args.path)
    if content is None:
        print(f"No artifact found at '/workspace/{args.path}' for session '{args.id}'.", file=sys.stderr)
        sys.exit(1)
    print(content)


def cmd_delete(service: ResearchSessionService, args):
    success = service.delete_session(args.id)
    if success:
        print(f"Session '{args.id}' and its execution tasks were deleted.")
    else:
        print(f"Session '{args.id}' not found.", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="agent-lab",
        description="Agent Lab Control Plane CLI — Persistent, checkpointable research sessions",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # research subcommands
    res_parser = subparsers.add_parser("research", help="Manage research sessions")
    res_subparsers = res_parser.add_subparsers(dest="action", required=True)

    # create
    p_create = res_subparsers.add_parser("create", help="Create and start a research session")
    p_create.add_argument("--objective", required=True, help="Research objective")
    p_create.add_argument("--id", help="Explicit session ID")
    p_create.add_argument("--target", default="Autonomous Actor Checkpointing & State Persistence")
    p_create.add_argument("--atespace", default="default")
    p_create.add_argument("--idempotency-key", help="Idempotency key for safe retries")

    # list
    p_list = res_subparsers.add_parser("list", help="List all research sessions")
    p_list.add_argument("--status", help="Filter by session status")

    # status
    p_status = res_subparsers.add_parser("status", help="Show session details & audit log")
    p_status.add_argument("id", help="Session ID")
    p_status.add_argument("--json", action="store_true", help="Output full JSON")

    # suspend
    p_suspend = res_subparsers.add_parser("suspend", help="Suspend session and reclaim worker")
    p_suspend.add_argument("id", help="Session ID")
    p_suspend.add_argument("--reason", help="Suspension rationale")
    p_suspend.add_argument("--idempotency-key", help="Idempotency key")

    # resume
    p_resume = res_subparsers.add_parser("resume", help="Resume session onto active worker")
    p_resume.add_argument("id", help="Session ID")
    p_resume.add_argument("--idempotency-key", help="Idempotency key")

    # report
    p_report = res_subparsers.add_parser("report", help="Read research artifacts from workspace")
    p_report.add_argument("id", help="Session ID")
    p_report.add_argument("--path", default="report.md", help="Workspace relative path (default: report.md)")

    # delete
    p_delete = res_subparsers.add_parser("delete", help="Delete session and terminate tasks")
    p_delete.add_argument("id", help="Session ID")

    args = parser.parse_args()

    service = ResearchSessionService()

    if args.command == "research":
        if args.action == "create":
            cmd_create(service, args)
        elif args.action == "list":
            cmd_list(service, args)
        elif args.action == "status":
            cmd_status(service, args)
        elif args.action == "suspend":
            cmd_suspend(service, args)
        elif args.action == "resume":
            cmd_resume(service, args)
        elif args.action == "report":
            cmd_report(service, args)
        elif args.action == "delete":
            cmd_delete(service, args)


if __name__ == "__main__":
    main()
