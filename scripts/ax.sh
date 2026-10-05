#!/usr/bin/env bash
# scripts/ax.sh — Transparent wrapper for AX CLI via in-cluster toolbox
set -euo pipefail

if [ -t 0 ]; then
  # Terminal input (no stdin pipe)
  kubectl exec -n ax-system deploy/ax-toolbox -- ax "$@"
else
  # Stdin piped in (e.g. cat file | ax apply -f -)
  kubectl exec -i -n ax-system deploy/ax-toolbox -- ax "$@"
fi
