#!/usr/bin/env bash
# scripts/resume.sh — Resume a suspended task from durable snapshot
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_NAME="${1:-}"

if [ -z "${TASK_NAME}" ]; then
  echo "Usage: $0 <task-name>" >&2
  exit 1
fi

echo "=== Resuming Task: ${TASK_NAME} ==="
"${SCRIPT_DIR}/ax.sh" resume task "${TASK_NAME}"

echo "Waiting for task status transition..."
sleep 2

"${SCRIPT_DIR}/ax.sh" get task "${TASK_NAME}" || true
echo "Task '${TASK_NAME}' resumed onto active worker."
