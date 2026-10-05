#!/usr/bin/env bash
# scripts/check-workers.sh — Inspect worker pool allocation and task status
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== AX Tasks ==="
"${SCRIPT_DIR}/ax.sh" get tasks || true

echo ""
echo "=== Agent Substrate WorkerPool Status ==="
kubectl get pods -n ax-system -l ate.dev/worker-pool=worker-pool -o wide

echo ""
echo "=== Agent Substrate Actors ==="
kubectl get actors.ate.dev -A 2>/dev/null || echo "No actors found or CRD ate.dev not in default path."
