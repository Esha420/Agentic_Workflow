"""
services/policy/capabilities.py — Authoritative Capability Registry
"""
from __future__ import annotations
import logging
import threading
from typing import Dict, List, Optional
from domain.policy.models import Capability

logger = logging.getLogger("agent-lab.services.policy.capabilities")


class CapabilityRegistry:
    """
    Authoritative catalog of typed capabilities supported across the Agent Lab platform.
    Defines allowed roles, actions, resource path patterns, and delegation bounds.
    """

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._lock = threading.Lock()
        self._init_defaults()

    def _init_defaults(self) -> None:
        defaults = [
            Capability(
                name="web_research",
                description="Perform live external search and documentation retrieval",
                allowed_roles=["research-agent", "lead-researcher"],
                allowed_actions=["fetch", "search", "summarize"],
                resource_path_pattern="/workspace/research/*",
                default_ttl_seconds=900,
                max_delegation_depth=1,
            ),
            Capability(
                name="document_analysis",
                description="Extract structured findings and synthesize document artifacts",
                allowed_roles=["research-agent", "reviewer-agent"],
                allowed_actions=["read", "analyze", "extract"],
                resource_path_pattern="/workspace/*",
                default_ttl_seconds=900,
                max_delegation_depth=1,
            ),
            Capability(
                name="repo_read",
                description="Read repository source trees and inspection trees",
                allowed_roles=["research-agent", "coder-agent", "reviewer-agent"],
                allowed_actions=["read", "search_code", "list_files"],
                resource_path_pattern="/workspace/*",
                default_ttl_seconds=1200,
                max_delegation_depth=1,
            ),
            Capability(
                name="code_review",
                description="Perform automated code inspection, comment, and review",
                allowed_roles=["reviewer-agent", "research-agent"],
                allowed_actions=["inspect", "comment", "approve"],
                resource_path_pattern="/workspace/*",
                default_ttl_seconds=900,
                max_delegation_depth=1,
            ),
            Capability(
                name="code_generation",
                description="Generate and refactor implementation code",
                allowed_roles=["coder-agent"],
                allowed_actions=["generate", "refactor", "patch"],
                resource_path_pattern="/workspace/*",
                default_ttl_seconds=600,
                max_delegation_depth=1,
            ),
            Capability(
                name="prod_deploy",
                description="High-privilege production infrastructure modification",
                allowed_roles=["deployment-admin"],
                allowed_actions=["deploy", "rollback"],
                resource_path_pattern="/workspace/deploy/*",
                default_ttl_seconds=300,
                max_delegation_depth=0,
            ),
        ]
        for cap in defaults:
            self._capabilities[cap.name] = cap

    def register_capability(self, capability: Capability) -> Capability:
        with self._lock:
            self._capabilities[capability.name] = capability
            logger.info(f"Registered capability '{capability.name}'")
            return capability

    def get_capability(self, name: str) -> Optional[Capability]:
        with self._lock:
            return self._capabilities.get(name)

    def list_capabilities(self) -> List[Capability]:
        with self._lock:
            return list(self._capabilities.values())

    def delete_capability(self, name: str) -> bool:
        with self._lock:
            if name in self._capabilities:
                del self._capabilities[name]
                return True
            return False
