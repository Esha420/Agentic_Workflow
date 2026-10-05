"""
domain/lifecycle/policies.py — Policy rules for suspension and reclamation
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class SuspensionPolicy:
    """
    Evaluates whether an agent in WAITING state should be checkpointed and suspended.
    """
    min_estimated_wait_seconds: float = 10.0
    auto_suspend_on_async_job: bool = True
    enforce_worker_reclamation: bool = True

    def should_suspend(
        self,
        job_type: str,
        estimated_wait_seconds: Optional[float] = None,
    ) -> bool:
        if not self.auto_suspend_on_async_job:
            return False

        # Jobs known to take significant time (e.g. security scans, synthesis, math proofs)
        long_running_jobs = {"scan", "synthesis", "math", "render", "aggregation"}
        if job_type in long_running_jobs:
            return True

        if estimated_wait_seconds is not None:
            return estimated_wait_seconds >= self.min_estimated_wait_seconds

        return True
