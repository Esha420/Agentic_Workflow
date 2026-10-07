"""
domain/speculative/models.py — Speculative Execution, Multi-Dimensional Evaluation Matrix, and Promotion Models
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import uuid


class EvaluationDimension(str, Enum):
    CORRECTNESS = "correctness"
    EVIDENCE = "evidence"
    COMPLETENESS = "completeness"
    EFFICIENCY = "efficiency"
    RELIABILITY = "reliability"
    POLICY_COMPLIANCE = "policy_compliance"
    REPRODUCIBILITY = "reproducibility"


@dataclass
class ScoringConfig:
    """
    Explicit, deterministic scoring weights across the 7 evaluation dimensions.
    Enforces strict policy compliance: any violation disqualifies the branch.
    """
    w_correctness: float = 0.25
    w_evidence: float = 0.20
    w_completeness: float = 0.20
    w_efficiency: float = 0.15
    w_reliability: float = 0.10
    w_reproducibility: float = 0.10
    require_strict_compliance: bool = True

    def compute_score(self, metrics: Dict[str, float]) -> Tuple[float, bool, Optional[str]]:
        """
        Computes final weighted score in [0.0, 1.0].
        Returns (final_score, is_disqualified, disqualification_reason).
        """
        compliance = metrics.get(EvaluationDimension.POLICY_COMPLIANCE.value, 1.0)
        if self.require_strict_compliance and compliance < 1.0:
            return 0.0, True, f"Policy violation detected (compliance score: {compliance:.2f} < 1.00)"

        raw_score = (
            self.w_correctness * metrics.get(EvaluationDimension.CORRECTNESS.value, 0.0) +
            self.w_evidence * metrics.get(EvaluationDimension.EVIDENCE.value, 0.0) +
            self.w_completeness * metrics.get(EvaluationDimension.COMPLETENESS.value, 0.0) +
            self.w_efficiency * metrics.get(EvaluationDimension.EFFICIENCY.value, 0.0) +
            self.w_reliability * metrics.get(EvaluationDimension.RELIABILITY.value, 0.0) +
            self.w_reproducibility * metrics.get(EvaluationDimension.REPRODUCIBILITY.value, 0.0)
        )
        final_score = round(max(0.0, min(1.0, raw_score)), 4)
        return final_score, False, None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BranchEvaluation:
    """
    Structured multi-dimensional evaluation of a branch's output and behavior.
    """
    evaluation_id: str = field(default_factory=lambda: f"eval-{uuid.uuid4().hex[:8]}")
    branch_id: str = ""
    checkpoint_id: str = ""
    session_id: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)
    dimension_details: Dict[str, Any] = field(default_factory=dict)
    is_compliant: bool = True
    disqualified: bool = False
    disqualification_reason: Optional[str] = None
    final_score: float = 0.0
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BranchEvaluation:
        return cls(**data)


@dataclass
class EvaluationMatrix:
    """
    Aggregated comparison matrix and deterministic ranking across competing branches.
    """
    session_id: str
    parent_checkpoint_id: str
    scoring_config: ScoringConfig
    evaluations: List[BranchEvaluation] = field(default_factory=list)
    ranking: List[str] = field(default_factory=list)  # branch_ids in descending order of score
    winning_branch_id: Optional[str] = None
    winning_checkpoint_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scoring_config"] = self.scoring_config.to_dict()
        d["evaluations"] = [e.to_dict() for e in self.evaluations]
        return d


@dataclass
class PromotionResult:
    """
    Captures atomic promotion of winning branch state to the new Primary HEAD.
    Preserves historical lineage immutability.
    """
    promotion_id: str = field(default_factory=lambda: f"prm-{uuid.uuid4().hex[:8]}")
    session_id: str = ""
    promoted_branch_id: str = ""
    promoted_checkpoint_id: str = ""
    previous_head_checkpoint_id: Optional[str] = None
    new_head_checkpoint_id: str = ""
    evaluation_id: str = ""
    status: str = "PROMOTED"
    promoted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    audit_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
