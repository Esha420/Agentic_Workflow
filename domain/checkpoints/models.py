"""
domain/checkpoints/models.py — Checkpoint domain model
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid


@dataclass
class Checkpoint:
    id: str = field(default_factory=lambda: f"chk-{uuid.uuid4().hex[:8]}")
    session_id: str = ""
    task_id: str = ""
    workspace_version: str = "v1"
    execution_state_key: Optional[str] = None
    parent_checkpoint_id: Optional[str] = None
    branch_id: Optional[str] = None
    workspace_generation: int = 1
    snapshot_reference: Optional[str] = None
    authorization_context: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Checkpoint:
        return cls(**data)
