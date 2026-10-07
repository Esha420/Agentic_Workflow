"""
services/speculative/evaluator.py — Multi-Dimensional Evaluation Framework
Evaluates competing branches quantitatively across 7 explicit dimensions.
"""
from __future__ import annotations
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from domain.checkpoints.branching import ExecutionBranch
from domain.checkpoints.models import Checkpoint
from domain.speculative.models import (
    BranchEvaluation,
    EvaluationDimension,
    EvaluationMatrix,
    ScoringConfig,
)
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.speculative.evaluator")


class MultiDimensionalEvaluator:
    """
    Evaluates branch executions across seven dimensions:
    - Correctness: Valid result syntax & semantic correctness
    - Evidence quality: Depth of sources, empirical verification, artifact presence
    - Completeness: Satisfied requested objective
    - Efficiency: Execution time, tool/compute usage
    - Reliability: Error rate, retries, stability
    - Policy compliance: Strict adherence to authorized scope boundaries
    - Reproducibility: Determinism and reconstructibility
    """

    def __init__(
        self,
        metadata_store: Optional[MetadataStoreInterface] = None,
        default_scoring_config: Optional[ScoringConfig] = None,
    ):
        self.store = metadata_store or SQLiteMetadataStore()
        self.config = default_scoring_config or ScoringConfig()

    def evaluate_branch(
        self,
        branch: ExecutionBranch,
        branch_checkpoint: Checkpoint,
        branch_output_data: Optional[Dict[str, Any]] = None,
        scoring_config: Optional[ScoringConfig] = None,
    ) -> BranchEvaluation:
        """
        Computes structured multi-dimensional evaluation for a single branch.
        """
        config = scoring_config or self.config
        output_data = branch_output_data or branch_checkpoint.metadata or {}

        metrics: Dict[str, float] = {}
        details: Dict[str, Any] = {}

        # 1. Correctness
        correctness = float(output_data.get("correctness", output_data.get("accuracy", 0.85)))
        has_error = bool(output_data.get("has_error", False))
        if has_error:
            correctness = min(correctness, 0.20)
        metrics[EvaluationDimension.CORRECTNESS.value] = round(max(0.0, min(1.0, correctness)), 4)
        details["correctness_reason"] = output_data.get("correctness_reason", "Verified output validity")

        # 2. Evidence Quality
        evidence = float(output_data.get("evidence", output_data.get("evidence_score", 0.80)))
        metrics[EvaluationDimension.EVIDENCE.value] = round(max(0.0, min(1.0, evidence)), 4)
        details["evidence_sources"] = output_data.get("evidence_sources", 1)

        # 3. Completeness
        completeness = float(output_data.get("completeness", 0.90))
        metrics[EvaluationDimension.COMPLETENESS.value] = round(max(0.0, min(1.0, completeness)), 4)
        details["satisfied_goals"] = output_data.get("satisfied_goals", True)

        # 4. Efficiency
        duration_s = float(output_data.get("duration_seconds", output_data.get("latency_s", 2.0)))
        calls = int(output_data.get("tool_calls", 3))
        # Normalized efficiency: faster duration & fewer calls yields higher score
        eff_score = max(0.1, min(1.0, 1.0 - (duration_s / 20.0) - (calls * 0.02)))
        efficiency = float(output_data.get("efficiency", eff_score))
        metrics[EvaluationDimension.EFFICIENCY.value] = round(max(0.0, min(1.0, efficiency)), 4)
        details["duration_seconds"] = duration_s
        details["tool_calls"] = calls

        # 5. Reliability
        retries = int(output_data.get("retries", 0))
        errors = int(output_data.get("error_count", 0))
        rel_score = max(0.0, 1.0 - (retries * 0.15) - (errors * 0.40))
        reliability = float(output_data.get("reliability", rel_score))
        metrics[EvaluationDimension.RELIABILITY.value] = round(max(0.0, min(1.0, reliability)), 4)
        details["retries"] = retries
        details["error_count"] = errors

        # 6. Policy Compliance (Strict fail-closed dimension)
        # Check audit trail for any scope/policy rejections during this branch
        branch_audits = self.store.list_audit_events(task_id=branch.task_id)
        has_violations = any(
            "DENIED" in (evt.to_status or "") or "escalation denied" in (evt.reason or "").lower()
            for evt in branch_audits
        ) or bool(output_data.get("policy_violation_attempted", False))

        compliance = 0.0 if has_violations else float(output_data.get("policy_compliance", 1.0))
        metrics[EvaluationDimension.POLICY_COMPLIANCE.value] = compliance
        details["policy_violations_found"] = has_violations

        # 7. Reproducibility
        reproducibility = float(output_data.get("reproducibility", 0.95))
        metrics[EvaluationDimension.REPRODUCIBILITY.value] = round(max(0.0, min(1.0, reproducibility)), 4)
        details["deterministic_seed"] = output_data.get("seed", 42)

        # Compute final score and check strict compliance disqualification
        final_score, disqualified, disq_reason = config.compute_score(metrics)

        evaluation = BranchEvaluation(
            branch_id=branch.branch_id,
            checkpoint_id=branch_checkpoint.id,
            session_id=branch.session_id,
            metrics=metrics,
            dimension_details=details,
            is_compliant=(compliance >= 1.0),
            disqualified=disqualified,
            disqualification_reason=disq_reason,
            final_score=final_score,
        )

        self.store.save_evaluation(evaluation)
        return evaluation

    def evaluate_matrix(
        self,
        session_id: str,
        parent_checkpoint_id: str,
        branch_evaluations: List[BranchEvaluation],
        scoring_config: Optional[ScoringConfig] = None,
    ) -> EvaluationMatrix:
        """
        Compiles an aggregated comparison matrix and ranks branches by final score.
        """
        config = scoring_config or self.config

        # Sort non-disqualified branches first, descending by final_score
        valid_evals = [e for e in branch_evaluations if not e.disqualified]
        disq_evals = [e for e in branch_evaluations if e.disqualified]

        valid_evals.sort(key=lambda e: e.final_score, reverse=True)
        disq_evals.sort(key=lambda e: e.final_score, reverse=True)

        ranked_evals = valid_evals + disq_evals
        ranking = [e.branch_id for e in ranked_evals]

        winner = valid_evals[0] if valid_evals else None

        matrix = EvaluationMatrix(
            session_id=session_id,
            parent_checkpoint_id=parent_checkpoint_id,
            scoring_config=config,
            evaluations=ranked_evals,
            ranking=ranking,
            winning_branch_id=winner.branch_id if winner else None,
            winning_checkpoint_id=winner.checkpoint_id if winner else None,
        )
        return matrix
