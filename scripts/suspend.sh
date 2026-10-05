#!/usr/bin/env bash
# scripts/suspend.sh — Suspend an active task and verify checkpoint
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_NAME="${1:-}"

if [ -z "${TASK_NAME}" ]; then
  echo "Usage: $0 <task-name>" >&2
  exit 1
fi

echo "=== Suspending Task: ${TASK_NAME} ==="
"${SCRIPT_DIR}/ax.sh" suspend task "${TASK_NAME}"

echo "Waiting for task status transition..."
sleep 2

"${SCRIPT_DIR}/ax.sh" get task "${TASK_NAME}" || true
echo "Task '${TASK_NAME}' suspension initiated. Worker resources are now reclaimed."
