#!/usr/bin/env python3
"""
experiments/005-multi-agent-delegation/run_delegation_experiment.py

Milestone 5 Verification Suite: Multi-Agent Delegation & Child Scope ⊆ Parent Scope
Empirically tests the 10 adversarial delegation phases:
  Phase 1: Agent A delegates an allowed capability to Agent B
  Phase 2: Child scope is proven to be a subset of parent scope
  Phase 3: Agent B attempts capability escalation (DENIED)
  Phase 4: Agent B attempts resource/path escalation (DENIED)
  Phase 5: Agent B attempts cross-task delegation (DENIED)
  Phase 6: Agent B attempts cross-tenant delegation (DENIED)
  Phase 7: Delegation depth reaches zero (DENIED)
  Phase 8: Expired/revoked parent scope invalidates delegation (DENIED)
  Phase 9: Full multi-hop delegation chain is reconstructed from audit (A -> B -> C)
  Phase 10: Gateway blocks every invalid delegation fail-closed

Core Acceptance Criterion:
No sequence of valid delegations can produce authority that was not present in the original authorized scope.
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

from domain.agents.models import AgentLifecycleState
from domain.delegation.models import DelegationRequest, DelegationVerdict
from domain.policy.models import AuthorizationRequest
from services.agents.registry import AgentRegistryService
from services.identity.manager import IdentityManager
from services.policy.capabilities import CapabilityRegistry
from services.policy.engine import PolicyEngine
from services.policy.scope_issuer import ScopeIssuer
from services.delegation.engine import DelegationEngine
from services.communication.manager import CommunicationManager
from services.gateway.authorizer import AgentGatewayAuthorizer
from adapters.storage.metadata_store import SQLiteMetadataStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agent-lab.experiment-005")


def print_banner(text: str) -> None:
    sep = "=" * 80
    print(f"\n{sep}\n{text.center(80)}\n{sep}\n")


def print_subbanner(text: str) -> None:
    print(f"\n--- {text} ---")


def run_experiment() -> Dict[str, Any]:
    print_banner("EXPERIMENT 005: MULTI-AGENT DELEGATION & INVARIANT ENFORCEMENT")

    results = {
        "experiment_id": "EXP-005-MULTI-AGENT-DELEGATION",
        "timestamp": time.time(),
        "phases": {},
        "overall_status": "FAILED",
    }

    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    db_path = tmp_db.name

    try:
        store = SQLiteMetadataStore(db_path=db_path)
        registry = AgentRegistryService(store)
        id_mgr = IdentityManager(registry=registry, metadata_store=store)
        cap_registry = CapabilityRegistry()

        # Configure document_analysis to allow delegation depth 2 and lead-researcher role
        doc_cap = cap_registry.get_capability("document_analysis")
        if doc_cap:
            doc_cap.max_delegation_depth = 2
            if "lead-researcher" not in doc_cap.allowed_roles:
                doc_cap.allowed_roles.append("lead-researcher")

        policy_engine = PolicyEngine(
            capability_registry=cap_registry,
            identity_manager=id_mgr,
            metadata_store=store,
        )
        for rule in policy_engine._rules:
            if "lead-researcher" not in rule.target_roles:
                rule.target_roles.append("lead-researcher")

        scope_issuer = ScopeIssuer(policy_engine=policy_engine)
        delegation_engine = DelegationEngine(
            agent_registry=registry,
            identity_manager=id_mgr,
            capability_registry=cap_registry,
            scope_issuer=scope_issuer,
            metadata_store=store,
        )
        comm_mgr = CommunicationManager(
            delegation_engine=delegation_engine,
            agent_registry=registry,
            metadata_store=store,
        )
        gateway = AgentGatewayAuthorizer(
            identity_manager=id_mgr,
            scope_issuer=scope_issuer,
            delegation_engine=delegation_engine,
            metadata_store=store,
        )

        TASK_ID = "T-482-autonomous-research"
        WORKSPACE_ID = "WS-security-mesh"

        # Register Agent A (Planner / Lead Researcher)
        agent_a = registry.register_agent(
            agent_id="planner-01",
            role="lead-researcher",
            tenant="acme",
            environment="staging",
            capabilities=["web_research", "document_analysis"],
        )
        registry.update_lifecycle("planner-01", AgentLifecycleState.ACTIVE)
        _, token_a = id_mgr.provision_agent_identity(
            agent_id="planner-01",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
        )

        # Register Agent B (Researcher)
        agent_b = registry.register_agent(
            agent_id="researcher-27",
            role="research-agent",
            tenant="acme",
            environment="staging",
            capabilities=["document_analysis", "web_research"],
        )
        registry.update_lifecycle("researcher-27", AgentLifecycleState.ACTIVE)
        _, token_b = id_mgr.provision_agent_identity(
            agent_id="researcher-27",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
        )

        # Register Agent C (Specialized Document Extractor)
        agent_c = registry.register_agent(
            agent_id="document-agent-42",
            role="reviewer-agent",
            tenant="acme",
            environment="staging",
            capabilities=["document_analysis"],
        )
        registry.update_lifecycle("document-agent-42", AgentLifecycleState.ACTIVE)
        _, token_c = id_mgr.provision_agent_identity(
            agent_id="document-agent-42",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
        )

        # Register Agent Rival (Different tenant)
        agent_rival = registry.register_agent(
            agent_id="rival-spy-007",
            role="research-agent",
            tenant="rival-corp",
            environment="staging",
            capabilities=["document_analysis"],
        )
        registry.update_lifecycle("rival-spy-007", AgentLifecycleState.ACTIVE)
        _, token_rival = id_mgr.provision_agent_identity(
            agent_id="rival-spy-007",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
        )

        # Mint Root Parent Scope Token for Agent A
        parent_auth_req = AuthorizationRequest(
            identity_token=token_a.raw_token,
            requested_capability="document_analysis",
            requested_action="read",
            target_resource="/workspace/research/*",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
            delegation_depth=2,
            environment="staging",
        )
        parent_scope = scope_issuer.issue_scope(request=parent_auth_req, max_invocations=10, ttl_seconds=1200)
        print(f"Issued Root Parent Scope for planner-01: {parent_scope.scope_id} [depth=2, max_calls=10]")

        # ======================================================================
        # PHASE 1: Agent A delegates an allowed capability to Agent B
        # ======================================================================
        print_subbanner("Phase 1: Agent A delegates an allowed capability to Agent B")
        del_req_1 = DelegationRequest(
            caller_identity_token=token_a.raw_token,
            parent_scope_token=parent_scope.raw_token,
            target_agent_id="researcher-27",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/*",
            requested_max_invocations=5,
            requested_delegation_depth=1,
            environment="staging",
        )
        res_1 = comm_mgr.delegate(del_req_1)
        print(f"Delegation Result: {res_1.verdict.value} - {res_1.reason}")
        assert res_1.verdict == DelegationVerdict.ALLOWED
        child_scope_b = res_1.child_scope
        assert child_scope_b is not None
        assert child_scope_b.child_subject == agent_b.identity_subject
        assert child_scope_b.delegated_by == agent_a.identity_subject
        results["phases"]["phase_1_delegation"] = {"status": "PASSED", "child_scope_id": child_scope_b.scope_id}
        print("  [SUCCESS] Phase 1: Delegation succeeded with valid provenance.")

        # ======================================================================
        # PHASE 2: Child scope is proven to be a subset of parent scope
        # ======================================================================
        print_subbanner("Phase 2: Child scope is proven to be a subset of parent scope")
        # Invariant checks:
        assert child_scope_b.capability == parent_scope.capability, "Capability must match parent"
        assert set(child_scope_b.allowed_actions).issubset(set(parent_scope.allowed_actions)), "Actions must be subset"
        assert child_scope_b.max_invocations <= parent_scope.max_invocations, "Quota must be <= parent quota"
        assert child_scope_b.remaining_delegation_depth == 1, "Delegation depth must be decremented to 1"
        assert child_scope_b.expires_at <= parent_scope.expires_at, "TTL must not exceed parent expiration"
        # Resource path containment check
        assert child_scope_b.resource_pattern.startswith(parent_scope.resource_pattern.rstrip("*")), "Path must be subpattern"
        print(f"  Parent: cap={parent_scope.capability}, res={parent_scope.resource_pattern}, calls={parent_scope.max_invocations}, depth={parent_scope.claims.get('delegation_depth')}")
        print(f"  Child:  cap={child_scope_b.capability}, res={child_scope_b.resource_pattern}, calls={child_scope_b.max_invocations}, depth={child_scope_b.remaining_delegation_depth}")
        results["phases"]["phase_2_subset_proven"] = {"status": "PASSED", "subset_invariant": "VERIFIED"}
        print("  [SUCCESS] Phase 2: Child Scope ⊆ Parent Scope mathematically verified.")

        # ======================================================================
        # PHASE 3: Agent B attempts capability escalation
        # ======================================================================
        print_subbanner("Phase 3: Agent B attempts capability escalation (DENIED)")
        esc_req = DelegationRequest(
            caller_identity_token=token_b.raw_token,
            parent_scope_token=child_scope_b.raw_token,
            target_agent_id="document-agent-42",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
            requested_capability="prod_deploy",  # ESCALATION!
            requested_action="deploy",
            requested_resource="/workspace/research/*",
        )
        res_esc = comm_mgr.delegate(esc_req)
        print(f"  Outcome: {res_esc.verdict.value} - {res_esc.reason}")
        assert res_esc.verdict == DelegationVerdict.DENIED
        assert "Capability escalation denied" in res_esc.reason
        results["phases"]["phase_3_capability_escalation"] = {"status": "PASSED", "denied_as_expected": True}
        print("  [SUCCESS] Phase 3: Capability escalation successfully blocked.")

        # ======================================================================
        # PHASE 4: Agent B attempts resource/path escalation
        # ======================================================================
        print_subbanner("Phase 4: Agent B attempts resource/path escalation (DENIED)")
        esc_path_req = DelegationRequest(
            caller_identity_token=token_b.raw_token,
            parent_scope_token=child_scope_b.raw_token,
            target_agent_id="document-agent-42",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/finance/payroll/*",  # ESCALATION outside sources/*!
        )
        res_path_esc = comm_mgr.delegate(esc_path_req)
        print(f"  Outcome: {res_path_esc.verdict.value} - {res_path_esc.reason}")
        assert res_path_esc.verdict == DelegationVerdict.DENIED
        assert "Resource escalation denied" in res_path_esc.reason
        results["phases"]["phase_4_resource_escalation"] = {"status": "PASSED", "denied_as_expected": True}
        print("  [SUCCESS] Phase 4: Resource path escalation successfully blocked.")

        # ======================================================================
        # PHASE 5: Agent B attempts cross-task delegation
        # ======================================================================
        print_subbanner("Phase 5: Agent B attempts cross-task delegation (DENIED)")
        cross_task_req = DelegationRequest(
            caller_identity_token=token_b.raw_token,
            parent_scope_token=child_scope_b.raw_token,
            target_agent_id="document-agent-42",
            task_id="T-TAMPERED-TASK-999",  # Cross-task injection!
            workspace_id=WORKSPACE_ID,
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/*",
        )
        res_cross_task = comm_mgr.delegate(cross_task_req)
        print(f"  Outcome: {res_cross_task.verdict.value} - {res_cross_task.reason}")
        assert res_cross_task.verdict == DelegationVerdict.DENIED
        results["phases"]["phase_5_cross_task"] = {"status": "PASSED", "denied_as_expected": True}
        print("  [SUCCESS] Phase 5: Cross-task delegation successfully blocked.")

        # ======================================================================
        # PHASE 6: Agent B attempts cross-tenant delegation
        # ======================================================================
        print_subbanner("Phase 6: Agent B attempts cross-tenant delegation (DENIED)")
        cross_tenant_req = DelegationRequest(
            caller_identity_token=token_b.raw_token,
            parent_scope_token=child_scope_b.raw_token,
            target_agent_id="rival-spy-007",  # In rival-corp tenant!
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/*",
        )
        res_cross_tenant = comm_mgr.delegate(cross_tenant_req)
        print(f"  Outcome: {res_cross_tenant.verdict.value} - {res_cross_tenant.reason}")
        assert res_cross_tenant.verdict == DelegationVerdict.DENIED
        assert "Cross-tenant delegation denied" in res_cross_tenant.reason
        results["phases"]["phase_6_cross_tenant"] = {"status": "PASSED", "denied_as_expected": True}
        print("  [SUCCESS] Phase 6: Cross-tenant delegation successfully blocked.")

        # ======================================================================
        # PHASE 7: Delegation depth reaches zero
        # ======================================================================
        print_subbanner("Phase 7: Delegation depth reaches zero (DENIED)")
        # 1. Agent B legitimately delegates to Agent C with remaining depth = 0
        del_req_2 = DelegationRequest(
            caller_identity_token=token_b.raw_token,
            parent_scope_token=child_scope_b.raw_token,
            target_agent_id="document-agent-42",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/pdf/*",
            requested_max_invocations=2,
            requested_delegation_depth=0,
            environment="staging",
        )
        res_2 = comm_mgr.delegate(del_req_2)
        print(f"  Hop 2 (B -> C, depth=0): {res_2.verdict.value} - {res_2.reason}")
        assert res_2.verdict == DelegationVerdict.ALLOWED
        child_scope_c = res_2.child_scope
        assert child_scope_c is not None
        assert child_scope_c.remaining_delegation_depth == 0

        # 2. Agent C attempts to delegate further (hop 3) with depth=0
        agent_d = registry.register_agent(
            agent_id="sub-agent-04",
            role="reviewer-agent",
            tenant="acme",
            environment="staging",
            capabilities=["document_analysis"],
        )
        _, token_d = id_mgr.provision_agent_identity(
            agent_id="sub-agent-04",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
        )
        del_req_3 = DelegationRequest(
            caller_identity_token=token_c.raw_token,
            parent_scope_token=child_scope_c.raw_token,
            target_agent_id="sub-agent-04",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/pdf/*",
        )
        res_3 = comm_mgr.delegate(del_req_3)
        print(f"  Hop 3 (C -> D, exhausted depth): {res_3.verdict.value} - {res_3.reason}")
        assert res_3.verdict == DelegationVerdict.DENIED
        assert "Delegation depth exhausted" in res_3.reason
        results["phases"]["phase_7_depth_zero"] = {"status": "PASSED", "denied_as_expected": True}
        print("  [SUCCESS] Phase 7: Delegation depth limit strictly enforced.")

        # ======================================================================
        # PHASE 8: Expired/revoked parent scope invalidates delegation
        # ======================================================================
        print_subbanner("Phase 8: Expired/revoked parent scope invalidates delegation (DENIED)")
        # Revoke the root parent scope
        scope_issuer.revoke_scope(parent_scope.scope_id)
        print(f"  Revoked Root Parent Scope: {parent_scope.scope_id}")

        # Attempt invocation through gateway using child_scope_b (derived from revoked parent)
        dec_revoked = gateway.authorize_invocation(
            identity_token=token_b.raw_token,
            scope_token=child_scope_b.raw_token,
            action="read",
            resource="/workspace/research/sources/doc.txt",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
        )
        print(f"  Gateway with Revoked Parent Scope: Allowed={dec_revoked.allowed} - {dec_revoked.reason}")
        assert dec_revoked.allowed is False
        assert "revoked" in dec_revoked.reason.lower()
        results["phases"]["phase_8_revocation"] = {"status": "PASSED", "revocation_cascade_enforced": True}
        print("  [SUCCESS] Phase 8: Revocation cascade invalidated delegated child scope.")

        # ======================================================================
        # PHASE 9: Full multi-hop delegation chain is reconstructed from audit
        # ======================================================================
        print_subbanner("Phase 9: Full multi-hop delegation chain is reconstructed from audit")
        # Inspect child_scope_c provenance chain
        chain = child_scope_c.delegation_chain
        print(f"  Child Scope C Provenance Chain: {' -> '.join(chain)}")
        expected_chain = [agent_a.identity_subject, agent_b.identity_subject, agent_c.identity_subject]
        assert chain == expected_chain, f"Expected {expected_chain}, got {chain}"
        assert child_scope_c.original_subject == agent_a.identity_subject
        assert child_scope_c.delegated_by == agent_b.identity_subject
        assert child_scope_c.child_subject == agent_c.identity_subject

        # Query SQLite audit logs for delegation provenance
        audit_events = store.list_audit_events(limit=50)
        delegation_events = [e for e in audit_events if e.actor == "delegation-engine"]
        print(f"  Found {len(delegation_events)} persistent delegation audit events in SQLite store.")
        assert len(delegation_events) >= 2
        results["phases"]["phase_9_audit_chain"] = {
            "status": "PASSED",
            "provenance_chain": chain,
            "audit_records_count": len(delegation_events),
        }
        print("  [SUCCESS] Phase 9: Multi-hop provenance chain verified from storage.")

        # ======================================================================
        # PHASE 10: Gateway blocks every invalid delegation fail-closed
        # ======================================================================
        print_subbanner("Phase 10: Gateway blocks every invalid delegation fail-closed")
        # Vector A: Token theft (Agent A tries to use Agent C's scope token)
        dec_theft = gateway.authorize_invocation(
            identity_token=token_a.raw_token,
            scope_token=child_scope_c.raw_token,
            action="read",
            resource="/workspace/research/sources/pdf/report.pdf",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
        )
        print(f"  Vector A (Scope Theft): Allowed={dec_theft.allowed} - {dec_theft.reason}")
        assert dec_theft.allowed is False

        # Vector B: Resource escape at gateway (Agent C attempts to read outside bounded subpattern)
        # Mint fresh valid unrevoked parent and child for Agent C
        fresh_parent = scope_issuer.issue_scope(request=parent_auth_req, max_invocations=5)
        fresh_del = comm_mgr.delegate(DelegationRequest(
            caller_identity_token=token_a.raw_token,
            parent_scope_token=fresh_parent.raw_token,
            target_agent_id="document-agent-42",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
            requested_capability="document_analysis",
            requested_action="read",
            requested_resource="/workspace/research/sources/pdf/*",
            requested_max_invocations=3,
            requested_delegation_depth=0,
            environment="staging",
        ))
        fresh_child = fresh_del.child_scope
        assert fresh_child is not None

        dec_escape = gateway.authorize_invocation(
            identity_token=token_c.raw_token,
            scope_token=fresh_child.raw_token,
            action="read",
            resource="/workspace/research/other.txt",  # Escapes /workspace/research/sources/pdf/*
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
        )
        print(f"  Vector B (Resource Escape): Allowed={dec_escape.allowed} - {dec_escape.reason}")
        assert dec_escape.allowed is False

        # Vector C: Valid invocation succeeds and consumes quota
        dec_valid = gateway.authorize_invocation(
            identity_token=token_c.raw_token,
            scope_token=fresh_child.raw_token,
            action="read",
            resource="/workspace/research/sources/pdf/paper.pdf",
            task_id=TASK_ID,
            workspace_id=WORKSPACE_ID,
        )
        print(f"  Vector C (Valid Authorized): Allowed={dec_valid.allowed} - Quota Left: {dec_valid.invocations_remaining}")
        assert dec_valid.allowed is True
        assert dec_valid.invocations_remaining == 2
        assert dec_valid.delegation_chain == [agent_a.identity_subject, agent_c.identity_subject]

        results["phases"]["phase_10_gateway_enforcement"] = {
            "status": "PASSED",
            "fail_closed_theft_blocked": True,
            "fail_closed_escape_blocked": True,
            "valid_invocation_authorized": True,
        }
        print("  [SUCCESS] Phase 10: Gateway verified as tamper-proof fail-closed enforcement point.")

        results["overall_status"] = "PASSED"
        print_banner("EXPERIMENT 005 COMPLETED: 100% SUCCESS ACROSS ALL 10 PHASES")

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
