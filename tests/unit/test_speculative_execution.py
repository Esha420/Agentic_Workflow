"""
tests/unit/test_speculative_execution.py — Unit tests for Milestone 7: Speculative Execution & Promotion
Verifies:
1. Multi-dimensional evaluation matrix computation and explicit scoring weights.
2. Strict policy violation disqualification (zero tolerance).
3. Concurrent branch execution and state isolation.
4. Highest-ranked branch auto-promotion to Primary HEAD.
5. Invariant: Promotion changes the active state reference, NOT historical DAG truth.
6. Promotion idempotency.
"""
import os
import shutil
import tempfile
import time
import unittest
import uuid

from domain.agents.models import Agent
from domain.checkpoints.branching import BranchRequest
from domain.checkpoints.models import Checkpoint
from domain.sessions.models import ResearchSession, SessionStatus
from domain.speculative.models import (
    BranchEvaluation,
    EvaluationDimension,
    EvaluationMatrix,
    PromotionResult,
    ScoringConfig,
)
from services.agents.registry import AgentRegistryService
from services.checkpoints.branching import CheckpointBranchingController
from services.identity.manager import IdentityManager
from services.policy.capabilities import CapabilityRegistry
from services.policy.scope_issuer import ScopeIssuer
from services.speculative.controller import SpeculativeExecutionController
from services.speculative.evaluator import MultiDimensionalEvaluator
from services.speculative.promoter import BranchPromotionController, PromotionError
from adapters.storage.metadata_store import SQLiteMetadataStore


