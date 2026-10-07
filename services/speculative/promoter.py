"""
services/speculative/promoter.py — Branch Promotion Controller
Enforces: Promotion changes the active state reference, not the historical truth of the execution graph.
"""
from __future__ import annotations
import logging
import time
from typing import Any, Dict, Optional
import uuid

from domain.sessions.models import AuditEvent
from domain.speculative.models import PromotionResult
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.speculative.promoter")


class PromotionError(Exception):
    pass


class BranchPromotionController:
    """
    Manages atomic, idempotent state promotion of winning branches.
    Enforces the core invariant:
    Promotion changes the active state reference, not the historical truth of the execution graph.
    """

    def __init__(self, metadata_store: Optional[MetadataStoreInterface] = None):
        self.store = metadata_store or SQLiteMetadataStore()

    def promote_branch(
        self,
        session_id: str,
        winning_branch_id: str,
        winning_checkpoint_id: str,
        evaluation_id: Optional[str] = None,
        operator: str = "orchestrator",
    ) -> PromotionResult:
        """
        Promotes the winning branch checkpoint to become the session's new Primary HEAD.
        Leaves historical checkpoints and losing branches completely intact in the lineage DAG.
        Idempotent: repeating promotion of the same checkpoint returns existing state.
        """
        # 1. Validate session exists
        session = self.store.get_session(session_id)
        if not session:
            raise PromotionError(f"Session '{session_id}' not found")

        # 2. Validate winning branch and checkpoint exist
        branch = self.store.get_branch(winning_branch_id)
        if not branch:
            raise PromotionError(f"Branch '{winning_branch_id}' not found")

        checkpoint = self.store.get_checkpoint(winning_checkpoint_id)
        if not checkpoint:
            raise PromotionError(f"Checkpoint '{winning_checkpoint_id}' not found")

        # 3. Check if evaluation disqualified the branch
        if evaluation_id:
            evaluation = self.store.get_evaluation(evaluation_id)
            if evaluation and evaluation.disqualified:
                raise PromotionError(
                    f"Cannot promote disqualified branch '{winning_branch_id}': {evaluation.disqualification_reason}"
                )

        # 4. Check current session head
        prev_head = self.store.get_session_head(session_id)
        if prev_head == winning_checkpoint_id:
            # Idempotent: already at head
            latest = self.store.get_latest_promotion(session_id)
            if latest and latest.promoted_checkpoint_id == winning_checkpoint_id:
                logger.info(f"Branch '{winning_branch_id}' already promoted to head for session '{session_id}'")
                return latest

        # 5. Record promotion audit event
        audit_id = f"evt-promo-{uuid.uuid4().hex[:8]}"
        audit_event = AuditEvent(
            event_id=audit_id,
            session_id=session_id,
            task_id=branch.task_id,
            from_status=f"HEAD:{prev_head or 'root'}",
            to_status=f"HEAD:{winning_checkpoint_id}",
            reason=f"Speculative winner promoted: branch '{winning_branch_id}'",
            actor=operator,
            details={
                "winning_branch_id": winning_branch_id,
                "winning_checkpoint_id": winning_checkpoint_id,
                "previous_head": prev_head,
                "evaluation_id": evaluation_id,
                "hypothesis": branch.hypothesis,
            },
        )
        self.store.record_audit_event(audit_event)

        # 6. Instantiate and persist PromotionResult
        promo = PromotionResult(
            session_id=session_id,
            promoted_branch_id=winning_branch_id,
            promoted_checkpoint_id=winning_checkpoint_id,
            previous_head_checkpoint_id=prev_head,
            new_head_checkpoint_id=winning_checkpoint_id,
            evaluation_id=evaluation_id or "",
            audit_id=audit_id,
        )
        self.store.save_promotion(promo)

        # 7. Update session metadata reference
        session.metadata["active_head_checkpoint_id"] = winning_checkpoint_id
        session.metadata["active_branch_id"] = winning_branch_id
        session.active_task_id = branch.task_id
        session.workspace_id = branch.workspace_id
        self.store.save_session(session)

        logger.info(
            f"Successfully promoted branch '{winning_branch_id}' (checkpoint '{winning_checkpoint_id}') "
            f"to Primary HEAD for session '{session_id}' [Previous HEAD: {prev_head}]"
        )
        return promo

    def get_current_head(self, session_id: str) -> Optional[str]:
        return self.store.get_session_head(session_id)
