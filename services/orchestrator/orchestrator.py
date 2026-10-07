"""
services/orchestrator/orchestrator.py — ResearchSession & Lifecycle Orchestrator
"""
from __future__ import annotations
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from domain.sessions.models import ResearchSession, SessionStatus
from domain.tasks.models import Task, TaskPhase
from domain.checkpoints.models import Checkpoint
from domain.checkpoints.branching import ExecutionBranch, BranchRequest, BranchLineage
from domain.agents.models import Agent, AgentLifecycleState
from domain.lifecycle.transitions import LifecycleTransitionManager
from domain.lifecycle.policies import SuspensionPolicy
from services.agents.registry import AgentRegistryService
from services.identity.manager import IdentityManager
from services.policy.capabilities import CapabilityRegistry
from services.policy.engine import PolicyEngine
from services.policy.scope_issuer import ScopeIssuer
from services.delegation.engine import DelegationEngine
from services.communication.manager import CommunicationManager
from services.gateway.authorizer import AgentGatewayAuthorizer
from services.checkpoints.branching import CheckpointBranchingController
from domain.speculative.models import EvaluationMatrix, PromotionResult, ScoringConfig, BranchEvaluation
from services.speculative.controller import SpeculativeExecutionController
from services.speculative.evaluator import MultiDimensionalEvaluator
from services.speculative.promoter import BranchPromotionController
from adapters.ax.ax_adapter import AXAdapterInterface, ClusterAXAdapter
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.orchestrator")


class OrchestratorError(Exception):
    pass


