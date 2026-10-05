"""
domain/workspaces/models.py — Workspace resource model
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class GitRepoRef:
    url: str
    branch: str = "main"
    mount_path: str = "/workspace/source"


@dataclass
class MCPServerRef:
    name: str
    url: str
    transport: str = "sse"


@dataclass
class Workspace:
    id: str
    session_id: str
    atespace: str = "default"
    mount_path: str = "/workspace"
    git_repos: List[GitRepoRef] = field(default_factory=list)
    mcp_servers: List[MCPServerRef] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Workspace:
        data = dict(data)
        if "git_repos" in data:
            data["git_repos"] = [
                GitRepoRef(**r) if isinstance(r, dict) else r for r in data["git_repos"]
            ]
        if "mcp_servers" in data:
            data["mcp_servers"] = [
                MCPServerRef(**s) if isinstance(s, dict) else s for s in data["mcp_servers"]
            ]
        return cls(**data)
