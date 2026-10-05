#!/usr/bin/env bash
# scripts/cleanup.sh — Delete a task and clean up associated resources
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_NAME="${1:-}"

if [ -z "${TASK_NAME}" ]; then
  echo "Usage: $0 <task-name>" >&2
  exit 1
fi

echo "=== Deleting Task: ${TASK_NAME} ==="
"${SCRIPT_DIR}/ax.sh" delete task "${TASK_NAME}" || true
echo "Cleaned up task '${TASK_NAME}'."
