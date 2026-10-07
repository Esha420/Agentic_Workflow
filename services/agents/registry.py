"""
services/agents/registry.py — Authoritative Logical Agent Registry Service
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from domain.agents.models import Agent, AgentLifecycleState
from adapters.storage.metadata_store import MetadataStoreInterface, SQLiteMetadataStore

logger = logging.getLogger("agent-lab.services.agents")


class AgentRegistryError(Exception):
    pass


class AgentRegistryService:
    """
    Authoritative directory of logical agents in Agent Lab.
    Represents logical agent identity, tenant, capabilities, and lifecycle states,
    completely decoupled from physical execution workers.
    """

    def __init__(self, metadata_store: Optional[MetadataStoreInterface] = None):
        self.store = metadata_store or SQLiteMetadataStore()

    def register_agent(
        self,
        agent_id: str,
        role: str,
        tenant: str = "default",
        environment: str = "staging",
        capabilities: Optional[List[str]] = None,
        identity_subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Agent:
        existing = self.store.get_agent(agent_id)
        if existing:
            raise AgentRegistryError(f"Agent with id '{agent_id}' is already registered")

        subject = identity_subject or f"agent:{agent_id}"

        agent = Agent(
            agent_id=agent_id,
            role=role,
            tenant=tenant,
            environment=environment,
            capabilities=capabilities or [],
            identity_subject=subject,
            lifecycle_state=AgentLifecycleState.REGISTERED,
            metadata=metadata or {},
        )
        self.store.save_agent(agent)
        logger.info(f"Registered logical agent '{agent_id}' with subject '{subject}'")
        return agent

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        return self.store.get_agent(agent_id)

    def get_agent_by_subject(self, subject: str) -> Optional[Agent]:
        all_agents = self.store.list_agents()
        for a in all_agents:
            if a.identity_subject == subject:
                return a
        return None

    def list_agents(
        self,
        role: Optional[str] = None,
        tenant: Optional[str] = None,
        lifecycle_state: Optional[AgentLifecycleState] = None,
    ) -> List[Agent]:
        return self.store.list_agents(role=role, tenant=tenant, lifecycle_state=lifecycle_state)

    def update_lifecycle(
        self,
        agent_id: str,
        state: AgentLifecycleState,
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> Agent:
        agent = self.store.get_agent(agent_id)
        if not agent:
            raise AgentRegistryError(f"Agent '{agent_id}' not found")

        agent.update_lifecycle(state, metadata_updates=metadata_updates)
        self.store.save_agent(agent)
        logger.info(f"Agent '{agent_id}' transitioned to lifecycle state '{state.value}'")
        return agent

    def bind_execution(
        self,
        agent_id: str,
        task_id: str,
        workspace_id: str,
        session_id: Optional[str] = None,
    ) -> Agent:
        agent = self.store.get_agent(agent_id)
        if not agent:
            raise AgentRegistryError(f"Agent '{agent_id}' not found")

        agent.bind_execution(task_id=task_id, workspace_id=workspace_id, session_id=session_id)
        self.store.save_agent(agent)
        logger.info(f"Agent '{agent_id}' bound to task '{task_id}', workspace '{workspace_id}'")
        return agent

    def delete_agent(self, agent_id: str) -> bool:
        return self.store.delete_agent(agent_id)
