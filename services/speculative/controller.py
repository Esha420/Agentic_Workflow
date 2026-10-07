"""
services/speculative/controller.py — Speculative Execution Controller
Orchestrates parallel hypothesis branches, evaluation ranking, and winner promotion.
"""
from __future__ import annotations
import concurrent.futures
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from domain.checkpoints.branching import BranchRequest, ExecutionBranch
from domain.checkpoints.models import Checkpoint
from domain.speculative.models import (
    BranchEvaluation,
    EvaluationMatrix,
    PromotionResult,
    ScoringConfig,
)
from services.checkpoints.branching import CheckpointBranchingController
from services.speculative.evaluator import MultiDimensionalEvaluator
from services.speculative.promoter import BranchPromotionController, PromotionError
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.speculative.controller")


class SpeculativeExecutionController:
    """
    Orchestrates the entire speculative lifecycle:
    Checkpoint -> Create N Branches -> Execute Hypotheses -> Collect Results ->
    Evaluate Multi-Dimensional Matrix -> Rank Branches -> Promote Winner.
    """

    def __init__(
        self,
        branching_controller: CheckpointBranchingController,
        evaluator: Optional[MultiDimensionalEvaluator] = None,
        promoter: Optional[BranchPromotionController] = None,
        metadata_store: Optional[MetadataStoreInterface] = None,
    ):
        self.branching = branching_controller
        self.store = metadata_store or branching_controller.store
        self.evaluator = evaluator or MultiDimensionalEvaluator(self.store)
        self.promoter = promoter or BranchPromotionController(self.store)

    def run_speculative_execution(
        self,
        checkpoint_id: str,
        caller_identity_token: str,
        source_scope_token: str,
        branch_specs: List[Dict[str, Any]],
        scoring_config: Optional[ScoringConfig] = None,
        auto_promote: bool = True,
    ) -> Tuple[EvaluationMatrix, Optional[PromotionResult]]:
        """
        Runs speculative execution across multiple competing hypothesis branches.
        1. Validates parent checkpoint
        2. Forks N branches with isolated workspaces & identities
        3. Executes hypothesis tasks (or simulates research runs) concurrently
        4. Evaluates all branches across 7 dimensions
        5. Computes ranking matrix
        6. Automatically promotes highest-ranking valid branch to Primary HEAD
        """
        parent_checkpoint = self.branching.validate_parent_checkpoint(checkpoint_id)
        session_id = parent_checkpoint.session_id

        # 1. Fork N Branches
        created_branches: List[ExecutionBranch] = []
        for spec in branch_specs:
            req = BranchRequest(
                parent_checkpoint_id=checkpoint_id,
                caller_identity_token=caller_identity_token,
                source_scope_token=source_scope_token,
                hypothesis=spec.get("hypothesis", "Speculative hypothesis"),
                branch_name=spec.get("branch_name"),
                target_agent_id=spec.get("target_agent_id"),
                requested_capabilities=spec.get("requested_capabilities"),
                requested_actions=spec.get("requested_actions"),
                requested_resources=spec.get("requested_resources"),
                requested_ttl=spec.get("requested_ttl", 3600),
                max_invocations=spec.get("max_invocations", 10),
                metadata=spec.get("metadata", {}),
            )
            branch = self.branching.create_branch(req)
            created_branches.append(branch)

        # 2. Concurrently execute / advance branches
        evaluations: List[BranchEvaluation] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(created_branches))) as executor:
            future_to_branch = {}
            for idx, branch in enumerate(created_branches):
                spec = branch_specs[idx]
                future = executor.submit(self._execute_and_commit_branch, branch, spec)
                future_to_branch[future] = branch

            for future in concurrent.futures.as_completed(future_to_branch):
                branch = future_to_branch[future]
                try:
                    committed_chk, output_data = future.result()
                    eval_res = self.evaluator.evaluate_branch(
                        branch=branch,
                        branch_checkpoint=committed_chk,
                        branch_output_data=output_data,
                        scoring_config=scoring_config,
                    )
                    evaluations.append(eval_res)
                except Exception as e:
                    logger.error(f"Execution failed on branch '{branch.branch_id}': {e}")

        # 3. Compile Evaluation Matrix and Rankings
        matrix = self.evaluator.evaluate_matrix(
            session_id=session_id,
            parent_checkpoint_id=checkpoint_id,
            branch_evaluations=evaluations,
            scoring_config=scoring_config,
        )

        # 4. Auto-Promote Winner if requested
        promotion_result: Optional[PromotionResult] = None
        if auto_promote and matrix.winning_branch_id and matrix.winning_checkpoint_id:
            winner_eval = next((e for e in matrix.evaluations if e.branch_id == matrix.winning_branch_id), None)
            promotion_result = self.promoter.promote_branch(
                session_id=session_id,
                winning_branch_id=matrix.winning_branch_id,
                winning_checkpoint_id=matrix.winning_checkpoint_id,
                evaluation_id=winner_eval.evaluation_id if winner_eval else None,
                operator="SpeculativeExecutionController",
            )

        return matrix, promotion_result

    def _execute_and_commit_branch(
        self,
        branch: ExecutionBranch,
        spec: Dict[str, Any],
    ) -> Tuple[Checkpoint, Dict[str, Any]]:
        """
        Executes a branch's hypothesis work and commits a new checkpoint.
        """
        output_data = spec.get("simulated_output", {})

        # Write artifacts to branch workspace volume
        branch_ws_path = os.path.join(self.branching.workspace_base_dir, branch.workspace_id)
        if os.path.exists(branch_ws_path):
            result_file = os.path.join(branch_ws_path, "SPECULATIVE_RESULT.json")
            with open(result_file, "w") as f:
                json.dump({
                    "branch_id": branch.branch_id,
                    "hypothesis": branch.hypothesis,
                    "metrics": output_data,
                }, f, indent=2)

        # Commit branch checkpoint (Gen 2)
        committed_chk = self.branching.commit_branch_checkpoint(
            branch_id=branch.branch_id,
            checkpoint_data={
                "id": f"chk-{branch.branch_id}-c2",
                "metadata": output_data,
            },
        )
        return committed_chk, output_data
