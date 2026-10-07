"""
services/policy/engine.py — Contextual Intersection Policy Engine
"""
from __future__ import annotations
import fnmatch
import logging
from typing import Any, Dict, List, Optional
from domain.policy.models import (
    Capability,
    PolicyRule,
    RuleEffect,
    EvaluationVerdict,
    AuthorizationRequest,
    PolicyEvaluationResult,
)
from services.policy.capabilities import CapabilityRegistry
from services.identity.manager import IdentityManager
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.policy.engine")


class PolicyEngine:
    """
    Evaluates dynamic authorization at invocation time using the Contextual Intersection Model:
    Effective Scope = Evaluate(Identity ∩ Task Context ∩ Workspace Context ∩ Capability ∩ Delegation ∩ Policy)
    """

    def __init__(
        self,
        capability_registry: Optional[CapabilityRegistry] = None,
        identity_manager: Optional[IdentityManager] = None,
        metadata_store: Optional[MetadataStoreInterface] = None,
    ):
        self.capabilities = capability_registry or CapabilityRegistry()
        self.store = metadata_store or SQLiteMetadataStore()
        self.identity_mgr = identity_manager or IdentityManager(metadata_store=self.store)
        self._rules: List[PolicyRule] = []
        self._init_default_rules()

    def _init_default_rules(self) -> None:
        self._rules = [
            PolicyRule(
                rule_id="rule-research-collaboration",
                name="Research Agent Collaboration Allowance",
                effect=RuleEffect.ALLOW,
                target_roles=["research-agent", "reviewer-agent"],
                target_capabilities=["web_research", "document_analysis", "repo_read", "code_review"],
                target_tenants=["*"],
                target_environments=["staging", "dev", "default"],
            ),
            PolicyRule(
                rule_id="rule-deny-production-mutation",
                name="Deny Direct Production Deployment from Research Agents",
                effect=RuleEffect.DENY,
                target_roles=["research-agent", "coder-agent"],
                target_capabilities=["prod_deploy"],
                target_tenants=["*"],
                target_environments=["*"],
            ),
        ]

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.insert(0, rule)  # prepend to evaluate in order

    def evaluate(self, request: AuthorizationRequest) -> PolicyEvaluationResult:
        """
        Executes strict 6-dimensional fail-closed intersection evaluation.
        """
        # ======================================================================
        # 1. Identity Dimension (Milestone 3 Cryptographic Verification)
        # ======================================================================
        val_result = self.identity_mgr.verify_workload_token(
            token=request.identity_token,
            expected_task_id=request.task_id,
            expected_workspace_id=request.workspace_id,
        )
        if not val_result.valid:
            return PolicyEvaluationResult(
                verdict=EvaluationVerdict.DENIED,
                reason=f"Identity verification failed: {val_result.error}",
            )

        claims = val_result.claims or {}
        subject = claims.get("sub", "")
        role = claims.get("role", "")
        tenant = claims.get("tenant", "default")
        environment = claims.get("environment", request.environment)

        # ======================================================================
        # 2. Task Context Invariant
        # ======================================================================
        if claims.get("task_id") != request.task_id:
            return PolicyEvaluationResult(
                verdict=EvaluationVerdict.DENIED,
                reason=f"Task context mismatch: token bound to '{claims.get('task_id')}', requested '{request.task_id}'",
            )

        # ======================================================================
        # 3. Workspace Boundary Invariant
        # ======================================================================
        if claims.get("workspace_id") != request.workspace_id:
            return PolicyEvaluationResult(
                verdict=EvaluationVerdict.DENIED,
                reason=f"Workspace context mismatch: token bound to '{claims.get('workspace_id')}', requested '{request.workspace_id}'",
            )

        # ======================================================================
        # 4. Capability & Role Dimension
        # ======================================================================
        cap = self.capabilities.get_capability(request.requested_capability)
        if not cap:
            return PolicyEvaluationResult(
                verdict=EvaluationVerdict.DENIED,
                reason=f"Unknown capability '{request.requested_capability}'",
            )

        if not cap.is_role_allowed(role):
            return PolicyEvaluationResult(
                verdict=EvaluationVerdict.DENIED,
                reason=f"Role '{role}' is not authorized for capability '{cap.name}'",
            )

        # ======================================================================
        # 5. Action & Resource Path Boundaries
        # ======================================================================
        if not cap.is_action_allowed(request.requested_action):
            return PolicyEvaluationResult(
                verdict=EvaluationVerdict.DENIED,
                reason=f"Action '{request.requested_action}' is not permissible under capability '{cap.name}'",
            )

        if not cap.is_resource_allowed(request.target_resource):
            return PolicyEvaluationResult(
                verdict=EvaluationVerdict.DENIED,
                reason=f"Resource path '{request.target_resource}' violates capability boundary '{cap.resource_path_pattern}'",
            )

        # ======================================================================
        # 6. Delegation Authority & Policy Rules
        # ======================================================================
        if request.delegation_depth > cap.max_delegation_depth:
            return PolicyEvaluationResult(
                verdict=EvaluationVerdict.DENIED,
                reason=f"Delegation depth {request.delegation_depth} exceeds capability maximum {cap.max_delegation_depth}",
            )

        # Evaluate Policy Rules (Explicit DENY always wins)
        matched_allow_rule: Optional[PolicyRule] = None
        for rule in self._rules:
            if rule.matches(role=role, capability=cap.name, tenant=tenant, environment=environment):
                if rule.effect == RuleEffect.DENY:
                    return PolicyEvaluationResult(
                        verdict=EvaluationVerdict.DENIED,
                        reason=f"Explicitly denied by policy rule '{rule.name}' ({rule.rule_id})",
                        rule_id=rule.rule_id,
                    )
                elif rule.effect == RuleEffect.ALLOW and not matched_allow_rule:
                    matched_allow_rule = rule

        if not matched_allow_rule:
            return PolicyEvaluationResult(
                verdict=EvaluationVerdict.DENIED,
                reason=f"Default-deny: No policy rule explicitly allows capability '{cap.name}' for role '{role}' in '{environment}'",
            )

        # ======================================================================
        # Compute Effective Scope (Intersection Granted)
        # ======================================================================
        effective_scope = {
            "subject": subject,
            "role": role,
            "tenant": tenant,
            "environment": environment,
            "task_id": request.task_id,
            "workspace_id": request.workspace_id,
            "capability": cap.name,
            "granted_action": request.requested_action,
            "allowed_actions": cap.allowed_actions,
            "resource_path": request.target_resource,
            "max_invocations": 10,
            "ttl_seconds": cap.default_ttl_seconds,

            "delegation_depth": request.delegation_depth,
            "target_agent": request.target_agent,
            "policy_rule": matched_allow_rule.rule_id,
        }

        return PolicyEvaluationResult(
            verdict=EvaluationVerdict.ALLOWED,
            reason=f"Granted via policy rule '{matched_allow_rule.name}'",
            rule_id=matched_allow_rule.rule_id,
            effective_scope=effective_scope,
        )
