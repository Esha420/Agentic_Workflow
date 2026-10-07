# Experiment 002 — Architectural Investigation & Verification

## 1. Overview & Objective

Before implementing the full Agent Lab architecture, Experiment 002 tests and establishes the four foundational architectural boundaries:
1. **Identity:** Can we reliably identify every agent?
2. **Authorization:** Can we dynamically determine what that agent is allowed to do without static peer-to-peer permissions?
3. **Orchestration:** Can AX dynamically decide which agent should perform the work, or is an application control plane strictly required above AX?
4. **Execution:** Can Agent Substrate execute, suspend, migrate, and restore an agent without losing its identity/context?

---

## 2. The Seven Investigation Experiments

| Experiment | Core Question | Validation Methodology |
|---|---|---|
| **1. AX Dynamic Orchestration** | *Is AX capable of being the dynamic orchestration layer, or do we need an additional orchestration component above AX?* | Inspect AX CRD reconciler (`ax-controller`), test task creation, runtime model selection, and analyze native routing, capability discovery, and delegation support in AX. |
| **2. Workload Identity** | *What should be the canonical identity of an Agent Lab agent?* | Compare Kubernetes Projected ServiceAccount tokens, SPIFFE/SPIRE SVIDs, and OIDC/JWT workload tokens. Verify cryptographic token issuance, unique subject claims, and tamper resistance. |
| **3. Identity Persistence** | *Does the agent's logical identity remain stable even though physical execution environment changes?* | Track Agent-27 during suspension on Worker A (`2s6cd`), worker reclamation to `<none>`, and restoration on Worker B (`8b9vz`). Verify signature validity and claims stability. |
| **4. Dynamic Authorization** | *Can effective scope be calculated dynamically from context rather than maintaining static agent-to-agent permissions?* | Test the intersection evaluation model `Evaluate(Identity, Task, Workspace, Capability, Delegation, Policy)`. Verify `ALLOW` and verify fail-closed `DENY` across 4 violation dimensions. |
| **5. Dynamic Discovery** | *Can agents discover eligible peers by capability instead of static hardcoded names?* | Test capability registry query (`"I need document_analysis"`), multi-provider selection, policy filtering, unavailable agent failover, and missing capability handling. |
| **6. Delegation & Enforcement** | *Where is the actual security boundary, and does it enforce Child Scope ⊆ Parent Scope?* | Validate that an agent cannot delegate authority it does not possess. Test Gateway interception with 5 deliberately invalid requests failing closed. |
| **7. API Boundary & Auditability** | *Can CLI/UI/other clients operate the same Agent Lab API without bypassing the architecture, and can transactions be fully reconstructed?* | Validate unified REST contracts for CLI, Web UI, and external integrations. Validate structured audit trail schema and provenance reconstruction. |

---

## 3. Running the Investigation Suite

```bash
python3 experiments/002-architectural-investigation/run_investigation.py
```

Results are saved to `experiments/002-architectural-investigation/investigation_summary.json` and documented in [results.md](results.md).
