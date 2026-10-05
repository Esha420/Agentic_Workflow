#!/usr/bin/env bash
# scripts/create-research-task.sh — Dynamically create an AX Research Task for an Agent Lab session
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SESSION_ID="${1:-research-session-$(date +%s)}"
TASK_NAME="${SESSION_ID}"
ATESPACE="${2:-default}"
RESEARCH_TARGET="${3:-Autonomous Actor Checkpointing & State Persistence}"

echo "=== Creating Research Task: ${TASK_NAME} ==="
echo "Session ID:      ${SESSION_ID}"
echo "Atespace:        ${ATESPACE}"
echo "Research Target: ${RESEARCH_TARGET}"

TEMPLATE_PATH="${PROJECT_ROOT}/manifests/task-template.yaml"

if [ ! -f "${TEMPLATE_PATH}" ]; then
  echo "Error: Template not found at ${TEMPLATE_PATH}" >&2
  exit 1
fi

# Render template with variables substituted
RENDERED=$(
  export TASK_NAME SESSION_ID ATESPACE RESEARCH_TARGET
  export SCAN_API_URL="http://mock-scan-api.default.svc.cluster.local:8080"
  export MCP_URL="http://172.18.0.1:8085/mcp"
  envsubst < "${TEMPLATE_PATH}"
)

# Apply task using ax CLI
echo "Applying Task manifest to AX..."
echo "${RENDERED}" | "${SCRIPT_DIR}/ax.sh" apply -f -

echo "Task '${TASK_NAME}' successfully submitted to AX."
echo ""
echo "Next actions:"
echo "  Watch status:  ${SCRIPT_DIR}/ax.sh watch task ${TASK_NAME}"
echo "  Describe task: ${SCRIPT_DIR}/ax.sh describe task ${TASK_NAME}"
echo "  Suspend task:  ${SCRIPT_DIR}/suspend.sh ${TASK_NAME}"
echo "  Resume task:   ${SCRIPT_DIR}/resume.sh ${TASK_NAME}"
