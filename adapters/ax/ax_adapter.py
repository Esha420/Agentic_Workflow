"""
adapters/ax/ax_adapter.py — Typed interface and cluster implementation for AX
"""
from __future__ import annotations
import json
import logging
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from domain.tasks.models import Task, TaskPhase

logger = logging.getLogger("agent-lab.adapters.ax")


class AXAdapterError(Exception):
    """Base exception for AX Adapter operations."""
    pass


class AXAdapterInterface:
    """Abstract interface defining the control-plane contract with AX."""

    def apply_task(self, task_name: str, session_id: str, target: str, atespace: str = "default") -> Task:
        raise NotImplementedError

    def get_task(self, task_name: str, atespace: str = "default") -> Optional[Task]:
        raise NotImplementedError

    def list_tasks(self, atespace: str = "default") -> List[Task]:
        raise NotImplementedError

    def suspend_task(self, task_name: str, atespace: str = "default") -> bool:
        raise NotImplementedError

    def resume_task(self, task_name: str, atespace: str = "default") -> bool:
        raise NotImplementedError

    def delete_task(self, task_name: str, atespace: str = "default") -> bool:
        raise NotImplementedError

    def exec_task(self, task_name: str, command: List[str], atespace: str = "default") -> Tuple[int, str, str]:
        raise NotImplementedError


