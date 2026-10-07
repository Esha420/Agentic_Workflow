#!/usr/bin/env python3
"""
experiments/004-trust-and-scope/run_scope_experiment.py

Milestone 4 Verification Suite: Trust & Scope Plane
Empirically verifies:
  1. Capability Registry & Typed Boundaries
  2. Contextual Intersection Policy Engine (6-dimension evaluation)
  3. Cryptographic Scope Token Minting & Invocation Quotas
  4. Fail-Closed Security Boundary Invariants (Negative Vectors)
  5. In-Path Agent Gateway Interception & Audit Provenance
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from typing import Any, Dict, List

# Ensure repository root is in sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from domain.policy.models import (
    AuthorizationRequest,
    EvaluationVerdict,
    PolicyRule,
    RuleEffect,
)
from services.agents.registry import AgentRegistryService
from services.identity.manager import IdentityManager
from services.policy.capabilities import CapabilityRegistry
from services.policy.engine import PolicyEngine
from services.policy.scope_issuer import ScopeIssuer, ScopeIssuerError
from services.gateway.authorizer import AgentGatewayAuthorizer
from adapters.storage.metadata_store import SQLiteMetadataStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agent-lab.experiment-004")


def print_banner(text: str) -> None:
    sep = "=" * 80
    print(f"\n{sep}\n{text.center(80)}\n{sep}\n")


def print_subbanner(text: str) -> None:
    print(f"\n--- {text} ---")


def run_experiment() -> Dict[str, Any]:
    print_banner("EXPERIMENT 004: TRUST & SCOPE PLANE VERIFICATION")

    results = {
        "experiment_id": "EXP-004-TRUST-AND-SCOPE",
        "timestamp": time.time(),
        "phases": {},
        "overall_status": "FAILED",
    }

    # Isolated temporary database
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    db_path = tmp_db.name

    try:
        store = SQLiteMetadataStore(db_path=db_path)
        agent_registry = AgentRegistryService(store)
        id_mgr = IdentityManager(registry=agent_registry, metadata_store=store)
        cap_registry = CapabilityRegistry()
        policy_engine = PolicyEngine(
            capability_registry=cap_registry,
            identity_manager=id_mgr,
            metadata_store=store,
        )
        scope_issuer = ScopeIssuer(policy_engine=policy_engine)
        gateway = AgentGatewayAuthorizer(
            identity_manager=id_mgr,
            scope_issuer=scope_issuer,
            metadata_store=store,
        )

        # ======================================================================
        # PHASE 1: Capability Registry & Typed Boundaries
        # ======================================================================
        print_subbanner("Phase 1: Capability Registry & Typed Schema Lookup")
        caps = cap_registry.list_capabilities()
        print(f"Total registered capabilities: {len(caps)}")
        for c in caps:
            print(f"  • {c.name:<18} roles={c.allowed_roles} actions={c.allowed_actions} res='{c.resource_path_pattern}' ttl={c.default_ttl_seconds}s")

        web_cap = cap_registry.get_capability("web_research")
        assert web_cap is not None, "Capability 'web_research' missing"
        assert web_cap.is_role_allowed("research-agent") is True
        assert web_cap.is_role_allowed("untrusted-role") is False
        assert web_cap.is_action_allowed("search") is True
        assert web_cap.is_action_allowed("format_drive") is False
        assert web_cap.is_resource_allowed("/workspace/research/notes.md") is True
        assert web_cap.is_resource_allowed("/etc/shadow") is False

        results["phases"]["phase_1_capability_registry"] = {
            "status": "PASSED",
            "registered_capabilities_count": len(caps),
            "verified_capabilities": [c.name for c in caps],
        }
        print("  [SUCCESS] Phase 1: Typed capability contracts verified.")

        # ======================================================================
        # PHASE 2: Contextual Intersection Policy Engine
        # ======================================================================
        print_subbanner("Phase 2: Contextual Intersection Policy Engine Evaluation")

        # Provision Researcher Agent
        researcher = agent_registry.register_agent(
            agent_id="researcher-42",
            role="research-agent",
            tenant="acme-corp",
            environment="staging",
            capabilities=["web_research", "document_analysis"],
        )
        _, res_token = id_mgr.provision_agent_identity(
            agent_id="researcher-42",
            task_id="T-900-research",
            workspace_id="WS-acme-research",
        )
        print(f"Registered & provisioned agent: {researcher.agent_id} ({researcher.identity_subject})")

        # Evaluate valid request
        eval_req = AuthorizationRequest(
            identity_token=res_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/sources.json",
            task_id="T-900-research",
            workspace_id="WS-acme-research",
            environment="staging",
        )
        eval_result = policy_engine.evaluate(eval_req)
        print(f"Evaluation Verdict: {eval_result.verdict.value}")
        print(f"Evaluation Reason:  {eval_result.reason}")
        print(f"Audit ID:           {eval_result.audit_id}")

        assert eval_result.verdict == EvaluationVerdict.ALLOWED, "Evaluation expected ALLOWED"
        assert eval_result.effective_scope is not None, "Effective scope expected"
        assert eval_result.effective_scope["subject"] == researcher.identity_subject
        assert eval_result.effective_scope["capability"] == "web_research"
        assert eval_result.effective_scope["granted_action"] == "search"

        results["phases"]["phase_2_contextual_intersection"] = {
            "status": "PASSED",
            "verdict": eval_result.verdict.value,
            "rule_id": eval_result.rule_id,
            "effective_scope": eval_result.effective_scope,
        }
        print("  [SUCCESS] Phase 2: Contextual intersection computed correctly.")

        # ======================================================================
        # PHASE 3: Cryptographic Scope Token Minting & Quotas
        # ======================================================================
        print_subbanner("Phase 3: Cryptographic Scope Token Issuance & Invocation Quotas")

        scope_token = scope_issuer.issue_scope(request=eval_req, max_invocations=3, ttl_seconds=600)
        print(f"Minted Scope Token: {scope_token.scope_id}")
        print(f"  Subject:           {scope_token.subject}")
        print(f"  Capability:        {scope_token.capability}")
        print(f"  Quota:             {scope_token.invocations_remaining}/{scope_token.max_invocations}")
        print(f"  Token Preview:     {scope_token.raw_token[:35]}...")

        # Consume invocation 1
        s1 = scope_issuer.validate_and_consume_scope(
            raw_scope_token=scope_token.raw_token,
            expected_action="search",
            expected_resource="/workspace/research/sources.json",
        )
        print(f"  Call 1 consumed -> Remaining: {s1.invocations_remaining}")
        assert s1.invocations_remaining == 2

        # Consume invocation 2
        s2 = scope_issuer.validate_and_consume_scope(
            raw_scope_token=scope_token.raw_token,
            expected_action="search",
            expected_resource="/workspace/research/sources.json",
        )
        print(f"  Call 2 consumed -> Remaining: {s2.invocations_remaining}")
        assert s2.invocations_remaining == 1

        # Consume invocation 3
        s3 = scope_issuer.validate_and_consume_scope(
            raw_scope_token=scope_token.raw_token,
            expected_action="search",
            expected_resource="/workspace/research/sources.json",
        )
        print(f"  Call 3 consumed -> Remaining: {s3.invocations_remaining}")
        assert s3.invocations_remaining == 0

        # Call 4 must fail closed on quota exhaustion
        quota_blocked = False
        try:
            scope_issuer.validate_and_consume_scope(
                raw_scope_token=scope_token.raw_token,
                expected_action="search",
                expected_resource="/workspace/research/sources.json",
            )
        except ScopeIssuerError as e:
            quota_blocked = True
            print(f"  Call 4 rejected as expected: {e}")

        assert quota_blocked, "Exhausted quota must block subsequent invocations"

        results["phases"]["phase_3_scope_tokens_and_quotas"] = {
            "status": "PASSED",
            "scope_id": scope_token.scope_id,
            "max_invocations": scope_token.max_invocations,
            "consumed_calls": 3,
            "quota_exhaustion_enforced": quota_blocked,
        }
        print("  [SUCCESS] Phase 3: Scope tokens minted and quota constraints enforced.")

        # ======================================================================
        # PHASE 4: Fail-Closed Security Boundary Invariants
        # ======================================================================
        print_subbanner("Phase 4: Fail-Closed Boundary Violations (5 Negative Vectors)")

        # Vector 1: Unauthorized Role (coder requesting prod_deploy)
        coder = agent_registry.register_agent(
            agent_id="coder-88",
            role="coder-agent",
            tenant="acme-corp",
            environment="staging",
            capabilities=["code_generation"],
        )
        _, coder_token = id_mgr.provision_agent_identity(
            agent_id="coder-88",
            task_id="T-901-code",
            workspace_id="WS-acme-code",
        )
        v1_req = AuthorizationRequest(
            identity_token=coder_token.raw_token,
            requested_capability="prod_deploy",
            requested_action="deploy",
            target_resource="/workspace/deploy/helm.yaml",
            task_id="T-901-code",
            workspace_id="WS-acme-code",
        )
        v1_res = policy_engine.evaluate(v1_req)
        print(f"  Vector 1 (Role Mismatch): {v1_res.verdict.value} - {v1_res.reason}")
        assert v1_res.verdict == EvaluationVerdict.DENIED

        # Vector 2: Resource Path Escape (/etc/shadow)
        v2_req = AuthorizationRequest(
            identity_token=res_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/etc/shadow",
            task_id="T-900-research",
            workspace_id="WS-acme-research",
        )
        v2_res = policy_engine.evaluate(v2_req)
        print(f"  Vector 2 (Path Escape): {v2_res.verdict.value} - {v2_res.reason}")
        assert v2_res.verdict == EvaluationVerdict.DENIED

        # Vector 3: Task Context Mismatch (token bound to T-900 used for T-WRONG)
        v3_req = AuthorizationRequest(
            identity_token=res_token.raw_token,
            requested_capability="web_research",
            requested_action="search",
            target_resource="/workspace/research/sources.json",
            task_id="T-TAMPERED-TASK",
            workspace_id="WS-acme-research",
        )
        v3_res = policy_engine.evaluate(v3_req)
        print(f"  Vector 3 (Task Mismatch): {v3_res.verdict.value} - {v3_res.reason}")
        assert v3_res.verdict == EvaluationVerdict.DENIED

        # Vector 4: Scope Token Theft / Subject Mismatch
        # Mint valid scope for researcher-42
        fresh_scope = scope_issuer.issue_scope(request=eval_req, max_invocations=5)
        # Coder attempts to use researcher's scope at the gateway
        v4_dec = gateway.authorize_invocation(
            identity_token=coder_token.raw_token,
            scope_token=fresh_scope.raw_token,
            action="search",
            resource="/workspace/research/sources.json",
            task_id="T-901-code",
            workspace_id="WS-acme-code",
        )
        print(f"  Vector 4 (Scope Theft): Allowed={v4_dec.allowed} - {v4_dec.reason}")
        assert v4_dec.allowed is False
        assert "does not match identity subject" in v4_dec.reason

        # Vector 5: Revoked Identity at Gateway
        id_mgr.terminate_agent_identity("coder-88", reason="Immediate quarantine")
        v5_dec = gateway.authorize_invocation(
            identity_token=coder_token.raw_token,
            scope_token=fresh_scope.raw_token,
            action="generate",
            resource="/workspace/src/main.py",
            task_id="T-901-code",
            workspace_id="WS-acme-code",
        )
        print(f"  Vector 5 (Revoked Identity): Allowed={v5_dec.allowed} - {v5_dec.reason}")
        assert v5_dec.allowed is False
        assert "Identity invalid" in v5_dec.reason

        results["phases"]["phase_4_fail_closed_boundaries"] = {
            "status": "PASSED",
            "vectors_tested": 5,
            "all_denied": True,
        }
        print("  [SUCCESS] Phase 4: All 5 fail-closed boundary vectors successfully repelled.")

        # ======================================================================
        # PHASE 5: In-Path Gateway Authorizer & Audit Provenance
        # ======================================================================
        print_subbanner("Phase 5: Agent Gateway In-Path Authorization & Audit Provenance")

        # Legitimate gateway invocation
        auth_decision = gateway.authorize_invocation(
            identity_token=res_token.raw_token,
            scope_token=fresh_scope.raw_token,
            action="search",
            resource="/workspace/research/sources.json",
            task_id="T-900-research",
            workspace_id="WS-acme-research",
            session_id="session-audit-proof-01",
        )
        print(f"Gateway Decision: Allowed={auth_decision.allowed}")
        print(f"Audit Event ID:   {auth_decision.audit_id}")
        print(f"Quota Remaining:  {auth_decision.invocations_remaining}")
        assert auth_decision.allowed is True

        # Query SQLite audit log
        audit_events = store.list_audit_events(session_id="session-audit-proof-01")
        print(f"Retrieved audit trail records: {len(audit_events)}")
        for evt in audit_events:
            print(f"  • [{evt.timestamp[:19]}] actor={evt.actor} -> {evt.to_status} ({evt.reason}) details={evt.details}")

        assert len(audit_events) >= 1
        assert audit_events[0].to_status == "ALLOWED"
        assert audit_events[0].actor == "agent-gateway"

        results["phases"]["phase_5_gateway_and_audit"] = {
            "status": "PASSED",
            "gateway_audit_events_recorded": len(audit_events),
            "last_event_id": audit_events[0].event_id,
            "last_status": audit_events[0].to_status,
        }
        print("  [SUCCESS] Phase 5: In-path authorization and audit trail verified.")

        results["overall_status"] = "PASSED"
        print_banner("EXPERIMENT 004 COMPLETED: 100% SUCCESS ACROSS ALL 5 PHASES")

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

    # Persist summary
    summary_path = os.path.join(os.path.dirname(__file__), "experiment_summary.json")
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Experiment summary written to: {summary_path}")

    return results


if __name__ == "__main__":
    res = run_experiment()
    if res.get("overall_status") != "PASSED":
        sys.exit(1)
