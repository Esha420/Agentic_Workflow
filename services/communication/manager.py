"""
services/communication/manager.py — Multi-Agent Communication & Delegation Coordinator
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from domain.agents.models import Agent, AgentLifecycleState
from domain.delegation.models import DelegationRequest, DelegationResult, ChildScopeToken
from services.agents.registry import AgentRegistryService
from services.delegation.engine import DelegationEngine
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.communication.manager")


class CommunicationManager:
    """
    Coordinates inter-agent communication, peer discovery, and bounded capability delegation.
    Ensures all inter-agent operations comply with the Child Scope ⊆ Parent Scope invariant.
    """

    def __init__(
        self,
        delegation_engine: Optional[DelegationEngine] = None,
        agent_registry: Optional[AgentRegistryService] = None,
        metadata_store: Optional[MetadataStoreInterface] = None,
    ):
        self.store = metadata_store or SQLiteMetadataStore()
        self.agent_registry = agent_registry or AgentRegistryService(self.store)
        self.delegation_engine = delegation_engine or DelegationEngine(
            agent_registry=self.agent_registry,
            metadata_store=self.store,
        )

    def discover_peers(
        self,
        capability: str,
        tenant: str = "default",
        environment: str = "staging",
        exclude_agent_id: Optional[str] = None,
    ) -> List[Agent]:
        """
        Discovers active, eligible peer agents possessing a specified capability within the tenant boundary.
        """
        all_agents = self.agent_registry.list_agents(
            tenant=tenant,
            lifecycle_state=AgentLifecycleState.ACTIVE,
        )
        eligible: List[Agent] = []
        for ag in all_agents:
            if exclude_agent_id and ag.agent_id == exclude_agent_id:
                continue
            if ag.environment != environment:
                continue
            if capability in ag.capabilities or "*" in ag.capabilities:
                eligible.append(ag)
        return eligible

    def delegate(self, request: DelegationRequest) -> DelegationResult:
        """
        Submits a delegation request to the Delegation Engine.
        """
        return self.delegation_engine.delegate(request)

    def get_delegated_scope(self, scope_id: str) -> Optional[ChildScopeToken]:
        """
        Retrieves active child scope token with complete provenance metadata.
        """
        return self.delegation_engine._active_child_scopes.get(scope_id)
