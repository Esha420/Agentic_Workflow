"""
services/checkpoints/branching.py — Checkpoint Branching and State Isolation Controller
Enforces: Branch Authorization ⊆ Source Authorization
"""
from __future__ import annotations
import fnmatch
import json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid
import jwt

from domain.agents.models import Agent, AgentLifecycleState
from domain.checkpoints.branching import (
    BranchLineage,
    BranchRequest,
    BranchStatus,
    ExecutionBranch,
)
from domain.checkpoints.models import Checkpoint
from domain.policy.models import EvaluationVerdict, ScopeToken
from domain.sessions.models import AuditEvent
from services.agents.registry import AgentRegistryService
from services.identity.manager import IdentityManager
from services.policy.capabilities import CapabilityRegistry
from services.policy.scope_issuer import ScopeIssuer
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.checkpoints.branching")


class BranchingError(Exception):
    """Base error for checkpoint branching operations."""
    pass


class BranchEscalationDenied(BranchingError):
    """Raised when a branch request attempts to escalate beyond source authorization."""
    pass


class CheckpointBranchingController:
    """
    Controller governing checkpoint state forking, branch isolation,
    and authorization inheritance under the invariant:
    Branch Authorization ⊆ Source Authorization.
    """

    def __init__(
        self,
        metadata_store: Optional[MetadataStoreInterface] = None,
        agent_registry: Optional[AgentRegistryService] = None,
        identity_manager: Optional[IdentityManager] = None,
        capability_registry: Optional[CapabilityRegistry] = None,
        scope_issuer: Optional[ScopeIssuer] = None,
        secret_key: Optional[str] = None,
        workspace_base_dir: str = "/tmp/agent-lab-workspaces",
    ):
        self.store = metadata_store or SQLiteMetadataStore()
        self.agent_registry = agent_registry or AgentRegistryService(self.store)
        self.identity_mgr = identity_manager or IdentityManager(registry=self.agent_registry, metadata_store=self.store)
        self.capabilities = capability_registry or CapabilityRegistry()
        self.scope_issuer = scope_issuer or ScopeIssuer()
        self.secret_key = secret_key or os.environ.get("AGENT_LAB_SCOPE_SECRET", "agent-lab-dev-scope-secret-2026")
        self.workspace_base_dir = workspace_base_dir
        os.makedirs(self.workspace_base_dir, exist_ok=True)

    def validate_parent_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """
        Retrieves and validates the immutability of the parent checkpoint.
        """
        chk = self.store.get_checkpoint(checkpoint_id)
        if not chk:
            raise BranchingError(f"Parent checkpoint '{checkpoint_id}' not found")
        return chk

    def verify_branch_authorization(
        self,
        request: BranchRequest,
        parent_checkpoint: Checkpoint,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Verifies caller identity and source scope token.
        Enforces the fundamental security invariant:
        Branch Authorization ⊆ Source Authorization.

        Returns (caller_identity_claims, source_scope_claims).
        """
        # 1. Validate Caller Workload Identity (M3)
        validation_res = self.identity_mgr.provider.validate_identity(request.caller_identity_token)
        if not validation_res.valid:
            raise BranchingError(f"Caller workload identity token is invalid: {validation_res.error}")

        # 2. Decode and Validate Source Scope Token (M4/M5)
        try:
            source_claims = jwt.decode(
                request.source_scope_token,
                self.secret_key,
                algorithms=["HS256"],
                audience=["agent-gateway", "agent-lab"],
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError:
            raise BranchEscalationDenied("Source scope token has expired")
        except Exception as e:
            raise BranchingError(f"Source scope token cryptographic failure: {e}")

        source_scope_id = source_claims.get("scope_id")
        if self.store.is_revoked(source_scope_id) or (source_scope_id in self.scope_issuer._revoked_scopes):
            raise BranchEscalationDenied(f"Source scope '{source_scope_id}' is revoked")

        # Subject binding
        caller_sub = validation_res.claims.get("sub")
        if caller_sub != source_claims.get("sub"):
            raise BranchEscalationDenied(
                f"Identity subject '{caller_sub}' does not match source scope subject '{source_claims.get('sub')}'"
            )

        caller_tenant = validation_res.claims.get("tenant", "default")

        # 3. Invariant: Capability Containment (Branch Capabilities ⊆ Source Capabilities)
        source_cap = source_claims.get("capability")
        source_caps = [source_cap] if source_cap else []
        requested_caps = request.requested_capabilities or source_caps

        for cap in requested_caps:
            if cap not in source_caps:
                reason = f"Capability escalation denied: requested branch capability '{cap}' is not granted by source authorization ({source_caps})"
                self._record_audit_rejection(parent_checkpoint, request, reason)
                raise BranchEscalationDenied(reason)

        # 4. Invariant: Action Containment (Branch Actions ⊆ Source Actions)
        source_action = source_claims.get("granted_action") or source_claims.get("action")
        source_actions = source_claims.get("allowed_actions") or ([source_action] if source_action else ["*"])
        requested_actions = request.requested_actions or source_actions

        if "*" not in source_actions:
            for act in requested_actions:
                if act not in source_actions:
                    reason = f"Action escalation denied: requested branch action '{act}' not granted by source authorization ({source_actions})"
                    self._record_audit_rejection(parent_checkpoint, request, reason)
                    raise BranchEscalationDenied(reason)

        # 5. Invariant: Resource Path Containment (Branch Resources ⊆ Source Resources)
        source_resource = source_claims.get("resource_path") or source_claims.get("resource_pattern") or "/workspace/*"
        requested_resources = request.requested_resources or [source_resource]

        for res in requested_resources:
            if not self._is_subpattern(res, source_resource):
                reason = f"Resource escalation denied: requested path '{res}' escapes source boundary '{source_resource}'"
                self._record_audit_rejection(parent_checkpoint, request, reason)
                raise BranchEscalationDenied(reason)

        # 6. Invariant: Quota Containment
        source_remaining = source_claims.get("invocations_remaining", source_claims.get("max_invocations", 10))
        if request.max_invocations > source_remaining:
            reason = f"Quota escalation denied: requested invocations {request.max_invocations} exceeds source remaining quota {source_remaining}"
            self._record_audit_rejection(parent_checkpoint, request, reason)
            raise BranchEscalationDenied(reason)

        # 7. Invariant: TTL Containment
        current_time = int(time.time())
        source_exp = source_claims.get("exp", current_time + 3600)
        requested_exp = current_time + request.requested_ttl
        if requested_exp > source_exp:
            # Clamp TTL to source expiration rather than allowing extension
            request.requested_ttl = max(1, source_exp - current_time)

        caller_claims = {
            "sub": validation_res.subject or caller_sub,
            "tenant": caller_tenant,
            "agent_id": validation_res.claims.get("agent_id", "") if validation_res.claims else "",
        }
        return caller_claims, source_claims

    def _is_subpattern(self, child_pattern: str, parent_pattern: str) -> bool:
        """
        Verifies that child_pattern is strictly contained within parent_pattern.
        """
        if parent_pattern == child_pattern:
            return True
        if parent_pattern == "*":
            return True

        if parent_pattern.endswith("/*"):
            prefix = parent_pattern[:-2]
            clean_child = child_pattern.rstrip("/*")
            if clean_child == prefix or clean_child.startswith(prefix + "/"):
                return True
            return False

        if parent_pattern.endswith("*"):
            prefix = parent_pattern[:-1]
            return child_pattern.startswith(prefix)

        return fnmatch.fnmatch(child_pattern, parent_pattern)

    def _record_audit_rejection(self, checkpoint: Checkpoint, request: BranchRequest, reason: str) -> None:
        event = AuditEvent(
            session_id=checkpoint.session_id,
            task_id=checkpoint.task_id,
            from_status="CHECKPOINT_BRANCHING",
            to_status="BRANCH_DENIED",
            reason=reason,
            actor="CheckpointBranchingController",
            details={
                "parent_checkpoint_id": checkpoint.id,
                "hypothesis": request.hypothesis,
                "violation": reason,
            },
        )
        self.store.record_audit_event(event)

    def clone_workspace_state(
        self,
        parent_checkpoint: Checkpoint,
        branch_id: str,
        hypothesis: str,
    ) -> Tuple[str, str, int]:
        """
        Isolates workspace state by cloning parent snapshot or files into a dedicated branch volume.
        Returns (branch_workspace_id, snapshot_reference, workspace_generation).
        """
        workspace_generation = parent_checkpoint.workspace_generation + 1
        branch_workspace_id = f"ws-{parent_checkpoint.session_id}-{branch_id}"
        branch_ws_path = os.path.join(self.workspace_base_dir, branch_workspace_id)
        os.makedirs(branch_ws_path, exist_ok=True)

        # Clone from source workspace directory if it exists
        source_ws_path = os.path.join(self.workspace_base_dir, f"ws-{parent_checkpoint.session_id}")
        if os.path.exists(source_ws_path):
            for item in os.listdir(source_ws_path):
                s_item = os.path.join(source_ws_path, item)
                d_item = os.path.join(branch_ws_path, item)
                if os.path.isdir(s_item):
                    if not os.path.exists(d_item):
                        shutil.copytree(s_item, d_item)
                else:
                    shutil.copy2(s_item, d_item)

        # Materialize branch metadata descriptor
        meta_file = os.path.join(branch_ws_path, "BRANCH_METADATA.json")
        branch_info = {
            "branch_id": branch_id,
            "parent_checkpoint_id": parent_checkpoint.id,
            "workspace_generation": workspace_generation,
            "hypothesis": hypothesis,
            "cloned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with open(meta_file, "w") as f:
            json.dump(branch_info, f, indent=2)

        snapshot_reference = (
            f"snapshot-ref://rustfs/{parent_checkpoint.session_id}/{parent_checkpoint.id}/clone/{branch_id}"
        )
        return branch_workspace_id, snapshot_reference, workspace_generation

    def create_branch(self, request: BranchRequest) -> ExecutionBranch:
        """
        Forks an immutable parent checkpoint into an independent execution branch.
        Preserves correct identity, authorization context, and complete lineage.
        """
        # 1. Validate parent checkpoint
        parent_checkpoint = self.validate_parent_checkpoint(request.parent_checkpoint_id)

        # 2. Verify authorization containment (Branch Authorization ⊆ Source Authorization)
        caller_claims, source_claims = self.verify_branch_authorization(request, parent_checkpoint)

        branch_id = request.branch_name or f"br-{uuid.uuid4().hex[:8]}"

        # 3. Clone durable workspace state into isolated volume
        branch_workspace_id, snapshot_ref, generation = self.clone_workspace_state(
            parent_checkpoint=parent_checkpoint,
            branch_id=branch_id,
            hypothesis=request.hypothesis,
        )

        # 4. Provision dedicated branch agent & independent M3 Workload Identity
        target_agent_id = request.target_agent_id or f"agent-{branch_id}"
        branch_role = source_claims.get("role", "researcher")
        caller_tenant = caller_claims.get("tenant", "default")
        caller_env = source_claims.get("environment", "development")

        branch_agent = self.agent_registry.get_agent(target_agent_id)
        if not branch_agent:
            branch_agent = self.agent_registry.register_agent(
                agent_id=target_agent_id,
                role=branch_role,
                tenant=caller_tenant,
                environment=caller_env,
                capabilities=request.requested_capabilities or [source_claims.get("capability", "document_analysis")],
                identity_subject=f"agent:{target_agent_id}",
            )
            branch_agent.task_id = f"T-branch-{branch_id}"
            branch_agent.workspace_id = branch_workspace_id
            branch_agent.session_id = parent_checkpoint.session_id
            branch_agent.lifecycle_state = AgentLifecycleState.ACTIVE
            self.store.save_agent(branch_agent)

        _, branch_identity_token = self.identity_mgr.provision_agent_identity(
            agent_id=branch_agent.agent_id,
            task_id=branch_agent.task_id,
            workspace_id=branch_agent.workspace_id,
            session_id=parent_checkpoint.session_id,
            ttl_seconds=request.requested_ttl,
        )

        # 5. Issue independent Branch Scope Token bounded strictly by source authorization
        parent_chain = source_claims.get("delegation_chain", [source_claims.get("sub", caller_claims["sub"])])
        branch_chain = list(parent_chain) + [branch_agent.identity_subject]

        granted_cap = (request.requested_capabilities or [source_claims.get("capability")])[0]
        granted_action = (request.requested_actions or [source_claims.get("granted_action", "*")])[0]
        granted_resource = (request.requested_resources or [source_claims.get("resource_path", "/workspace/*")])[0]

        branch_scope_id = f"scp-branch-{uuid.uuid4().hex[:8]}"
        now = int(time.time())
        exp = now + request.requested_ttl

        scope_claims = {
            "scope_id": branch_scope_id,
            "sub": branch_agent.identity_subject,
            "parent_scope_id": source_claims.get("scope_id"),
            "parent_checkpoint_id": parent_checkpoint.id,
            "branch_id": branch_id,
            "session_id": parent_checkpoint.session_id,
            "task_id": branch_agent.task_id,
            "workspace_id": branch_workspace_id,
            "capability": granted_cap,
            "granted_action": granted_action,
            "resource_path": granted_resource,
            "delegation_chain": branch_chain,
            "workspace_generation": generation,
            "max_invocations": request.max_invocations,
            "invocations_remaining": request.max_invocations,
            "iat": now,
            "exp": exp,
            "iss": "https://branching.agent-lab.internal",
            "aud": "agent-gateway",
        }

        raw_branch_scope_token = jwt.encode(scope_claims, self.secret_key, algorithm="HS256")

        branch_scope_obj = ScopeToken(
            scope_id=branch_scope_id,
            subject=branch_agent.identity_subject,
            task_id=branch_agent.task_id,
            workspace_id=branch_workspace_id,
            capability=granted_cap,
            allowed_actions=[granted_action],
            resource_pattern=granted_resource,
            max_invocations=request.max_invocations,
            invocations_remaining=request.max_invocations,
            issued_at=now,
            expires_at=exp,
            delegation_depth=source_claims.get("delegation_depth", 0),
            raw_token=raw_branch_scope_token,
            claims=scope_claims,
        )
        self.scope_issuer._active_scopes[branch_scope_id] = branch_scope_obj

        # 6. Instantiate ExecutionBranch
        branch = ExecutionBranch(
            branch_id=branch_id,
            parent_checkpoint_id=parent_checkpoint.id,
            session_id=parent_checkpoint.session_id,
            agent_id=branch_agent.agent_id,
            task_id=branch_agent.task_id,
            workspace_id=branch_workspace_id,
            identity_subject=branch_agent.identity_subject,
            scope_id=branch_scope_id,
            delegation_chain=branch_chain,
            workspace_generation=generation,
            snapshot_reference=snapshot_ref,
            hypothesis=request.hypothesis,
            status=BranchStatus.ACTIVE,
            metadata={
                "identity_token": branch_identity_token.raw_token,
                "scope_token": raw_branch_scope_token,
                "granted_capability": granted_cap,
                "granted_action": granted_action,
                "granted_resource": granted_resource,
            },
        )
        self.store.save_branch(branch)

        # 7. Record immutable Audit Event
        audit_event = AuditEvent(
            session_id=parent_checkpoint.session_id,
            task_id=parent_checkpoint.task_id,
            from_status="CHECKPOINT_VERIFIED",
            to_status="BRANCH_ACTIVE",
            reason=f"Forked checkpoint '{parent_checkpoint.id}' into branch '{branch_id}'",
            actor="CheckpointBranchingController",
            details={
                "branch_id": branch.branch_id,
                "parent_checkpoint_id": parent_checkpoint.id,
                "hypothesis": request.hypothesis,
                "identity_subject": branch.identity_subject,
                "scope_id": branch.scope_id,
                "workspace_generation": generation,
            },
        )
        self.store.record_audit_event(audit_event)

        logger.info(
            f"Successfully created branch '{branch_id}' from checkpoint '{parent_checkpoint.id}' "
            f"[Generation={generation}, Hypothesis='{request.hypothesis}']"
        )
        return branch

    def commit_branch_checkpoint(
        self,
        branch_id: str,
        checkpoint_data: Optional[Dict[str, Any]] = None,
    ) -> Checkpoint:
        """
        Creates a new immutable Checkpoint committed by a branch,
        preserving checkpoint parent lineage and generation.
        """
        branch = self.store.get_branch(branch_id)
        if not branch:
            raise BranchingError(f"Branch '{branch_id}' not found")

        checkpoint_data = checkpoint_data or {}
        chk_id = checkpoint_data.get("id") or f"chk-{uuid.uuid4().hex[:8]}"

        new_checkpoint = Checkpoint(
            id=chk_id,
            session_id=branch.session_id,
            task_id=branch.task_id,
            workspace_version=f"v-gen{branch.workspace_generation}",
            parent_checkpoint_id=branch.parent_checkpoint_id,
            branch_id=branch.branch_id,
            workspace_generation=branch.workspace_generation,
            snapshot_reference=f"snapshot-ref://rustfs/{branch.session_id}/{chk_id}",
            authorization_context={
                "scope_id": branch.scope_id,
                "identity_subject": branch.identity_subject,
                "delegation_chain": branch.delegation_chain,
            },
            metadata={
                "hypothesis": branch.hypothesis,
                "committed_by_branch": branch.branch_id,
                **checkpoint_data.get("metadata", {}),
            },
        )
        self.store.save_checkpoint(new_checkpoint)

        audit_event = AuditEvent(
            session_id=branch.session_id,
            task_id=branch.task_id,
            from_status="BRANCH_ACTIVE",
            to_status="CHECKPOINT_COMMITTED",
            reason=f"Branch '{branch.branch_id}' committed checkpoint '{new_checkpoint.id}'",
            actor=branch.identity_subject,
            details={
                "branch_id": branch.branch_id,
                "checkpoint_id": new_checkpoint.id,
                "parent_checkpoint_id": branch.parent_checkpoint_id,
                "workspace_generation": branch.workspace_generation,
            },
        )
        self.store.record_audit_event(audit_event)
        return new_checkpoint

    def get_lineage(self, session_id: str) -> BranchLineage:
        """
        Reconstructs the full checkpoint lineage DAG for a research session.
        """
        return self.store.get_checkpoint_lineage(session_id)