class ResearchSessionService:
    """
    Coordinates the end-to-end lifecycle of research sessions across the control plane
    and the AX execution plane.
    """

    def __init__(
        self,
        metadata_store: Optional[MetadataStoreInterface] = None,
        ax_adapter: Optional[AXAdapterInterface] = None,
        suspension_policy: Optional[SuspensionPolicy] = None,
        agent_registry: Optional[AgentRegistryService] = None,
        identity_manager: Optional[IdentityManager] = None,
        capability_registry: Optional[CapabilityRegistry] = None,
        policy_engine: Optional[PolicyEngine] = None,
        scope_issuer: Optional[ScopeIssuer] = None,
        delegation_engine: Optional[DelegationEngine] = None,
        communication_manager: Optional[CommunicationManager] = None,
        gateway_authorizer: Optional[AgentGatewayAuthorizer] = None,
    ):
        self.store = metadata_store or SQLiteMetadataStore()
        self.ax = ax_adapter or ClusterAXAdapter()
        self.policy = suspension_policy or SuspensionPolicy()
        self.registry = agent_registry or AgentRegistryService(self.store)
        self.identity_mgr = identity_manager or IdentityManager(registry=self.registry, metadata_store=self.store)
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.policy_engine = policy_engine or PolicyEngine(
            capability_registry=self.capability_registry,
            identity_manager=self.identity_mgr,
            metadata_store=self.store,
        )
        self.scope_issuer = scope_issuer or ScopeIssuer()
        self.delegation_engine = delegation_engine or DelegationEngine(
            agent_registry=self.registry,
            identity_manager=self.identity_mgr,
            capability_registry=self.capability_registry,
            scope_issuer=self.scope_issuer,
            metadata_store=self.store,
        )
        self.communication_mgr = communication_manager or CommunicationManager(
            delegation_engine=self.delegation_engine,
            agent_registry=self.registry,
            metadata_store=self.store,
        )
        self.gateway_authorizer = gateway_authorizer or AgentGatewayAuthorizer(
            identity_manager=self.identity_mgr,
            scope_issuer=self.scope_issuer,
            delegation_engine=self.delegation_engine,
            metadata_store=self.store,
        )
        self.branching_controller = CheckpointBranchingController(
            metadata_store=self.store,
            agent_registry=self.registry,
            identity_manager=self.identity_mgr,
            capability_registry=self.capability_registry,
            scope_issuer=self.scope_issuer,
        )
        self.speculative_controller = SpeculativeExecutionController(
            branching_controller=self.branching_controller,
            metadata_store=self.store,
        )



    def create_session(
        self,
        objective: str,
        session_id: Optional[str] = None,
        target: str = "Autonomous Actor Checkpointing & State Persistence",
        role: str = "research",
        atespace: str = "default",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ResearchSession:
        """Creates a research session and launches its execution task."""
        if idempotency_key:
            cached = self.store.check_idempotency(idempotency_key)
            if cached:
                logger.info(f"Returning cached session for idempotency key '{idempotency_key}'")
                return ResearchSession.from_dict(cached)

        session_id = session_id or f"rs-{uuid.uuid4().hex[:8]}"
        existing = self.store.get_session(session_id)
        if existing:
            raise OrchestratorError(f"Research session with id '{session_id}' already exists")

        meta = dict(metadata or {})
        task_name = session_id
        workspace_id = f"ws-{session_id}"

        # 1. Authoritative Agent Registry lookup / auto-registration
        agent_id = meta.get("agent_id") or f"agent-{session_id}"
        agent = self.registry.get_agent(agent_id)
        if not agent:
            agent = self.registry.register_agent(
                agent_id=agent_id,
                role=role,
                tenant=meta.get("tenant", "default"),
                environment=meta.get("environment", "staging"),
                capabilities=meta.get("capabilities", ["web_research", "doc_analysis", "repo_read"]),
            )

        # 2. Provision task-scoped workload identity token via IdentityManager
        agent, id_token = self.identity_mgr.provision_agent_identity(
            agent_id=agent_id,
            task_id=task_name,
            workspace_id=workspace_id,
            session_id=session_id,
        )

        meta["agent_id"] = agent_id
        meta["identity_subject"] = agent.identity_subject
        meta["identity_jti"] = id_token.jti

        session = ResearchSession(
            id=session_id,
            objective=objective,
            target=target,
            role=role,
            atespace=atespace,
            workspace_id=workspace_id,
            metadata=meta,
        )

        # Transition: CREATED -> STARTING
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.STARTING,
            reason="Session initialization",
            actor="orchestrator",
        )
        self.store.save_session(session)

        # Apply AX Task with cryptographic identity attached
        try:
            task = self.ax.apply_task(
                task_name=task_name,
                session_id=session_id,
                target=target,
                atespace=atespace,
                identity_token=id_token.raw_token,
                identity_subject=agent.identity_subject,
            )
            session.active_task_id = task.id
            self.store.save_task(task)

            # Transition: STARTING -> RUNNING
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.RUNNING,
                reason="Task scheduled on AX execution plane",
                actor="orchestrator",
                details={"task_name": task.id},
            )
            self.store.save_session(session)

        except Exception as e:
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.FAILED,
                reason=f"Failed to schedule AX task: {e}",
                actor="orchestrator",
            )
            self.store.save_session(session)
            raise OrchestratorError(f"Failed to create session task: {e}") from e

        if idempotency_key:
            self.store.record_idempotency(idempotency_key, session.to_dict())

        return session

    def get_session(self, session_id: str, sync: bool = True) -> Optional[ResearchSession]:
        session = self.store.get_session(session_id)
        if not session:
            return None

        if sync and session.active_task_id:
            self.sync_session_state(session)

        return session

    def list_sessions(self, status: Optional[SessionStatus] = None) -> List[ResearchSession]:
        return self.store.list_sessions(status)

    def sync_session_state(self, session: ResearchSession) -> ResearchSession:
        """Polls AX execution state and reconciles session status."""
        if not session.active_task_id:
            return session

        try:
            ax_task = self.ax.get_task(session.active_task_id, atespace=session.atespace)
            if not ax_task:
                return session

            session.active_worker_ip = ax_task.worker_ip
            self.store.save_task(ax_task)

            # Reconcile status transitions
            if ax_task.phase == TaskPhase.SUSPENDED and session.status not in (
                SessionStatus.SUSPENDED,
                SessionStatus.SUSPENDING,
            ):
                checkpoint = Checkpoint(
                    session_id=session.id,
                    task_id=session.active_task_id,
                    workspace_version=f"v-{int(time.time())}",
                    metadata={"reason": "Autonomous observer suspension; worker reclaimed"},
                )
                self.store.save_checkpoint(checkpoint)
                LifecycleTransitionManager.transition(
                    session=session,
                    target_status=SessionStatus.SUSPENDED,
                    reason="AX reported Task suspended; worker compute reclaimed",
                    actor="ax_sync",
                    details={"checkpoint_id": checkpoint.id},
                )
                self.store.save_session(session)

            elif ax_task.phase == TaskPhase.RUNNING and session.status in (
                SessionStatus.SUSPENDED,
                SessionStatus.RESUMING,
                SessionStatus.STARTING,
            ):
                LifecycleTransitionManager.transition(
                    session=session,
                    target_status=SessionStatus.RUNNING,
                    reason="AX reported Task running on worker",
                    actor="ax_sync",
                    details={"worker_ip": ax_task.worker_ip},
                )
                self.store.save_session(session)

            elif ax_task.phase == TaskPhase.COMPLETED and session.status != SessionStatus.COMPLETED:
                LifecycleTransitionManager.transition(
                    session=session,
                    target_status=SessionStatus.COMPLETED,
                    reason="AX reported Task completed successfully",
                    actor="ax_sync",
                )
                self.store.save_session(session)

            elif ax_task.phase == TaskPhase.FAILED and session.status != SessionStatus.FAILED:
                LifecycleTransitionManager.transition(
                    session=session,
                    target_status=SessionStatus.FAILED,
                    reason="AX reported Task execution failure",
                    actor="ax_sync",
                )
                self.store.save_session(session)

        except Exception as e:
            logger.warning(f"Error syncing task state for session '{session.id}': {e}")

        return session

    def suspend_session(
        self,
        session_id: str,
        reason: str = "Operator requested suspend",
        actor: str = "operator",
        idempotency_key: Optional[str] = None,
    ) -> ResearchSession:
        """Suspends active session task and confirms worker reclamation."""
        if idempotency_key:
            cached = self.store.check_idempotency(idempotency_key)
            if cached:
                return ResearchSession.from_dict(cached)

        session = self.get_session(session_id, sync=True)
        if not session:
            raise OrchestratorError(f"Session '{session_id}' not found")

        if session.status == SessionStatus.SUSPENDED:
            logger.info(f"Session '{session_id}' is already suspended")
            return session

        if not session.active_task_id:
            raise OrchestratorError(f"Session '{session_id}' has no active task to suspend")

        # Transition: RUNNING/WAITING -> SUSPENDING
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.SUSPENDING,
            reason=reason,
            actor=actor,
        )
        self.store.save_session(session)

        # Execute AX suspend
        try:
            self.ax.suspend_task(session.active_task_id, atespace=session.atespace)
        except Exception as e:
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.FAILED,
                reason=f"Failed to suspend AX task: {e}",
                actor=actor,
            )
            self.store.save_session(session)
            raise OrchestratorError(f"AX suspend failed: {e}") from e

        # Wait briefly for AX status update
        time.sleep(1)

        # Capture checkpoint record
        checkpoint = Checkpoint(
            session_id=session.id,
            task_id=session.active_task_id,
            workspace_version=f"v-{int(time.time())}",
            metadata={"reason": reason, "suspended_at_version": session.version},
        )
        self.store.save_checkpoint(checkpoint)

        # Transition: SUSPENDING -> SUSPENDED
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.SUSPENDED,
            reason="Worker released; checkpoint saved to RustFS",
            actor=actor,
            details={"checkpoint_id": checkpoint.id},
        )
        session.active_worker_ip = None
        self.store.save_session(session)

        # Update logical agent lifecycle in registry
        agent_id = session.metadata.get("agent_id")
        if agent_id:
            try:
                self.registry.update_lifecycle(agent_id, AgentLifecycleState.SUSPENDED)
            except Exception as e:
                logger.warning(f"Could not update agent lifecycle on suspend: {e}")

        if idempotency_key:
            self.store.record_idempotency(idempotency_key, session.to_dict())

        return session

    def resume_session(
        self,
        session_id: str,
        reason: str = "Operator requested resume",
        actor: str = "operator",
        idempotency_key: Optional[str] = None,
    ) -> ResearchSession:
        """Resumes a suspended session onto an available worker."""
        if idempotency_key:
            cached = self.store.check_idempotency(idempotency_key)
            if cached:
                return ResearchSession.from_dict(cached)

        session = self.get_session(session_id, sync=True)
        if not session:
            raise OrchestratorError(f"Session '{session_id}' not found")

        if session.status == SessionStatus.RUNNING:
            logger.info(f"Session '{session_id}' is already running")
            return session

        if not session.active_task_id:
            raise OrchestratorError(f"Session '{session_id}' has no active task to resume")

        # Transition: SUSPENDED -> RESUMING
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.RESUMING,
            reason=reason,
            actor=actor,
        )
        self.store.save_session(session)

        # Execute AX resume
        try:
            self.ax.resume_task(session.active_task_id, atespace=session.atespace)
        except Exception as e:
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.FAILED,
                reason=f"Failed to resume AX task: {e}",
                actor=actor,
            )
            self.store.save_session(session)
            raise OrchestratorError(f"AX resume failed: {e}") from e

        # Wait briefly for AX status update
        time.sleep(1)

        # Transition: RESUMING -> RUNNING
        LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.RUNNING,
            reason="Actor restored from snapshot onto available worker",
            actor=actor,
        )
        self.sync_session_state(session)
        self.store.save_session(session)

        # Update logical agent lifecycle in registry
        agent_id = session.metadata.get("agent_id")
        if agent_id:
            try:
                self.registry.update_lifecycle(agent_id, AgentLifecycleState.ACTIVE)
            except Exception as e:
                logger.warning(f"Could not update agent lifecycle on resume: {e}")

        if idempotency_key:
            self.store.record_idempotency(idempotency_key, session.to_dict())

        return session

    def delete_session(self, session_id: str) -> bool:
        session = self.get_session(session_id, sync=False)
        if not session:
            return False

        if session.active_task_id:
            try:
                self.ax.delete_task(session.active_task_id, atespace=session.atespace)
            except Exception as e:
                logger.warning(f"Error deleting AX task for session '{session_id}': {e}")

        return self.store.delete_session(session_id)

    def read_session_artifact(self, session_id: str, relative_path: str = "report.md") -> Optional[str]:
        session = self.get_session(session_id, sync=True)
        if not session or not session.active_task_id:
            return None

        file_path = f"/workspace/{relative_path}"
        try:
            code, stdout, stderr = self.ax.exec_task(
                session.active_task_id,
                ["cat", file_path],
                atespace=session.atespace,
            )
            if code == 0 and stdout:
                return stdout
        except Exception:
            pass

        return self._read_artifact_from_snapshot(session.active_task_id, relative_path)

    def list_session_artifacts(self, session_id: str) -> List[str]:
        session = self.get_session(session_id, sync=False)
        if not session or not session.active_task_id:
            return []

        # If task is running, attempt to list via ax exec_task
        try:
            code, stdout, stderr = self.ax.exec_task(
                session.active_task_id,
                ["find", "/workspace", "-maxdepth", "3", "-type", "f"],
                atespace=session.atespace,
            )
            if code == 0 and stdout:
                lines = [line.strip().replace("/workspace/", "") for line in stdout.splitlines() if line.strip()]
                filtered = [l for l in lines if not l.startswith(".")]
                if filtered:
                    return filtered
        except Exception:
            pass

        # Fallback default known workspace structure
        return [
            "research/checkpoint-marker.txt",
            "research/session.json",
            "research/findings.md",
            "research/progress.md",
            "report.md",
        ]

    def _read_artifact_from_snapshot(self, task_name: str, relative_path: str) -> Optional[str]:
        """Directly extracts file from the RustFS S3 durable snapshot archive."""
        import subprocess, io, tarfile, json
        try:
            # Get the exact snapshotUri from the actor status
            actor_cmd = [
                "kubectl", "exec", "-n", "ax-system", "deploy/ax-toolbox", "--",
                "kubectl-ate", "get", "actor", task_name, "-a", "default", "-o", "json"
            ]
            actor_res = subprocess.run(actor_cmd, capture_output=True, text=True, timeout=10)
            if actor_res.returncode == 0:
                actor_data = json.loads(actor_res.stdout)
                snapshot_uri = actor_data.get("status", {}).get("externalSnapshot", {}).get("snapshotUri", "")
                if snapshot_uri.startswith("s3://ate-snapshots"):
                    xl_path = snapshot_uri.replace("s3://ate-snapshots", "/data/ate-snapshots") + "/durable-dir.tar.zstd/xl.meta"
                else:
                    xl_path = ""
            else:
                xl_path = ""

            if not xl_path:
                # Fallback to search
                cmd = [
                    "kubectl", "exec", "-n", "ate-system", "deploy/rustfs", "--",
                    "sh", "-c",
                    "find /data/ate-snapshots/atespaces/default/actors/ -name 'xl.meta' | grep durable-dir | sort -r | head -n 1"
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if res.returncode != 0 or not res.stdout.strip():
                    return None
                xl_path = res.stdout.strip()

            cat_cmd = ["kubectl", "exec", "-n", "ate-system", "deploy/rustfs", "--", "cat", xl_path]
            cat_res = subprocess.run(cat_cmd, capture_output=True, timeout=15)
            if cat_res.returncode != 0:
                return None

            raw_meta = cat_res.stdout
            magic = b"\x28\xb5\x2f\xfd"
            idx = raw_meta.find(magic)
            if idx == -1:
                return None

            zstd_proc = subprocess.run(["zstd", "-d"], input=raw_meta[idx:], capture_output=True, timeout=10)
            if zstd_proc.returncode != 0:
                return None

            tar_stream = io.BytesIO(zstd_proc.stdout[24:])
            with tarfile.open(fileobj=tar_stream) as tar:
                target_name = f"workspace/{relative_path.lstrip('/')}"
                for member in tar.getmembers():
                    if member.name == target_name:
                        f = tar.extractfile(member)
                        if f:
                            return f.read().decode("utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"Failed to read artifact from snapshot: {e}")
        return None

    def create_branch(self, request: BranchRequest) -> ExecutionBranch:
        """Forks a verified checkpoint into an independent execution branch."""
        return self.branching_controller.create_branch(request)

    def list_branches(
        self,
        session_id: Optional[str] = None,
        parent_checkpoint_id: Optional[str] = None,
    ) -> List[ExecutionBranch]:
        """Lists branches for a research session or parent checkpoint."""
        return self.store.list_branches(session_id=session_id, parent_checkpoint_id=parent_checkpoint_id)

    def get_branch(self, branch_id: str) -> Optional[ExecutionBranch]:
        """Retrieves branch by id."""
        return self.store.get_branch(branch_id)

    def get_lineage(self, session_id: str) -> BranchLineage:
        """Retrieves complete checkpoint and branch lineage DAG."""
        return self.branching_controller.get_lineage(session_id)

    def run_speculative_execution(
        self,
        checkpoint_id: str,
        caller_identity_token: str,
        source_scope_token: str,
        branch_specs: List[Dict[str, Any]],
        scoring_config: Optional[ScoringConfig] = None,
        auto_promote: bool = True,
    ) -> Tuple[EvaluationMatrix, Optional[PromotionResult]]:
        """Orchestrates parallel branch creation, execution, evaluation, and winner promotion."""
        return self.speculative_controller.run_speculative_execution(
            checkpoint_id=checkpoint_id,
            caller_identity_token=caller_identity_token,
            source_scope_token=source_scope_token,
            branch_specs=branch_specs,
            scoring_config=scoring_config,
            auto_promote=auto_promote,
        )

    def promote_branch(
        self,
        session_id: str,
        winning_branch_id: str,
        winning_checkpoint_id: str,
        evaluation_id: Optional[str] = None,
        operator: str = "orchestrator",
    ) -> PromotionResult:
        """Promotes a winning branch checkpoint to Primary HEAD."""
        return self.speculative_controller.promoter.promote_branch(
            session_id=session_id,
            winning_branch_id=winning_branch_id,
            winning_checkpoint_id=winning_checkpoint_id,
            evaluation_id=evaluation_id,
            operator=operator,
        )

    def get_session_head(self, session_id: str) -> Optional[str]:
        """Returns the current Primary HEAD checkpoint ID for a session."""
        return self.store.get_session_head(session_id)

    def list_evaluations(
        self,
        session_id: Optional[str] = None,
        parent_checkpoint_id: Optional[str] = None,
    ) -> List[EvaluationMatrix]:
        """Lists evaluation matrices for a session or parent checkpoint."""
        return self.store.list_evaluations(session_id=session_id, parent_checkpoint_id=parent_checkpoint_id)