class TestSpeculativeExecution(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, f"test_spec_{uuid.uuid4().hex[:6]}.db")
        self.workspace_base = os.path.join(self.tmp_dir, "workspaces")
        os.makedirs(self.workspace_base, exist_ok=True)

        self.store = SQLiteMetadataStore(db_path=self.db_path)
        self.registry = AgentRegistryService(self.store)
        self.identity_mgr = IdentityManager(registry=self.registry, metadata_store=self.store)
        self.capabilities = CapabilityRegistry()
        self.scope_issuer = ScopeIssuer()
        self.secret_key = "test-secret-spec-m7"
        self.scope_issuer.secret_key = self.secret_key

        self.branching_controller = CheckpointBranchingController(
            metadata_store=self.store,
            agent_registry=self.registry,
            identity_manager=self.identity_mgr,
            capability_registry=self.capabilities,
            scope_issuer=self.scope_issuer,
            secret_key=self.secret_key,
            workspace_base_dir=self.workspace_base,
        )

        self.evaluator = MultiDimensionalEvaluator(self.store)
        self.promoter = BranchPromotionController(self.store)
        self.speculative_controller = SpeculativeExecutionController(
            branching_controller=self.branching_controller,
            evaluator=self.evaluator,
            promoter=self.promoter,
            metadata_store=self.store,
        )

        # Baseline Session, Agent, Checkpoint
        self.session_id = f"RS-SPEC-{uuid.uuid4().hex[:6]}"
        self.session = ResearchSession(
            id=self.session_id,
            objective="Consensus Mechanism Comparison",
            target="Speculative Branching & Automated Promotion",
            role="lead-analyst",
            status=SessionStatus.RUNNING,
        )
        self.store.save_session(self.session)

        self.agent = self.registry.register_agent(
            agent_id="analyst-lead",
            role="lead-analyst",
            tenant="acme",
            environment="production",
            capabilities=["document_analysis", "web_research", "code_generation"],
            identity_subject="agent:analyst-lead",
        )
        self.agent.task_id = "task-001"
        self.agent.workspace_id = f"ws-{self.session_id}"
        self.agent.lifecycle_state = "ACTIVE"
        self.agent.session_id = self.session_id

        _, self.id_token = self.identity_mgr.provision_agent_identity(
            agent_id=self.agent.agent_id,
            task_id="task-001",
            workspace_id=f"ws-{self.session_id}",
            session_id=self.session_id,
        )

        now = int(time.time())
        scope_claims = {
            "scope_id": "scp-parent-c1",
            "sub": self.agent.identity_subject,
            "task_id": "task-001",
            "workspace_id": f"ws-{self.session_id}",
            "capability": "document_analysis",
            "granted_action": "read",
            "allowed_actions": ["read", "query", "summarize"],
            "resource_path": "/workspace/research/*",
            "resource_pattern": "/workspace/research/*",
            "max_invocations": 10,
            "invocations_remaining": 10,
            "delegation_depth": 3,
            "iat": now,
            "exp": now + 3600,
            "iss": "https://scope.agent-lab.internal",
            "aud": "agent-gateway",
            "role": "lead-analyst",
            "environment": "production",
        }
        import jwt
        self.scope_token_str = jwt.encode(scope_claims, self.secret_key, algorithm="HS256")

        # Setup root workspace dir
        root_ws_dir = os.path.join(self.workspace_base, f"ws-{self.session_id}")
        os.makedirs(root_ws_dir, exist_ok=True)
        with open(os.path.join(root_ws_dir, "notes.md"), "w") as f:
            f.write("# Baseline Notes\nInitial findings.")

        # Baseline Checkpoint C1
        self.baseline_checkpoint = Checkpoint(
            id=f"chk-base-{uuid.uuid4().hex[:6]}",
            session_id=self.session_id,
            task_id="task-001",
            workspace_version="v-base-001",
            metadata={"description": "Baseline state before speculative hypotheses"},
        )
        self.store.save_checkpoint(self.baseline_checkpoint)
        self.store.set_session_head(self.session_id, self.baseline_checkpoint.id)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_multi_dimensional_scoring_formula(self):
        """Validates that ScoringConfig computes weighted score deterministically."""
        config = ScoringConfig(
            w_correctness=0.25,
            w_evidence=0.25,
            w_completeness=0.20,
            w_efficiency=0.15,
            w_reliability=0.10,
            w_reproducibility=0.05,
        )

        scores = {
            EvaluationDimension.CORRECTNESS.value: 0.90,
            EvaluationDimension.EVIDENCE.value: 0.80,
            EvaluationDimension.COMPLETENESS.value: 0.85,
            EvaluationDimension.EFFICIENCY.value: 0.70,
            EvaluationDimension.RELIABILITY.value: 1.00,
            EvaluationDimension.REPRODUCIBILITY.value: 0.90,
            EvaluationDimension.POLICY_COMPLIANCE.value: 1.00,
        }

        # Expected: 0.90*0.25 + 0.80*0.25 + 0.85*0.20 + 0.70*0.15 + 1.00*0.10 + 0.90*0.05
        # = 0.225 + 0.200 + 0.170 + 0.105 + 0.100 + 0.045 = 0.845
        computed, disq, reason = config.compute_score(scores)
        self.assertFalse(disq)
        self.assertAlmostEqual(computed, 0.845, places=3)

    def test_strict_policy_violation_disqualification(self):
        """Validates that a policy violation immediately disqualifies a branch to score 0.00."""
        config = ScoringConfig(require_strict_compliance=True)
        scores = {
            EvaluationDimension.CORRECTNESS.value: 0.99,
            EvaluationDimension.EVIDENCE.value: 0.98,
            EvaluationDimension.COMPLETENESS.value: 0.99,
            EvaluationDimension.EFFICIENCY.value: 0.95,
            EvaluationDimension.POLICY_COMPLIANCE.value: 0.50,  # Violated
            EvaluationDimension.RELIABILITY.value: 1.0,
            EvaluationDimension.REPRODUCIBILITY.value: 1.0,
        }
        score, disq, reason = config.compute_score(scores)
        self.assertTrue(disq, "Branch with compliance < 1.0 must be disqualified")
        self.assertEqual(score, 0.0, "Violating branch must receive 0.00 score")

    def test_speculative_execution_competing_branches_and_auto_promotion(self):
        """
        Orchestrates 3 competing hypotheses concurrently:
        - Branch A: Solid hypothesis (High correctness, Moderate efficiency)
        - Branch B: Superior hypothesis (High correctness, High efficiency) -> WINNER
        - Branch C: Policy violating / low evidence branch -> REJECTED
        Verifies automatic promotion of Branch B to Primary HEAD without corrupting historical lineage.
        """
        branch_specs = [
            {
                "hypothesis": "Hypothesis A: Raft Consensus with log replication",
                "branch_name": "branch-raft-01",
                "requested_capabilities": ["document_analysis"],
                "requested_actions": ["read", "query"],
                "requested_resources": ["/workspace/research/raft/*"],
                "simulated_output": {
                    "correctness": 0.88,
                    "evidence": 0.85,
                    "completeness": 0.90,
                    "efficiency": 0.75,
                    "reliability": 0.95,
                    "policy_compliance": 1.00,
                    "reproducibility": 0.90,
                    "conclusion": "Raft is simple and correct for small clusters.",
                },
            },
            {
                "hypothesis": "Hypothesis B: Paxos Multi-Decree with pipelining",
                "branch_name": "branch-paxos-02",
                "requested_capabilities": ["document_analysis"],
                "requested_actions": ["read", "query"],
                "requested_resources": ["/workspace/research/paxos/*"],
                "simulated_output": {
                    "correctness": 0.97,
                    "evidence": 0.95,
                    "completeness": 0.94,
                    "efficiency": 0.88,
                    "reliability": 0.98,
                    "policy_compliance": 1.00,
                    "reproducibility": 0.96,
                    "conclusion": "Paxos pipelining provides maximum throughput and proven correctness.",
                },
            },
            {
                "hypothesis": "Hypothesis C: Rogue unauthorized branch with scope escalation attempt",
                "branch_name": "branch-rogue-03",
                "requested_capabilities": ["document_analysis"],
                "requested_actions": ["read"],
                "requested_resources": ["/workspace/research/unauthorized/*"],
                "simulated_output": {
                    "correctness": 0.99,
                    "evidence": 0.99,
                    "completeness": 0.99,
                    "efficiency": 0.99,
                    "reliability": 1.00,
                    "policy_compliance": 0.00,  # Deliberate failure
                    "reproducibility": 1.00,
                    "policy_violation_attempted": True,
                },
            },
        ]

        matrix, promotion = self.speculative_controller.run_speculative_execution(
            checkpoint_id=self.baseline_checkpoint.id,
            caller_identity_token=self.id_token.raw_token,
            source_scope_token=self.scope_token_str,
            branch_specs=branch_specs,
            auto_promote=True,
        )

        self.assertIsNotNone(matrix)
        self.assertEqual(len(matrix.evaluations), 3)

        # Check winner is Branch B
        paxos_branch = next(b for b in matrix.evaluations if "paxos" in b.branch_id.lower())
        raft_branch = next(b for b in matrix.evaluations if "raft" in b.branch_id.lower())
        rogue_branch = next(b for b in matrix.evaluations if "rogue" in b.branch_id.lower())

        self.assertEqual(matrix.winning_branch_id, paxos_branch.branch_id)
        self.assertGreater(paxos_branch.final_score, raft_branch.final_score)
        self.assertEqual(rogue_branch.final_score, 0.0)
        self.assertTrue(rogue_branch.disqualified)

        # Check promotion
        self.assertIsNotNone(promotion)
        self.assertEqual(promotion.status, "PROMOTED")
        self.assertEqual(promotion.promoted_branch_id, paxos_branch.branch_id)
        self.assertEqual(promotion.promoted_checkpoint_id, paxos_branch.checkpoint_id)

        # Check Primary HEAD updated in session
        head_chk_id = self.store.get_session_head(self.session_id)
        self.assertEqual(head_chk_id, paxos_branch.checkpoint_id)

        # INVARIANT CHECK: Historical baseline checkpoint remains immutable
        baseline = self.store.get_checkpoint(self.baseline_checkpoint.id)
        self.assertIsNotNone(baseline)
        self.assertEqual(baseline.id, self.baseline_checkpoint.id)

        # INVARIANT CHECK: Losing branch checkpoints remain inspectable
        raft_chk = self.store.get_checkpoint(raft_branch.checkpoint_id)
        self.assertIsNotNone(raft_chk)

        # INVARIANT CHECK: Lineage DAG reflects parent -> child branches
        lineage = self.branching_controller.get_lineage(self.session_id)
        self.assertEqual(lineage.total_branches, 3)
        self.assertIn(paxos_branch.branch_id, lineage.lineage_dag.get(self.baseline_checkpoint.id, []))
        self.assertIn(raft_branch.branch_id, lineage.lineage_dag.get(self.baseline_checkpoint.id, []))

    def test_promotion_idempotency(self):
        """Validates that promoting the same branch checkpoint twice returns the existing result safely."""
        branch_req = BranchRequest(
            parent_checkpoint_id=self.baseline_checkpoint.id,
            caller_identity_token=self.id_token.raw_token,
            source_scope_token=self.scope_token_str,
            hypothesis="Idempotency verification branch",
            requested_capabilities=["document_analysis"],
            requested_actions=["read"],
            requested_resources=["/workspace/research/*"],
        )
        branch = self.branching_controller.create_branch(branch_req)
        committed_chk = self.branching_controller.commit_branch_checkpoint(
            branch_id=branch.branch_id,
            checkpoint_data={"id": f"chk-{branch.branch_id}-c2", "metadata": {"status": "success"}},
        )

        res1 = self.promoter.promote_branch(
            session_id=self.session_id,
            winning_branch_id=branch.branch_id,
            winning_checkpoint_id=committed_chk.id,
        )
        self.assertEqual(res1.status, "PROMOTED")

        # Second call with same parameters
        res2 = self.promoter.promote_branch(
            session_id=self.session_id,
            winning_branch_id=branch.branch_id,
            winning_checkpoint_id=committed_chk.id,
        )
        self.assertEqual(res2.promotion_id, res1.promotion_id)
        self.assertEqual(res2.promoted_checkpoint_id, committed_chk.id)


if __name__ == "__main__":
    unittest.main()