class ClusterAXAdapter(AXAdapterInterface):
    """
    Production-shaped adapter communicating with AX through the in-cluster ax-toolbox deployment.
    """

    def __init__(self, toolbox_deployment: str = "deploy/ax-toolbox", namespace: str = "ax-system"):
        self.toolbox_deployment = toolbox_deployment
        self.namespace = namespace

    def _run_ax(self, args: List[str], input_data: Optional[str] = None) -> Tuple[int, str, str]:
        cmd = ["kubectl", "exec"]
        if input_data is not None:
            cmd.append("-i")
        cmd.extend(["-n", self.namespace, self.toolbox_deployment, "--", "ax"])
        cmd.extend(args)

        try:
            result = subprocess.run(
                cmd,
                input=input_data,
                text=True,
                capture_output=True,
                timeout=30,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as e:
            raise AXAdapterError(f"AX command '{' '.join(args)}' timed out after 30s") from e
        except Exception as e:
            raise AXAdapterError(f"Failed to execute AX command: {e}") from e

    def apply_task(self, task_name: str, session_id: str, target: str, atespace: str = "default") -> Task:
        bootstrap_script = r"""set -e
WORKSPACE="${WORKSPACE:-/workspace}"
RESEARCH_DIR="$WORKSPACE/research"
MARKER_FILE="$RESEARCH_DIR/checkpoint-marker.txt"
SESSION_FILE="$RESEARCH_DIR/session.json"
PROGRESS_FILE="$RESEARCH_DIR/progress.md"
FINDINGS_FILE="$RESEARCH_DIR/findings.md"

mkdir -p "$RESEARCH_DIR"

if [ ! -f "$MARKER_FILE" ]; then
  UNIQUE_MARKER="marker-$(date +%s)-$RANDOM"
  echo "SESSION: $TASK_NAME" > "$MARKER_FILE"
  echo "PHASE: pre-suspension" >> "$MARKER_FILE"
  echo "CHECKPOINT_MARKER: $UNIQUE_MARKER" >> "$MARKER_FILE"
  echo "CREATED_AT: $(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "$MARKER_FILE"

  cat <<EOF > "$SESSION_FILE"
{
  "session_id": "$TASK_NAME",
  "phase": "pre-suspension",
  "checkpoint_marker": "$UNIQUE_MARKER",
  "target": "$TARGET"
}
EOF

  cat <<EOF > "$FINDINGS_FILE"
# Preliminary Research Findings: $TARGET
- Theorem 1: Checkpointed state in durable storage eliminates idle compute leakage.
- Theorem 2: Hardware-level gVisor snapshots retain process tree without user serialization.
- Status: Dispatched proof verification to external async worker.
EOF

  echo "# Research Progress: $TASK_NAME" > "$PROGRESS_FILE"
  echo "- Initialized session with marker: \`$UNIQUE_MARKER\`" >> "$PROGRESS_FILE"
  echo "[Pre-Suspension] Created research checkpoint marker: $UNIQUE_MARKER"
else
  PREV_MARKER=$(grep "CHECKPOINT_MARKER:" "$MARKER_FILE" | awk '{print $2}')
  echo "RESUMED: true" >> "$MARKER_FILE"
  echo "PREVIOUS_MARKER: $PREV_MARKER" >> "$MARKER_FILE"
  echo "RESUMED_AT: $(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "$MARKER_FILE"

  echo "" >> "$PROGRESS_FILE"
  echo "## Resumption Verified" >> "$PROGRESS_FILE"
  echo "- State restored from checkpoint marker: \`$PREV_MARKER\`" >> "$PROGRESS_FILE"
  echo "- Resumed timestamp: \`$(date -u +'%Y-%m-%dT%H:%M:%SZ')\`" >> "$PROGRESS_FILE"
  echo "[Resumption Continuity Verified] Successfully discovered previous marker: $PREV_MARKER"
fi

exec /bin/bash /agent/run_workload.sh
"""
        manifest = f"""apiVersion: ax.io/v1alpha1
kind: Task
metadata:
  name: {task_name}
  atespace: {atespace}
spec:
  image: "localhost:5001/openclaw-agent@sha256:3a00eb8df2f127b46e926dcea420ade1d46f8723b0ec7abb4b3610637569f7d9"
  command:
    - /bin/bash
    - -c
    - |
{self._indent(bootstrap_script, 6)}
  env:
    - name: ROLE
      value: "research"
    - name: TARGET
      value: "{target}"
    - name: SCAN_API_URL
      value: "http://172.18.0.4:8080"
    - name: MCP_URL
      value: "http://172.18.0.2:8000/mcp"
    - name: TASK_NAME
      value: "{task_name}"
    - name: WORKSPACE
      value: "/workspace"
    - name: SESSION_ID
      value: "{session_id}"
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://opentelemetry-collector.otel-system.svc.cluster.local:4318"
    - name: OTEL_SERVICE_NAME
      value: "agent-lab-researcher"
    - name: OTEL_EXPORTER_OTLP_PROTOCOL
      value: "http/protobuf"
  debug: true
"""
        code, stdout, stderr = self._run_ax(["apply", "-f", "-"], input_data=manifest)
        if code != 0:
            raise AXAdapterError(f"Failed to apply task '{task_name}': {stderr.strip() or stdout.strip()}")

        return Task(
            id=task_name,
            session_id=session_id,
            atespace=atespace,
            phase=TaskPhase.PENDING,
            metadata={"target": target},
        )

    @staticmethod
    def _indent(text: str, spaces: int) -> str:
        prefix = " " * spaces
        return "\n".join(prefix + line if line.strip() else "" for line in text.splitlines())

    def get_task(self, task_name: str, atespace: str = "default") -> Optional[Task]:
        code, stdout, stderr = self._run_ax(["get", "task", task_name, "-a", atespace])
        if code != 0:
            if "not found" in stderr.lower() or "not found" in stdout.lower():
                return None
            raise AXAdapterError(f"Error getting task '{task_name}': {stderr.strip() or stdout.strip()}")

        # Parse YAML output: status.phase, status.actor
        phase = TaskPhase.UNKNOWN
        m_phase = re.search(r"phase:\s*([A-Za-z0-9_-]+)", stdout)
        if m_phase:
            try:
                phase = TaskPhase(m_phase.group(1))
            except ValueError:
                phase = TaskPhase.UNKNOWN

        m_actor = re.search(r"actor:\s*([^\s]+)", stdout)
        actor_id = m_actor.group(1) if m_actor else None

        # Cross-reference with list_tasks table for worker_ip
        worker_ip = None
        for t in self.list_tasks(atespace=atespace):
            if t.id == task_name:
                worker_ip = t.worker_ip
                if phase == TaskPhase.UNKNOWN:
                    phase = t.phase
                break

        return Task(
            id=task_name,
            session_id="",
            atespace=atespace,
            phase=phase,
            actor_id=actor_id,
            worker_ip=worker_ip,
        )

    def list_tasks(self, atespace: str = "default") -> List[Task]:
        code, stdout, stderr = self._run_ax(["get", "tasks", "-a", atespace])
        if code != 0:
            raise AXAdapterError(f"Error listing tasks: {stderr.strip() or stdout.strip()}")

        tasks: List[Task] = []
        lines = [line.strip() for line in stdout.strip().splitlines() if line.strip()]
        for line in lines[1:]:
            parts = re.split(r"\s+", line)
            if len(parts) >= 3:
                name = parts[0]
                phase_str = parts[2]
                actor_id = parts[3] if len(parts) > 3 and parts[3] != "-" else None
                worker_ip = parts[4] if len(parts) > 4 and parts[4] != "-" else None
                try:
                    phase = TaskPhase(phase_str)
                except ValueError:
                    phase = TaskPhase.UNKNOWN
                tasks.append(
                    Task(
                        id=name,
                        session_id="",
                        atespace=atespace,
                        phase=phase,
                        actor_id=actor_id,
                        worker_ip=worker_ip,
                    )
                )
        return tasks

    def suspend_task(self, task_name: str, atespace: str = "default") -> bool:
        code, stdout, stderr = self._run_ax(["suspend", "task", task_name, "-a", atespace])
        if code != 0:
            raise AXAdapterError(f"Failed to suspend task '{task_name}': {stderr.strip() or stdout.strip()}")
        return True

    def resume_task(self, task_name: str, atespace: str = "default") -> bool:
        code, stdout, stderr = self._run_ax(["resume", "task", task_name, "-a", atespace])
        if code != 0:
            raise AXAdapterError(f"Failed to resume task '{task_name}': {stderr.strip() or stdout.strip()}")
        return True

    def delete_task(self, task_name: str, atespace: str = "default") -> bool:
        code, stdout, stderr = self._run_ax(["delete", "task", task_name, "-a", atespace])
        if code != 0 and "not found" not in stderr.lower():
            raise AXAdapterError(f"Failed to delete task '{task_name}': {stderr.strip() or stdout.strip()}")
        return True

    def exec_task(self, task_name: str, command: List[str], atespace: str = "default") -> Tuple[int, str, str]:
        ax_cmd = ["ssh", task_name, "-a", atespace, "--"] + command
        return self._run_ax(ax_cmd)
