#!/usr/bin/env python3
"""
cli/main.py — Agent Lab Platform CLI

Promoted to a client of the unified Agent Lab REST API.
Operates against the unified control-plane API server, sharing the exact same
backend services as the Web UI and external integrations.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from cli.client import AgentLabClient, APIClientError
from domain.sessions.models import SessionStatus
from services.orchestrator.orchestrator import ResearchSessionService, OrchestratorError


def format_table(headers: List[str], rows: List[List[Any]]) -> str:
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


# ==============================================================================
# Client Dispatch Handlers
# ==============================================================================

def cmd_create(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        session = client.create_session(
            objective=args.objective,
            session_id=args.id,
            target=args.target,
            atespace=args.atespace,
            idempotency_key=args.idempotency_key,
        )
        print(f"Research Session '{session.get('id')}' successfully created via Agent Lab API.")
        print(f"Status:       {session.get('status')}")
        print(f"Active Task:  {session.get('active_task_id')}")
        print(f"Objective:    {session.get('objective')}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        sessions = client.list_sessions(status=args.status)
        if not sessions:
            print("No research sessions found.")
            return

        headers = ["SESSION ID", "STATUS", "TASK ID", "WORKER IP", "VERSION", "CREATED AT"]
        rows = []
        for s in sessions:
            rows.append([
                s.get("id"),
                s.get("status"),
                s.get("active_task_id") or "-",
                s.get("active_worker_ip") or "-",
                s.get("version", 1),
                (s.get("created_at") or "")[:19].replace("T", " "),
            ])
        print(format_table(headers, rows))
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        session = client.get_session(args.id)
        if args.json:
            print(json.dumps(session, indent=2))
            return

        print("=== Research Session Details ===")
        print(f"ID:              {session.get('id')}")
        print(f"Status:          {session.get('status')}")
        print(f"Active Task:     {session.get('active_task_id') or '-'}")
        print(f"Active Worker:   {session.get('active_worker_ip') or '-'}")
        print(f"Objective:       {session.get('objective')}")
        print(f"Target:          {session.get('target')}")
        print(f"Concurrency Ver: {session.get('version')}")
        print(f"Created At:      {session.get('created_at')}")
        print(f"Updated At:      {session.get('updated_at')}")

        checkpoints = client.list_checkpoints(args.id)
        if checkpoints:
            print("")
            print("--- Checkpoints ---")
            for cp in checkpoints:
                ts = (cp.get("created_at") or "")[:19].replace("T", " ")
                print(f"[{ts}] {cp.get('id')} | Workspace: {cp.get('workspace_version')} | Task: {cp.get('task_id')}")

        audit_trail = session.get("audit_trail", [])
        if audit_trail:
            print("")
            print("--- Recent Audit Trail ---")
            for event in audit_trail[-5:]:
                ts = (event.get("timestamp") or "")[:19].replace("T", " ")
                print(f"[{ts}] {event.get('from_status')} -> {event.get('to_status')} ({event.get('reason')}) by {event.get('actor')}")

    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_suspend(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        session = client.suspend_session(
            session_id=args.id,
            reason=args.reason or "Operator manual suspend via CLI",
            idempotency_key=args.idempotency_key,
        )
        print(f"Session '{session.get('id')}' successfully suspended via API.")
        print(f"Status:  {session.get('status')}")
        print("Compute capacity reclaimed in Substrate worker pool.")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_resume(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        session = client.resume_session(
            session_id=args.id,
            idempotency_key=args.idempotency_key,
        )
        print(f"Session '{session.get('id')}' successfully resumed onto active worker via API.")
        print(f"Status:  {session.get('status')}")
        print(f"Worker:  {session.get('active_worker_ip') or 'Allocating'}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_checkpoint(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        cp = client.create_checkpoint(session_id=args.id, reason=args.reason)
        print(f"Checkpoint '{cp.get('id')}' created for session '{args.id}'.")
        print(f"Workspace Version: {cp.get('workspace_version')}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_report(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        art = client.read_artifact(session_id=args.id, relative_path=args.path)
        content = art.get("content")
        if content is None:
            print(f"No artifact found at '/workspace/{args.path}' for session '{args.id}'.", file=sys.stderr)
            sys.exit(1)
        print(content)
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_timeline(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        data = client.get_timeline(session_id=args.id)
        events = data.get("timeline", [])
        print(f"=== Execution Timeline: {args.id} ===")
        for evt in events:
            ts = (evt.get("timestamp") or "")[:19].replace("T", " ")
            print(f"[{ts}] {evt.get('from_status')} -> {evt.get('to_status')} | Reason: {evt.get('reason')} | Actor: {evt.get('actor')}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_workspace(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        data = client.get_workspace(session_id=args.id)
        artifacts = data.get("artifacts", [])
        print(f"=== Workspace Tree: {data.get('workspace_id')} ===")
        if not artifacts:
            print("  (Empty workspace or no artifacts written)")
            return
        for art in artifacts:
            print(f"  📄 {art}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_delete(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        client.delete_session(args.id)
        print(f"Session '{args.id}' and its execution tasks deleted via API.")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_agents_list(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        agents = client.list_agents(role=args.role, tenant=args.tenant, status=args.status)
        if not agents:
            print("No agents registered in Agent Registry.")
            return

        headers = ["AGENT ID", "ROLE", "TENANT", "ENV", "LIFECYCLE", "SUBJECT", "BOUND TASK"]
        rows = []
        for a in agents:
            rows.append([
                a.get("agent_id"),
                a.get("role"),
                a.get("tenant"),
                a.get("environment"),
                a.get("lifecycle_state"),
                a.get("identity_subject"),
                a.get("task_id") or "-",
            ])
        print(format_table(headers, rows))
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_agents_get(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        agent = client.get_agent(args.id)
        if args.json:
            print(json.dumps(agent, indent=2))
            return

        print("=== Logical Agent Details ===")
        print(f"Agent ID:       {agent.get('agent_id')}")
        print(f"Role:           {agent.get('role')}")
        print(f"Tenant:         {agent.get('tenant')}")
        print(f"Environment:    {agent.get('environment')}")
        print(f"Lifecycle:      {agent.get('lifecycle_state')}")
        print(f"Subject:        {agent.get('identity_subject')}")
        print(f"Bound Task:     {agent.get('task_id') or '-'}")
        print(f"Workspace:      {agent.get('workspace_id') or '-'}")
        print(f"Capabilities:   {', '.join(agent.get('capabilities', []))}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_agents_register(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        caps = [c.strip() for c in args.capabilities.split(",")] if args.capabilities else []
        agent = client.register_agent(
            agent_id=args.id,
            role=args.role,
            tenant=args.tenant,
            environment=args.environment,
            capabilities=caps,
            identity_subject=args.subject,
        )
        print(f"Logical Agent '{agent.get('agent_id')}' successfully registered in Agent Registry.")
        print(f"Role:       {agent.get('role')}")
        print(f"Subject:    {agent.get('identity_subject')}")
        print(f"Lifecycle:  {agent.get('lifecycle_state')}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_agents_identity(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        info = client.get_agent_identity(args.id)
        if args.json:
            print(json.dumps(info, indent=2))
            return

        print("=== Cryptographic Workload Identity Status ===")
        print(f"Agent ID:       {info.get('agent_id')}")
        print(f"Subject:        {info.get('subject')}")
        print(f"Lifecycle:      {info.get('lifecycle_state')}")
        print(f"Bound Task:     {info.get('task_id') or '-'}")
        print(f"Bound WS:       {info.get('workspace_id') or '-'}")
        id_info = info.get("identity", {})
        print(f"Token JTI:      {id_info.get('jti') or '-'}")
        print(f"Issuer:         {id_info.get('issuer') or '-'}")
        print(f"Audience:       {id_info.get('audience') or '-'}")
        print(f"Valid:          {'YES' if id_info.get('is_valid') else 'NO'}")
        print(f"Expired:        {'YES' if id_info.get('is_expired') else 'NO'}")
        print(f"Revoked:        {'YES' if id_info.get('is_revoked') else 'NO'}")
        print(f"Token Preview:  {id_info.get('token_preview') or '-'}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_agents_revoke(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        client.revoke_agent_identity(args.id, reason=args.reason or "Operator manual revocation")
        print(f"Workload identity for agent '{args.id}' successfully revoked.")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


# ------------------------------------------------------------------------------
# Milestone 4: Trust & Scope Plane CLI Handlers
# ------------------------------------------------------------------------------

def cmd_capabilities(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        caps = client.list_capabilities()
        if not caps:
            print("No capabilities registered.")
            return

        headers = ["CAPABILITY", "ALLOWED ROLES", "ACTIONS", "RESOURCE PATTERN", "TTL", "MAX DEPTH"]
        rows = []
        for c in caps:
            rows.append([
                c.get("name"),
                ", ".join(c.get("allowed_roles", [])) or "*",
                ", ".join(c.get("allowed_actions", [])) or "*",
                c.get("resource_path_pattern"),
                f"{c.get('default_ttl_seconds')}s",
                c.get("max_delegation_depth", 1),
            ])
        print(format_table(headers, rows))
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_policy_evaluate(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        result = client.evaluate_policy(
            identity_token=args.token,
            requested_capability=args.capability,
            task_id=args.task_id,
            workspace_id=args.workspace_id,
            requested_action=args.action or "*",
            target_resource=args.resource or "/workspace/*",
            delegation_depth=args.delegation_depth,
            environment=args.environment,
        )
        if args.json:
            print(json.dumps(result, indent=2))
            return

        print("=== Policy Evaluation Result ===")
        print(f"Verdict:        {result.get('verdict')}")
        print(f"Reason:         {result.get('reason')}")
        print(f"Rule ID:        {result.get('rule_id') or '-'}")
        scope = result.get("effective_scope")
        if scope:
            print(f"Subject:        {scope.get('subject')}")
            print(f"Capability:     {scope.get('capability')}")
            print(f"Granted Action: {scope.get('granted_action')}")
            print(f"Resource:       {scope.get('resource_path')}")
            print(f"TTL:            {scope.get('ttl_seconds')}s")
            print(f"Max Calls:      {scope.get('max_invocations')}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_scope_issue(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        res = client.issue_scope(
            identity_token=args.token,
            requested_capability=args.capability,
            task_id=args.task_id,
            workspace_id=args.workspace_id,
            requested_action=args.action or "*",
            target_resource=args.resource or "/workspace/*",
            max_invocations=args.quota,
            ttl_seconds=args.ttl,
        )
        if args.json:
            print(json.dumps(res, indent=2))
            return

        st = res.get("scope_token", {})
        print("=== Cryptographic Scope Token Minted ===")
        print(f"Scope ID:       {st.get('scope_id')}")
        print(f"Subject:        {st.get('subject')}")
        print(f"Capability:     {st.get('capability')}")
        print(f"Granted Action: {', '.join(st.get('allowed_actions', []))}")
        print(f"Resource Bound: {st.get('resource_pattern')}")
        print(f"Quota:          {st.get('invocations_remaining')}/{st.get('max_invocations')} remaining")
        print(f"Expires:        {st.get('expires_at')}")
        print(f"\nRaw Scope JWT:\n{res.get('raw_token')}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_gateway_authorize(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        decision = client.gateway_authorize(
            identity_token=args.token,
            scope_token=args.scope,
            action=args.action,
            resource=args.resource,
            task_id=args.task_id,
            workspace_id=args.workspace_id,
            session_id=args.session,
        )
        if args.json:
            print(json.dumps(decision, indent=2))
            return

        print("=== Gateway In-Path Authorization Decision ===")
        print(f"Allowed:        {'YES' if decision.get('allowed') else 'NO'}")
        print(f"Reason:         {decision.get('reason')}")
        print(f"Audit ID:       {decision.get('audit_id')}")
        print(f"Subject:        {decision.get('subject') or '-'}")
        print(f"Capability:     {decision.get('capability') or '-'}")
        print(f"Quota Left:     {decision.get('invocations_remaining') if decision.get('invocations_remaining') is not None else '-'}")
        chain = decision.get("delegation_chain")
        if chain:
            print(f"Delegation Chain: {' -> '.join(chain)}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


# ------------------------------------------------------------------------------
# Milestone 5: Multi-Agent Communication & Delegation CLI Handlers
# ------------------------------------------------------------------------------

def cmd_discover(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        peers = client.discover_peers(
            capability=args.capability,
            tenant=args.tenant,
            environment=args.environment,
            exclude_agent_id=args.exclude,
        )
        if not peers:
            print(f"No active peer agents discovered for capability '{args.capability}'.")
            return

        headers = ["AGENT ID", "ROLE", "TENANT", "ENVIRONMENT", "SUBJECT", "CAPABILITIES"]
        rows = []
        for p in peers:
            rows.append([
                p.get("agent_id"),
                p.get("role"),
                p.get("tenant"),
                p.get("environment"),
                p.get("identity_subject"),
                ", ".join(p.get("capabilities", [])),
            ])
        print(format_table(headers, rows))
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_delegate(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        res = client.delegate_capability(
            caller_identity_token=args.caller_token,
            parent_scope_token=args.parent_scope,
            target_agent_id=args.target,
            task_id=args.task_id,
            workspace_id=args.workspace_id,
            requested_capability=args.capability,
            requested_action=args.action or "*",
            requested_resource=args.resource or "/workspace/*",
            requested_ttl_seconds=args.ttl,
            requested_max_invocations=args.quota,
            requested_delegation_depth=args.depth,
            environment=args.environment,
        )
        if args.json:
            print(json.dumps(res, indent=2))
            return

        print("=== Inter-Agent Capability Delegation Result ===")
        print(f"Verdict:        {res.get('verdict')}")
        print(f"Reason:         {res.get('reason')}")
        print(f"Audit ID:       {res.get('audit_id')}")
        chain = res.get("delegation_chain", [])
        if chain:
            print(f"Chain:          {' -> '.join(chain)}")
        cs = res.get("child_scope")
        if cs:
            print(f"Child Scope ID: {cs.get('scope_id')}")
            print(f"Child Subject:  {cs.get('child_subject')}")
            print(f"Delegated By:   {cs.get('delegated_by')}")
            print(f"Capability:     {cs.get('capability')}")
            print(f"Actions:        {', '.join(cs.get('allowed_actions', []))}")
            print(f"Resource:       {cs.get('resource_pattern')}")
            print(f"Quota:          {cs.get('invocations_remaining')}/{cs.get('max_invocations')}")
            print(f"Remaining Depth:{cs.get('remaining_delegation_depth')}")
            print(f"\nRaw Delegated Child JWT:\n{cs.get('raw_token')}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_delegation_chain(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        info = client.get_delegation_chain(args.scope_id)
        if args.json:
            print(json.dumps(info, indent=2))
            return

        print("=== Delegated Scope Provenance Chain ===")
        print(f"Scope ID:       {info.get('scope_id')}")
        print(f"Parent Scope:   {info.get('parent_scope_id') or '-'}")
        print(f"Root Initiator: {info.get('original_subject')}")
        print(f"Delegated By:   {info.get('delegated_by')}")
        print(f"Current Holder: {info.get('child_subject')}")
        chain = info.get("delegation_chain", [])
        print(f"Full Provenance:{' -> '.join(chain)}")
        print(f"Capability:     {info.get('capability')}")
        print(f"Resource Bound: {info.get('resource_pattern')}")
        print(f"Quota Remaining:{info.get('invocations_remaining')}/{info.get('max_invocations')}")
        print(f"Depth Left:     {info.get('remaining_delegation_depth')}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


# ------------------------------------------------------------------------------
# Milestone 6: Checkpoint Branching CLI Handlers
# ------------------------------------------------------------------------------

def cmd_branch_create(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        caps = [args.capability] if args.capability else None
        actions = [args.action] if args.action else None
        resources = [args.resource] if args.resource else None

        res = client.create_branch(
            checkpoint_id=args.checkpoint,
            caller_identity_token=args.caller_token,
            source_scope_token=args.source_scope,
            hypothesis=args.hypothesis,
            branch_name=args.name,
            target_agent_id=args.target,
            requested_capabilities=caps,
            requested_actions=actions,
            requested_resources=resources,
            requested_ttl=args.ttl,
            max_invocations=args.quota,
        )
        if args.json:
            print(json.dumps(res, indent=2))
            return

        print("=== Checkpoint Forked into Independent Execution Branch ===")
        print(f"Branch ID:          {res.get('branch_id')}")
        print(f"Parent Checkpoint:  {res.get('parent_checkpoint_id')}")
        print(f"Hypothesis:         {res.get('hypothesis')}")
        print(f"Status:             {res.get('status')}")
        print(f"Workspace Gen:      {res.get('workspace_generation')}")
        print(f"Branch Agent ID:    {res.get('agent_id')}")
        print(f"Identity Subject:   {res.get('identity_subject')}")
        print(f"Scope Token ID:     {res.get('scope_id')}")
        print(f"Snapshot Ref:       {res.get('snapshot_reference')}")
        chain = res.get("delegation_chain", [])
        if chain:
            print(f"Lineage Chain:      {' -> '.join(chain)}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_branch_list(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        branches = client.list_branches(session_id=args.session_id)
        if not branches:
            print(f"No execution branches found for session '{args.session_id}'.")
            return

        headers = ["BRANCH ID", "PARENT CHK", "GEN", "STATUS", "AGENT ID", "HYPOTHESIS"]
        rows = []
        for b in branches:
            rows.append([
                b.get("branch_id"),
                b.get("parent_checkpoint_id"),
                b.get("workspace_generation", 1),
                b.get("status"),
                b.get("agent_id"),
                b.get("hypothesis", "")[:40],
            ])
        print(format_table(headers, rows))
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_branch_get(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        b = client.get_branch(args.id)
        if args.json:
            print(json.dumps(b, indent=2))
            return

        print("=== Execution Branch Details ===")
        print(f"Branch ID:          {b.get('branch_id')}")
        print(f"Session ID:         {b.get('session_id')}")
        print(f"Parent Checkpoint:  {b.get('parent_checkpoint_id')}")
        print(f"Generation:         {b.get('workspace_generation')}")
        print(f"Status:             {b.get('status')}")
        print(f"Agent ID:           {b.get('agent_id')}")
        print(f"Identity Subject:   {b.get('identity_subject')}")
        print(f"Scope ID:           {b.get('scope_id')}")
        print(f"Hypothesis:         {b.get('hypothesis')}")
        print(f"Workspace:          {b.get('workspace_id')}")
        print(f"Snapshot Ref:       {b.get('snapshot_reference')}")
        chain = b.get("delegation_chain", [])
        if chain:
            print(f"Provenance Chain:   {' -> '.join(chain)}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_branch_lineage(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        lineage = client.get_lineage(session_id=args.session_id)
        if args.json:
            print(json.dumps(lineage, indent=2))
            return

        print("=== Checkpoint & Branch Lineage DAG ===")
        print(f"Session ID:         {lineage.get('session_id')}")
        print(f"Root Checkpoint:    {lineage.get('root_checkpoint_id') or '-'}")
        print(f"Total Checkpoints:  {lineage.get('total_checkpoints', 0)}")
        print(f"Total Branches:     {lineage.get('total_branches', 0)}")
        print("\nLineage Directed Graph (Parent -> Children):")
        dag = lineage.get("lineage_dag", {})
        for parent_node, children in dag.items():
            if children:
                print(f"  [{parent_node}]")
                for child in children:
                    print(f"    └──> [{child}]")
            else:
                print(f"  [{parent_node}] (leaf)")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


# Milestone 7: Speculative Execution CLI Handlers
def cmd_speculative_run(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        branches_data = []
        if args.branches_json:
            if os.path.exists(args.branches_json):
                with open(args.branches_json) as f:
                    branches_data = json.load(f)
            else:
                branches_data = json.loads(args.branches_json)

        scoring_config = None
        if args.scoring_json:
            if os.path.exists(args.scoring_json):
                with open(args.scoring_json) as f:
                    scoring_config = json.load(f)
            else:
                scoring_config = json.loads(args.scoring_json)

        res = client.run_speculative(
            session_id=args.session_id,
            checkpoint_id=args.checkpoint_id,
            caller_identity_token=args.caller_token,
            source_scope_token=args.scope_token,
            branches=branches_data,
            scoring_config=scoring_config,
            auto_promote=not args.no_auto_promote,
        )

        if args.json:
            print(json.dumps(res, indent=2))
            return

        matrix = res.get("matrix", {})
        promo = res.get("promotion")

        print("=== Speculative Execution Completed ===")
        print(f"Matrix ID:          {matrix.get('matrix_id')}")
        print(f"Parent Checkpoint:  {matrix.get('parent_checkpoint_id')}")
        print(f"Winning Branch ID:  {matrix.get('winning_branch_id') or 'NONE'}")
        print(f"Winning Checkpoint: {matrix.get('winning_checkpoint_id') or 'NONE'}")
        print(f"Promotion Status:   {promo.get('status') if promo else 'NOT_PROMOTED'}")

        print("\nBranch Rankings & Multi-Dimensional Matrix:")
        headers = ["RANK", "BRANCH ID", "FINAL SCORE", "STATUS", "CORRECT", "EVID", "COMPL", "EFF", "REL", "POL", "REP"]
        rows = []
        for rank, b_eval in enumerate(matrix.get("ranked_branches", []), start=1):
            sc = b_eval.get("dimension_scores", {})
            rows.append([
                str(rank),
                b_eval.get("branch_id", ""),
                f"{b_eval.get('final_score', 0.0):.4f}",
                b_eval.get("status", ""),
                f"{sc.get('correctness', 0.0):.2f}",
                f"{sc.get('evidence_quality', 0.0):.2f}",
                f"{sc.get('completeness', 0.0):.2f}",
                f"{sc.get('efficiency', 0.0):.2f}",
                f"{sc.get('reliability', 0.0):.2f}",
                f"{sc.get('policy_compliance', 0.0):.2f}",
                f"{sc.get('reproducibility', 0.0):.2f}",
            ])
        print_table(headers, rows)

    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_speculative_promote(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        res = client.promote_branch(
            session_id=args.session_id,
            winning_branch_id=args.branch_id,
            winning_checkpoint_id=args.checkpoint_id,
            evaluation_id=args.evaluation_id,
            operator=args.operator or "cli-operator",
        )
        if args.json:
            print(json.dumps(res, indent=2))
            return

        print("=== Speculative Branch Promoted to Primary HEAD ===")
        print(f"Promotion ID:       {res.get('promotion_id')}")
        print(f"Session ID:         {res.get('session_id')}")
        print(f"Promoted Branch:    {res.get('winning_branch_id')}")
        print(f"Primary HEAD:       {res.get('promoted_head_checkpoint_id')}")
        print(f"Previous HEAD:      {res.get('previous_head_checkpoint_id') or '-'}")
        print(f"Status:             {res.get('status')}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_speculative_head(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        res = client.get_session_head(session_id=args.session_id)
        if args.json:
            print(json.dumps(res, indent=2))
            return
        print("=== Session Primary HEAD Checkpoint ===")
        print(f"Session ID:         {res.get('session_id')}")
        print(f"HEAD Checkpoint ID: {res.get('head_checkpoint_id') or 'NONE'}")
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


def cmd_speculative_evaluations(client: AgentLabClient, args: argparse.Namespace) -> None:
    try:
        evals = client.list_evaluations(session_id=args.session_id)
        if args.json:
            print(json.dumps(evals, indent=2))
            return
        if not evals:
            print(f"No speculative evaluations found for session '{args.session_id}'.")
            return
        print("=== Speculative Evaluation Matrices ===")
        headers = ["MATRIX ID", "PARENT CHK", "WINNING BRANCH", "WINNING CHK", "CREATED AT"]
        rows = [
            [
                e.get("matrix_id"),
                e.get("parent_checkpoint_id"),
                e.get("winning_branch_id") or "-",
                e.get("winning_checkpoint_id") or "-",
                e.get("created_at"),
            ]
            for e in evals
        ]
        print_table(headers, rows)
    except APIClientError as e:
        print(f"Error ({e.status_code or 'Client'}): {e}", file=sys.stderr)
        sys.exit(1)


# ==============================================================================
# CLI Entrypoint & Parser Configuration
# ==============================================================================



def main():
    parser = argparse.ArgumentParser(
        prog="agent-lab",
        description="Agent Lab Control Plane CLI — Client communicating with the unified Agent Lab API",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("AGENT_LAB_API_URL", "http://127.0.0.1:8000"),
        help="Agent Lab API server URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Direct service execution bypass (for offline/standalone testing)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # research subcommands
    res_parser = subparsers.add_parser("research", help="Manage research sessions via API")
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

    # checkpoint
    p_checkpoint = res_subparsers.add_parser("checkpoint", help="Create explicit checkpoint")
    p_checkpoint.add_argument("id", help="Session ID")
    p_checkpoint.add_argument("--reason", help="Checkpoint rationale")

    # timeline
    p_timeline = res_subparsers.add_parser("timeline", help="View lifecycle event timeline")
    p_timeline.add_argument("id", help="Session ID")

    # workspace
    p_workspace = res_subparsers.add_parser("workspace", help="Explore session workspace artifacts")
    p_workspace.add_argument("id", help="Session ID")

    # report
    p_report = res_subparsers.add_parser("report", help="Read research artifacts from workspace")
    p_report.add_argument("id", help="Session ID")
    p_report.add_argument("--path", default="report.md", help="Workspace relative path (default: report.md)")

    # delete
    p_delete = res_subparsers.add_parser("delete", help="Delete session and terminate tasks")
    p_delete.add_argument("id", help="Session ID")

    # agents subcommands
    agents_parser = subparsers.add_parser("agents", help="Manage logical agents & workload identity via API")
    agents_subparsers = agents_parser.add_subparsers(dest="action", required=True)

    # agents list
    ag_list = agents_subparsers.add_parser("list", help="List registered agents")
    ag_list.add_argument("--role", help="Filter by agent role")
    ag_list.add_argument("--tenant", help="Filter by tenant")
    ag_list.add_argument("--status", help="Filter by lifecycle state")

    # agents get
    ag_get = agents_subparsers.add_parser("get", help="Show agent details")
    ag_get.add_argument("id", help="Agent ID")
    ag_get.add_argument("--json", action="store_true", help="Output full JSON")

    # agents register
    ag_reg = agents_subparsers.add_parser("register", help="Register a new logical agent in registry")
    ag_reg.add_argument("--id", required=True, help="Agent ID")
    ag_reg.add_argument("--role", required=True, help="Agent role")
    ag_reg.add_argument("--tenant", default="default", help="Tenant organization (default: default)")
    ag_reg.add_argument("--environment", default="staging", help="Environment (default: staging)")
    ag_reg.add_argument("--capabilities", help="Comma-separated capability list")
    ag_reg.add_argument("--subject", help="Explicit identity subject (default: agent:<id>)")

    # agents identity
    ag_id = agents_subparsers.add_parser("identity", help="Inspect cryptographic workload identity status")
    ag_id.add_argument("id", help="Agent ID")
    ag_id.add_argument("--json", action="store_true", help="Output full JSON")

    # agents revoke
    ag_rev = agents_subparsers.add_parser("revoke", help="Revoke agent workload identity")
    ag_rev.add_argument("id", help="Agent ID")
    ag_rev.add_argument("--reason", help="Revocation rationale")

    # Direct shortcuts
    sc_list = subparsers.add_parser("list", help="Shortcut: list research sessions")
    sc_list.add_argument("--status", help="Filter by session status")

    sc_status = subparsers.add_parser("status", help="Shortcut: show session details")
    sc_status.add_argument("id", help="Session ID")
    sc_status.add_argument("--json", action="store_true", help="Output full JSON")

    sc_timeline = subparsers.add_parser("timeline", help="Shortcut: view lifecycle timeline")
    sc_timeline.add_argument("id", help="Session ID")

    sc_workspace = subparsers.add_parser("workspace", help="Shortcut: explore workspace")
    sc_workspace.add_argument("id", help="Session ID")

    sc_report = subparsers.add_parser("report", help="Shortcut: read report artifact")
    sc_report.add_argument("id", help="Session ID")
    sc_report.add_argument("--path", default="report.md", help="Artifact path")

    # M4: capabilities
    sc_caps = subparsers.add_parser("capabilities", help="List registered typed capabilities")

    # M4: evaluate-policy
    sc_eval = subparsers.add_parser("evaluate-policy", help="Evaluate Contextual Intersection policy")
    sc_eval.add_argument("--token", required=True, help="Workload Identity Token (JWT)")
    sc_eval.add_argument("--capability", required=True, help="Requested capability name")
    sc_eval.add_argument("--task-id", required=True, help="Task ID")
    sc_eval.add_argument("--workspace-id", required=True, help="Workspace ID")
    sc_eval.add_argument("--action", default="*", help="Requested action")
    sc_eval.add_argument("--resource", default="/workspace/*", help="Target resource path")
    sc_eval.add_argument("--delegation-depth", type=int, default=0, help="Delegation depth")
    sc_eval.add_argument("--environment", default="staging", help="Environment")
    sc_eval.add_argument("--json", action="store_true", help="Output full JSON")

    # M4: issue-scope
    sc_scope = subparsers.add_parser("issue-scope", help="Issue cryptographic short-lived scope token")
    sc_scope.add_argument("--token", required=True, help="Workload Identity Token (JWT)")
    sc_scope.add_argument("--capability", required=True, help="Requested capability name")
    sc_scope.add_argument("--task-id", required=True, help="Task ID")
    sc_scope.add_argument("--workspace-id", required=True, help="Workspace ID")
    sc_scope.add_argument("--action", default="*", help="Requested action")
    sc_scope.add_argument("--resource", default="/workspace/*", help="Target resource path")
    sc_scope.add_argument("--quota", type=int, default=10, help="Max invocations quota")
    sc_scope.add_argument("--ttl", type=int, default=900, help="TTL in seconds")
    sc_scope.add_argument("--json", action="store_true", help="Output full JSON")

    # M4: authorize
    sc_auth = subparsers.add_parser("authorize", help="Gateway in-path invocation authorization")
    sc_auth.add_argument("--token", required=True, help="Workload Identity Token (JWT)")
    sc_auth.add_argument("--scope", required=True, help="Scope Token (JWT)")
    sc_auth.add_argument("--action", required=True, help="Invocation action")
    sc_auth.add_argument("--resource", required=True, help="Invocation target resource")
    sc_auth.add_argument("--task-id", required=True, help="Task ID")
    sc_auth.add_argument("--workspace-id", required=True, help="Workspace ID")
    sc_auth.add_argument("--session", help="Session ID (optional)")
    sc_auth.add_argument("--json", action="store_true", help="Output full JSON")

    # M5: discover
    sc_disc = subparsers.add_parser("discover", help="Discover peer agents by capability")
    sc_disc.add_argument("--capability", required=True, help="Target capability name")
    sc_disc.add_argument("--tenant", default="default", help="Tenant organization (default: default)")
    sc_disc.add_argument("--environment", default="staging", help="Environment (default: staging)")
    sc_disc.add_argument("--exclude", help="Exclude caller agent ID")

    # M5: delegate
    sc_del = subparsers.add_parser("delegate", help="Delegate bounded capability to a peer agent")
    sc_del.add_argument("--caller-token", required=True, help="Caller Workload Identity Token (JWT)")
    sc_del.add_argument("--parent-scope", required=True, help="Parent Scope Token (JWT)")
    sc_del.add_argument("--target", required=True, help="Target Agent ID")
    sc_del.add_argument("--task-id", required=True, help="Task ID")
    sc_del.add_argument("--workspace-id", required=True, help="Workspace ID")
    sc_del.add_argument("--capability", required=True, help="Capability to delegate")
    sc_del.add_argument("--action", default="*", help="Permissible action")
    sc_del.add_argument("--resource", default="/workspace/*", help="Bounded resource pattern")
    sc_del.add_argument("--ttl", type=int, help="Delegated TTL in seconds")
    sc_del.add_argument("--quota", type=int, help="Delegated invocation quota")
    sc_del.add_argument("--depth", type=int, default=0, help="Remaining delegation depth")
    sc_del.add_argument("--environment", default="staging", help="Environment")
    sc_del.add_argument("--json", action="store_true", help="Output full JSON")

    # M5: delegation-chain
    sc_chain = subparsers.add_parser("delegation-chain", help="Inspect delegation provenance chain")
    sc_chain.add_argument("scope_id", help="Child Scope ID")
    sc_chain.add_argument("--json", action="store_true", help="Output full JSON")

    # M6: branch
    p_branch = subparsers.add_parser("branch", help="Checkpoint branching operations")
    branch_subs = p_branch.add_subparsers(dest="action", required=True)

    sb_create = branch_subs.add_parser("create", help="Fork checkpoint into an independent branch")
    sb_create.add_argument("--checkpoint", required=True, help="Parent Checkpoint ID")
    sb_create.add_argument("--caller-token", required=True, help="Caller Workload Identity Token (JWT)")
    sb_create.add_argument("--source-scope", required=True, help="Source Scope Token (JWT)")
    sb_create.add_argument("--hypothesis", required=True, help="Hypothesis / branch purpose")
    sb_create.add_argument("--name", help="Optional branch name / ID")
    sb_create.add_argument("--target", help="Optional target agent ID")
    sb_create.add_argument("--capability", help="Requested branch capability")
    sb_create.add_argument("--action", help="Requested branch action")
    sb_create.add_argument("--resource", help="Requested branch resource pattern")
    sb_create.add_argument("--ttl", type=int, default=3600, help="Branch TTL in seconds")
    sb_create.add_argument("--quota", type=int, default=10, help="Branch max invocations quota")
    sb_create.add_argument("--json", action="store_true", help="Output full JSON")

    sb_list = branch_subs.add_parser("list", help="List execution branches for session")
    sb_list.add_argument("--session-id", required=True, help="Session ID")
    sb_list.add_argument("--json", action="store_true", help="Output full JSON")

    sb_get = branch_subs.add_parser("get", help="Get execution branch details")
    sb_get.add_argument("id", help="Branch ID")
    sb_get.add_argument("--json", action="store_true", help="Output full JSON")

    sb_lineage = branch_subs.add_parser("lineage", help="Get checkpoint & branch lineage DAG")
    sb_lineage.add_argument("--session-id", required=True, help="Session ID")
    sb_lineage.add_argument("--json", action="store_true", help="Output full JSON")

    # M7: speculative
    p_spec = subparsers.add_parser("speculative", help="Speculative execution & branch promotion operations")
    spec_subs = p_spec.add_subparsers(dest="action", required=True)

    sb_spec_run = spec_subs.add_parser("run", help="Run speculative hypotheses and evaluate branches")
    sb_spec_run.add_argument("--session-id", required=True, help="Research session ID")
    sb_spec_run.add_argument("--checkpoint-id", required=True, help="Baseline parent checkpoint ID")
    sb_spec_run.add_argument("--caller-token", required=True, help="Workload identity JWT token")
    sb_spec_run.add_argument("--scope-token", required=True, help="Parent authorization scope token")
    sb_spec_run.add_argument("--branches-json", required=True, help="JSON file or string defining competing branches")
    sb_spec_run.add_argument("--scoring-json", help="Optional JSON file or string defining scoring weights")
    sb_spec_run.add_argument("--no-auto-promote", action="store_true", help="Do not automatically promote winner")
    sb_spec_run.add_argument("--json", action="store_true", help="Output raw JSON")

    sb_spec_promote = spec_subs.add_parser("promote", help="Promote branch checkpoint to Primary HEAD")
    sb_spec_promote.add_argument("--session-id", required=True, help="Research session ID")
    sb_spec_promote.add_argument("--branch-id", required=True, help="Winning branch ID")
    sb_spec_promote.add_argument("--checkpoint-id", required=True, help="Winning checkpoint ID")
    sb_spec_promote.add_argument("--evaluation-id", help="Optional evaluation ID")
    sb_spec_promote.add_argument("--operator", default="cli-operator", help="Promoting operator name")
    sb_spec_promote.add_argument("--json", action="store_true", help="Output raw JSON")

    sb_spec_head = spec_subs.add_parser("head", help="Get Primary HEAD checkpoint ID")
    sb_spec_head.add_argument("--session-id", required=True, help="Research session ID")
    sb_spec_head.add_argument("--json", action="store_true", help="Output raw JSON")

    sb_spec_evals = spec_subs.add_parser("evaluations", help="List speculative evaluations")
    sb_spec_evals.add_argument("--session-id", required=True, help="Research session ID")
    sb_spec_evals.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()

    client = AgentLabClient(base_url=args.api_url)

    if args.command == "research":
        if args.action == "create":
            cmd_create(client, args)
        elif args.action == "list":
            cmd_list(client, args)
        elif args.action == "status":
            cmd_status(client, args)
        elif args.action == "suspend":
            cmd_suspend(client, args)
        elif args.action == "resume":
            cmd_resume(client, args)
        elif args.action == "checkpoint":
            cmd_checkpoint(client, args)
        elif args.action == "timeline":
            cmd_timeline(client, args)
        elif args.action == "workspace":
            cmd_workspace(client, args)
        elif args.action == "report":
            cmd_report(client, args)
        elif args.action == "delete":
            cmd_delete(client, args)
    elif args.command == "agents":
        if args.action == "list":
            cmd_agents_list(client, args)
        elif args.action == "get":
            cmd_agents_get(client, args)
        elif args.action == "register":
            cmd_agents_register(client, args)
        elif args.action == "identity":
            cmd_agents_identity(client, args)
        elif args.action == "revoke":
            cmd_agents_revoke(client, args)
    elif args.command == "list":
        cmd_list(client, args)
    elif args.command == "status":
        cmd_status(client, args)
    elif args.command == "timeline":
        cmd_timeline(client, args)
    elif args.command == "workspace":
        cmd_workspace(client, args)
    elif args.command == "report":
        cmd_report(client, args)
    elif args.command == "capabilities":
        cmd_capabilities(client, args)
    elif args.command == "evaluate-policy":
        cmd_policy_evaluate(client, args)
    elif args.command == "issue-scope":
        cmd_scope_issue(client, args)
    elif args.command == "authorize":
        cmd_gateway_authorize(client, args)
    elif args.command == "discover":
        cmd_discover(client, args)
    elif args.command == "delegate":
        cmd_delegate(client, args)
    elif args.command == "delegation-chain":
        cmd_delegation_chain(client, args)
    elif args.command == "branch":
        if args.action == "create":
            cmd_branch_create(client, args)
        elif args.action == "list":
            cmd_branch_list(client, args)
        elif args.action == "get":
            cmd_branch_get(client, args)
        elif args.action == "lineage":
            cmd_branch_lineage(client, args)
    elif args.command == "speculative":
        if args.action == "run":
            cmd_speculative_run(client, args)
        elif args.action == "promote":
            cmd_speculative_promote(client, args)
        elif args.action == "head":
            cmd_speculative_head(client, args)
        elif args.action == "evaluations":
            cmd_speculative_evaluations(client, args)




if __name__ == "__main__":
    main()

