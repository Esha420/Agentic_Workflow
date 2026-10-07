"""
experiments/006-checkpoint-branching/run_branching_experiment.py
Investigates and verifies Milestone 6: Checkpoint Branching

Core Invariants Tested:
1. Every branch must have an immutable parent checkpoint.
2. Independent branch identity and preserved provenance.
3. Core Security Invariant: Branch Authorization ⊆ Source Authorization.
4. Workspace & state isolation (zero cross-contamination).
5. Accurate lineage DAG reconstruction (C1 -> {C2A, C2B}).
"""
from __future__ import annotations
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import uuid
import jwt

# Add workspace root to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from domain.agents.models import Agent, AgentLifecycleState
from domain.checkpoints.branching import BranchRequest, BranchStatus
from domain.checkpoints.models import Checkpoint
from domain.sessions.models import ResearchSession, SessionStatus
from services.agents.registry import AgentRegistryService
from services.checkpoints.branching import (
    BranchEscalationDenied,
    BranchingError,
    CheckpointBranchingController,
)
from services.identity.manager import IdentityManager
from services.policy.capabilities import CapabilityRegistry
from services.policy.scope_issuer import ScopeIssuer
from adapters.storage.metadata_store import SQLiteMetadataStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("exp-006")


def run_experiment() -> Dict[str, Any]:
    print("=" * 80)
    print("EXPERIMENT 006: CHECKPOINT BRANCHING & STATE ISOLATION INVESTIGATION")
    print("Core Invariant: Branch Authorization ⊆ Source Authorization")
    print("=" * 80)

    # Isolated test environment
    exp_dir = os.path.join(BASE_DIR, "experiments", "006-checkpoint-branching")
    scratch_dir = tempfile.mkdtemp(prefix="agent_lab_exp006_")
    db_path = os.path.join(scratch_dir, "exp006.db")
    ws_base_dir = os.path.join(scratch_dir, "workspaces")
    os.makedirs(ws_base_dir, exist_ok=True)

    store = SQLiteMetadataStore(db_path=db_path)
    registry = AgentRegistryService(store)
    identity_mgr = IdentityManager(registry=registry, metadata_store=store)
    capabilities = CapabilityRegistry()
    secret_key = "exp006-secret-key-branching-invariant-2026"
    scope_issuer = ScopeIssuer(secret_key=secret_key)

    controller = CheckpointBranchingController(
        metadata_store=store,
        agent_registry=registry,
        identity_manager=identity_mgr,
        capability_registry=capabilities,
        scope_issuer=scope_issuer,
        secret_key=secret_key,
        workspace_base_dir=ws_base_dir,
    )

    results: Dict[str, Any] = {
        "experiment_id": "EXP-006-CHECKPOINT-BRANCHING",
        "milestone": "Milestone 6 (Checkpoint Branching)",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phases": {},
        "all_passed": False,
    }

    try:
        # ======================================================================
        # PHASE 1: Create Baseline Session & Immutable Checkpoint C1
        # ======================================================================
        print("\n--- PHASE 1: Baseline Session & Immutable Parent Checkpoint C1 ---")
        session_id = f"RS-EXP006-{uuid.uuid4().hex[:6]}"
        session = ResearchSession(
            id=session_id,
            objective="Autonomous Architecture Benchmarking",
            target="State Forking & Branch Lineage",
            role="lead-researcher",
            status=SessionStatus.RUNNING,
        )
        store.save_session(session)

        # Baseline researcher
        root_agent = registry.register_agent(
            agent_id="researcher-root",
            role="lead-researcher",
            tenant="acme-corp",
            environment="production",
            capabilities=["document_analysis", "web_research"],
            identity_subject="agent:researcher-root",
        )
        root_agent.task_id = f"T-root-{session_id}"
        root_agent.workspace_id = f"ws-{session_id}"
        root_agent.session_id = session_id
        root_agent.lifecycle_state = AgentLifecycleState.ACTIVE
        store.save_agent(root_agent)

        _, root_identity = identity_mgr.provision_agent_identity(
            agent_id=root_agent.agent_id,
            task_id=root_agent.task_id,
            workspace_id=root_agent.workspace_id,
            session_id=session_id,
        )

        # Setup root workspace with baseline data
        root_ws_dir = os.path.join(ws_base_dir, f"ws-{session_id}")
        os.makedirs(root_ws_dir, exist_ok=True)
        with open(os.path.join(root_ws_dir, "baseline_hypothesis.md"), "w") as f:
            f.write("# Baseline Hypothesis\nCore initial hypothesis state before branching.\n")
        with open(os.path.join(root_ws_dir, "baseline_data.json"), "w") as f:
            json.dump({"samples": 1000, "baseline_loss": 0.42}, f)

        # Commit parent Checkpoint C1
        c1 = Checkpoint(
            id="chk-root-c1",
            session_id=session_id,
            task_id=root_agent.task_id,
            workspace_version="v1",
            workspace_generation=1,
            snapshot_reference=f"snapshot-ref://rustfs/{session_id}/chk-root-c1",
            metadata={"phase": "baseline_established"},
        )
        store.save_checkpoint(c1)

        # Root scope token (M4)
        now = int(time.time())
        root_scope_claims = {
            "scope_id": "scp-root-c1",
            "sub": root_agent.identity_subject,
            "task_id": root_agent.task_id,
            "workspace_id": root_agent.workspace_id,
            "capability": "document_analysis",
            "granted_action": "read",
            "allowed_actions": ["read"],
            "resource_path": "/workspace/research/*",
            "resource_pattern": "/workspace/research/*",
            "max_invocations": 20,
            "invocations_remaining": 20,
            "delegation_depth": 2,
            "iat": now,
            "exp": now + 7200,
            "iss": "https://scope.agent-lab.internal",
            "aud": "agent-gateway",
            "role": "lead-researcher",
            "environment": "production",
        }
        root_scope_jwt = jwt.encode(root_scope_claims, secret_key, algorithm="HS256")

        print(f"  [OK] Session '{session_id}' created with root agent '{root_agent.agent_id}'")
        print(f"  [OK] Immutable Checkpoint '{c1.id}' saved (Generation 1)")
        results["phases"]["phase_1_baseline_checkpoint"] = {
            "status": "PASSED",
            "session_id": session_id,
            "checkpoint_id": c1.id,
            "generation": 1,
        }

        # ======================================================================
        # PHASE 2: Dual Branch Creation from C1
        # ======================================================================
        print("\n--- PHASE 2: Dual Branch Creation from Checkpoint C1 ---")
        # Branch A: Hypothesis A
        req_a = BranchRequest(
            parent_checkpoint_id=c1.id,
            caller_identity_token=root_identity.raw_token,
            source_scope_token=root_scope_jwt,
            hypothesis="Hypothesis A: Fast statistical sampling approach",
            branch_name="branch-A-sampling",
            requested_capabilities=["document_analysis"],
            requested_actions=["read"],
            requested_resources=["/workspace/research/sampling/*"],
            max_invocations=8,
            requested_ttl=3600,
        )
        branch_a = controller.create_branch(req_a)

        # Branch B: Hypothesis B
        req_b = BranchRequest(
            parent_checkpoint_id=c1.id,
            caller_identity_token=root_identity.raw_token,
            source_scope_token=root_scope_jwt,
            hypothesis="Hypothesis B: Deep semantic verification approach",
            branch_name="branch-B-semantic",
            requested_capabilities=["document_analysis"],
            requested_actions=["read"],
            requested_resources=["/workspace/research/semantic/*"],
            max_invocations=12,
            requested_ttl=3600,
        )
        branch_b = controller.create_branch(req_b)

        print(f"  [OK] Branch A created: ID={branch_a.branch_id}, Gen={branch_a.workspace_generation}, Agent={branch_a.agent_id}")
        print(f"  [OK] Branch B created: ID={branch_b.branch_id}, Gen={branch_b.workspace_generation}, Agent={branch_b.agent_id}")
        assert branch_a.workspace_generation == 2
        assert branch_b.workspace_generation == 2
        assert branch_a.parent_checkpoint_id == c1.id
        assert branch_b.parent_checkpoint_id == c1.id
        results["phases"]["phase_2_dual_branch_creation"] = {
            "status": "PASSED",
            "branch_a": branch_a.branch_id,
            "branch_b": branch_b.branch_id,
            "generation": 2,
        }

        # ======================================================================
        # PHASE 3: Mathematical Invariant: Branch Authorization ⊆ Source Authorization
        # ======================================================================
        print("\n--- PHASE 3: Verify Branch Authorization ⊆ Source Authorization ---")
        scope_a_jwt = branch_a.metadata["scope_token"]
        claims_a = jwt.decode(scope_a_jwt, secret_key, algorithms=["HS256"], options={"verify_aud": False})

        # Capability containment
        assert claims_a["capability"] == root_scope_claims["capability"]
        # Action containment
        assert claims_a["granted_action"] in root_scope_claims["allowed_actions"]
        # Resource path containment (subpattern)
        assert controller._is_subpattern(claims_a["resource_path"], root_scope_claims["resource_path"])
        # Quota containment
        assert claims_a["max_invocations"] <= root_scope_claims["max_invocations"]
        # TTL containment
        assert claims_a["exp"] <= root_scope_claims["exp"]

        print(f"  [OK] Capability Containment: '{claims_a['capability']}' == '{root_scope_claims['capability']}'")
        print(f"  [OK] Action Containment: '{claims_a['granted_action']}' in {root_scope_claims['allowed_actions']}")
        print(f"  [OK] Resource Containment: '{claims_a['resource_path']}' ⊆ '{root_scope_claims['resource_path']}'")
        print(f"  [OK] Quota Containment: {claims_a['max_invocations']} <= {root_scope_claims['max_invocations']}")
        print(f"  [OK] TTL Containment: {claims_a['exp']} <= {root_scope_claims['exp']}")
        results["phases"]["phase_3_invariant_containment"] = {"status": "PASSED"}

        # ======================================================================
        # PHASE 4: Adversarial Test: Capability Escalation Denied
        # ======================================================================
        print("\n--- PHASE 4: Adversarial Test: Capability Escalation Blocked ---")
        req_esc_cap = BranchRequest(
            parent_checkpoint_id=c1.id,
            caller_identity_token=root_identity.raw_token,
            source_scope_token=root_scope_jwt,
            hypothesis="Attempting unauthorized prod_deploy on new branch",
            requested_capabilities=["prod_deploy"],
        )
        try:
            controller.create_branch(req_esc_cap)
            print("  [FAIL] Capability escalation was unexpectedly ALLOWED!")
            sys.exit(1)
        except BranchEscalationDenied as e:
            print(f"  [OK] Capability escalation blocked fail-closed: {e}")
            results["phases"]["phase_4_capability_escalation_denied"] = {
                "status": "PASSED",
                "reason": str(e),
            }

        # ======================================================================
        # PHASE 5: Adversarial Test: Resource Path Escape Denied
        # ======================================================================
        print("\n--- PHASE 5: Adversarial Test: Resource Path Escape Blocked ---")
        req_esc_res = BranchRequest(
            parent_checkpoint_id=c1.id,
            caller_identity_token=root_identity.raw_token,
            source_scope_token=root_scope_jwt,
            hypothesis="Attempting path traversal escape to financial payroll",
            requested_resources=["/workspace/finance/payroll/*"],
        )
        try:
            controller.create_branch(req_esc_res)
            print("  [FAIL] Resource path escape was unexpectedly ALLOWED!")
            sys.exit(1)
        except BranchEscalationDenied as e:
            print(f"  [OK] Resource path escape blocked fail-closed: {e}")
            results["phases"]["phase_5_resource_escape_denied"] = {
                "status": "PASSED",
                "reason": str(e),
            }

        # ======================================================================
        # PHASE 6: Independent Branch Workload Identity Verification
        # ======================================================================
        print("\n--- PHASE 6: Independent Branch Workload Identity ---")
        agent_a = registry.get_agent(branch_a.agent_id)
        agent_b = registry.get_agent(branch_b.agent_id)
        assert agent_a is not None and agent_b is not None
        assert agent_a.agent_id != agent_b.agent_id
        assert agent_a.identity_subject != agent_b.identity_subject
        assert branch_a.task_id != branch_b.task_id
        assert branch_a.workspace_id != branch_b.workspace_id

        # Verify identity tokens validate correctly
        id_a_tok = branch_a.metadata["identity_token"]
        id_b_tok = branch_b.metadata["identity_token"]
        val_a = identity_mgr.provider.validate_identity(id_a_tok)
        val_b = identity_mgr.provider.validate_identity(id_b_tok)
        assert val_a.valid and val_b.valid
        assert val_a.subject == agent_a.identity_subject
        assert val_b.subject == agent_b.identity_subject

        print(f"  [OK] Branch A Subject: '{agent_a.identity_subject}', Task: '{branch_a.task_id}'")
        print(f"  [OK] Branch B Subject: '{agent_b.identity_subject}', Task: '{branch_b.task_id}'")
        print(f"  [OK] Cryptographic identity validation successful without subject collision")
        results["phases"]["phase_6_independent_identity"] = {
            "status": "PASSED",
            "subject_a": agent_a.identity_subject,
            "subject_b": agent_b.identity_subject,
        }

        # ======================================================================
        # PHASE 7: Durable State & Workspace Isolation (Zero Cross-Contamination)
        # ======================================================================
        print("\n--- PHASE 7: Workspace State Isolation & Divergence ---")
        ws_a_path = os.path.join(ws_base_dir, branch_a.workspace_id)
        ws_b_path = os.path.join(ws_base_dir, branch_b.workspace_id)

        # Confirm initial state cloned from parent
        assert os.path.exists(os.path.join(ws_a_path, "baseline_hypothesis.md"))
        assert os.path.exists(os.path.join(ws_b_path, "baseline_hypothesis.md"))

        # Mutate Branch A
        res_a_file = os.path.join(ws_a_path, "sampling_findings.json")
        with open(res_a_file, "w") as f:
            json.dump({"branch": "A", "speedup": "4.2x", "accuracy": 0.91}, f)

        # Mutate Branch B
        res_b_file = os.path.join(ws_b_path, "semantic_findings.json")
        with open(res_b_file, "w") as f:
            json.dump({"branch": "B", "speedup": "1.1x", "accuracy": 0.994}, f)

        # Verify isolation: File A not in B, File B not in A
        assert not os.path.exists(os.path.join(ws_b_path, "sampling_findings.json"))
        assert not os.path.exists(os.path.join(ws_a_path, "semantic_findings.json"))

        print(f"  [OK] Branch A wrote 'sampling_findings.json' -> completely absent in Branch B")
        print(f"  [OK] Branch B wrote 'semantic_findings.json' -> completely absent in Branch A")
        print(f"  [OK] Zero workspace cross-contamination verified across independent branches")
        results["phases"]["phase_7_workspace_isolation"] = {"status": "PASSED"}

        # ======================================================================
        # PHASE 8: Parent Checkpoint Immutability Verification
        # ======================================================================
        print("\n--- PHASE 8: Parent Checkpoint Immutability Verification ---")
        # Ensure root workspace was not contaminated by branch writes
        assert not os.path.exists(os.path.join(root_ws_dir, "sampling_findings.json"))
        assert not os.path.exists(os.path.join(root_ws_dir, "semantic_findings.json"))

        # Ensure Checkpoint C1 in store is unchanged
        c1_refreshed = store.get_checkpoint(c1.id)
        assert c1_refreshed is not None
        assert c1_refreshed.workspace_generation == 1
        assert c1_refreshed.id == "chk-root-c1"
        assert c1_refreshed.parent_checkpoint_id is None

        print(f"  [OK] Parent Checkpoint '{c1.id}' remains 100% immutable (Gen 1)")
        print(f"  [OK] Root workspace unmodified by downstream branch mutations")
        results["phases"]["phase_8_parent_immutability"] = {"status": "PASSED"}

        # ======================================================================
        # PHASE 9: Commit Branch Checkpoints C2A and C2B
        # ======================================================================
        print("\n--- PHASE 9: Commit Checkpoints from Divergent Branches ---")
        chk_2a = controller.commit_branch_checkpoint(
            branch_id=branch_a.branch_id,
            checkpoint_data={
                "id": "chk-branch-a-c2",
                "metadata": {"sampling_complete": True, "final_score": 0.91},
            },
        )
        chk_2b = controller.commit_branch_checkpoint(
            branch_id=branch_b.branch_id,
            checkpoint_data={
                "id": "chk-branch-b-c2",
                "metadata": {"semantic_complete": True, "final_score": 0.994},
            },
        )

        assert chk_2a.parent_checkpoint_id == c1.id
        assert chk_2a.branch_id == branch_a.branch_id
        assert chk_2a.workspace_generation == 2
        assert chk_2b.parent_checkpoint_id == c1.id
        assert chk_2b.branch_id == branch_b.branch_id
        assert chk_2b.workspace_generation == 2

        print(f"  [OK] Checkpoint C2A committed: ID={chk_2a.id}, Parent={chk_2a.parent_checkpoint_id}, Gen=2")
        print(f"  [OK] Checkpoint C2B committed: ID={chk_2b.id}, Parent={chk_2b.parent_checkpoint_id}, Gen=2")
        results["phases"]["phase_9_commit_branch_checkpoints"] = {
            "status": "PASSED",
            "checkpoint_c2a": chk_2a.id,
            "checkpoint_c2b": chk_2b.id,
        }

        # ======================================================================
        # PHASE 10: Reconstruct Full Lineage DAG & Audit Provenance
        # ======================================================================
        print("\n--- PHASE 10: Full Lineage DAG & Audit Provenance Reconstruction ---")
        lineage = controller.get_lineage(session_id)
        assert lineage.total_checkpoints == 3  # C1, C2A, C2B
        assert lineage.total_branches == 2     # Branch A, Branch B

        dag = lineage.lineage_dag
        print(f"  [OK] Reconstructed Lineage DAG:")
        for node, edges in dag.items():
            print(f"       Node [{node}] -> Children: {edges}")

        assert c1.id in dag
        assert branch_a.branch_id in dag[c1.id] or chk_2a.id in dag[c1.id]
        assert branch_b.branch_id in dag[c1.id] or chk_2b.id in dag[c1.id]

        # Verify Audit Log
        audit_events = store.list_audit_events(session_id=session_id)
        assert len(audit_events) >= 4  # branch_a created, branch_b created, 2 checkpoints committed
        print(f"  [OK] Verified {len(audit_events)} audit events recorded in immutable SQLite ledger")

        results["phases"]["phase_10_lineage_and_audit"] = {
            "status": "PASSED",
            "total_checkpoints": lineage.total_checkpoints,
            "total_branches": lineage.total_branches,
            "lineage_dag": dag,
            "audit_event_count": len(audit_events),
        }

        results["all_passed"] = True
        print("\n" + "=" * 80)
        print("EXPERIMENT 006: ALL 10 PHASES PASSED WITH 100% SUCCESS")
        print("Invariant Verified: Branch Authorization ⊆ Source Authorization")
        print("State Lineage Verified: C1 -> {C2A, C2B}")
        print("=" * 80)

    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    # Save summary json
    summary_path = os.path.join(exp_dir, "experiment_summary.json")
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == "__main__":
    res = run_experiment()
    if not res["all_passed"]:
        sys.exit(1)
