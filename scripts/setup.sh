#!/usr/bin/env bash
# scripts/setup.sh — Verify and prepare the AX + Agent Substrate environment for Agent Lab
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== Agent Lab Environment Verification ==="

echo -n "Checking kubectl connection... "
if ! kubectl cluster-info >/dev/null 2>&1; then
  echo "FAILED: Cannot reach Kubernetes cluster." >&2
  exit 1
fi
echo "OK"

echo -n "Checking Agent Substrate (ate-system)... "
ATE_RUNNING=$(kubectl get pods -n ate-system --no-headers 2>/dev/null | grep -c "Running" || true)
if [ "${ATE_RUNNING}" -lt 5 ]; then
  echo "WARNING: Expected at least 5 running pods in ate-system, found ${ATE_RUNNING}." >&2
else
  echo "OK (${ATE_RUNNING} pods running)"
fi

echo -n "Checking AX Control Plane (ax-system)... "
AX_RUNNING=$(kubectl get pods -n ax-system --no-headers 2>/dev/null | grep -c "Running" || true)
if [ "${AX_RUNNING}" -lt 5 ]; then
  echo "WARNING: Expected at least 5 running pods in ax-system, found ${AX_RUNNING}." >&2
else
  echo "OK (${AX_RUNNING} pods running)"
fi

echo -n "Checking AX CLI via ax-toolbox... "
if "${SCRIPT_DIR}/ax.sh" get tasks >/dev/null 2>&1; then
  echo "OK"
else
  echo "FAILED: ax CLI invocation failed." >&2
  exit 1
fi

echo -n "Checking Agent Substrate WorkerPool... "
WORKERS=$(kubectl get pods -n ax-system -l ate.dev/worker-pool=worker-pool --no-headers 2>/dev/null | grep -c "Running" || true)
echo "OK (${WORKERS} worker pods active)"

echo -n "Checking Mock Scan API... "
SCAN_STATUS=$(kubectl get pod -l app=mock-scan-api -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)
if [ "${SCAN_STATUS}" = "Running" ]; then
  echo "OK"
else
  echo "WARNING: Mock scan API status is '${SCAN_STATUS}'."
fi

echo ""
echo "=== Agent Lab Environment is Ready ==="
echo "Run './scripts/create-research-task.sh [session-id]' to launch a research agent."
