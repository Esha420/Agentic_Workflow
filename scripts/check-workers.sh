#!/usr/bin/env bash
# scripts/check-workers.sh — Inspect worker pool allocation, AX tasks, and Substrate actors
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== AX Tasks ==="
"${SCRIPT_DIR}/ax.sh" get tasks || true

echo ""
echo "=== Agent Substrate WorkerPool Pods ==="
kubectl get pods -n ax-system -l ate.dev/worker-pool=worker-pool -o wide

echo ""
echo "=== Agent Substrate Actors (Active Allocations) ==="
kubectl exec -n ax-system deploy/ax-toolbox -- kubectl-ate get actors -a default 2>/dev/null || echo "Unable to query kubectl-ate"
