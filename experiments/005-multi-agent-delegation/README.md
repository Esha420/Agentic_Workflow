# Experiment 005: Multi-Agent Delegation & Invariant Enforcement

## 1. Context & Research Objective

In Milestone 3, we established task-scoped workload identity (`WHO is this agent?`). In Milestone 4, we implemented the Policy Engine and Scope Issuer (`WHAT is this agent allowed to do right now?`).

The question for **Milestone 5** is:
> **"Can multiple agents safely collaborate and delegate authority without privilege escalation?"**

### The Central Security Invariant
$$\text{Child Scope} \subseteq \text{Parent Scope}$$

An agent can delegate authority it already possesses, but can **never create, transfer, or escalate authority beyond its own effective scope**.
No sequence of valid delegations can produce authority that was not present in the original authorized parent scope.

---

## 2. Architecture & Delegation Flow

```text
                 Agent A (Planner)
                        │ Verified Workload Identity (M3)
                        │ Effective Scope (M4)
                        ▼
                 Delegation Request
                        │
                        ▼
              ┌────────────────────┐
              │ Delegation Engine  │
              │                    │
              │ Parent Scope       │
              │ Requested Scope    │
              │ Target Agent       │
              │ Cross-Tenant Check │
              │ Depth Check        │
              └─────────┬──────────┘
                        │
                 Child ⊆ Parent?
                   │          │
                  YES         NO
                   │           │
                   ▼           ▼
            Child Scope      DENIED
              Issuer          + Audit
                   │
                   ▼
              Agent Gateway (In-Path Dual Verification)
                   │
                   ▼
                 Agent B (Worker)
```

### Delegation Provenance Chain
Delegated tokens explicitly retain complete end-to-end provenance:
`planner-01 -> researcher-27 -> document-agent-42`

---

## 3. Ten Experimental Verification Phases

| Phase | Test Scenario | Expected Outcome |
|---|---|---|
| **Phase 1** | Agent A delegates allowed capability to Agent B | `ALLOWED`, valid provenance |
| **Phase 2** | Child scope verified as mathematical subset of parent | $\text{Child} \subseteq \text{Parent}$ |
| **Phase 3** | Agent B attempts capability escalation (`prod_deploy`) | `DENIED` |
| **Phase 4** | Agent B attempts resource path escalation (`/workspace/finance/*`) | `DENIED` |
| **Phase 5** | Agent B attempts cross-task delegation (`T-TAMPERED-TASK`) | `DENIED` |
| **Phase 6** | Agent B attempts cross-tenant delegation (`rival-corp`) | `DENIED` |
| **Phase 7** | Delegation depth reaches zero; hop 3 attempted | Hop 2 `ALLOWED`, Hop 3 `DENIED` |
| **Phase 8** | Revoked parent scope invalidates downstream child scopes | Invalidation cascade enforced at Gateway |
| **Phase 9** | Full multi-hop delegation chain reconstructed from SQLite audit | Chain verified: $A \to B \to C$ |
| **Phase 10**| Gateway blocks invalid delegations fail-closed | Token theft and path escape blocked |

---

## 4. Execution Command

```bash
python3 experiments/005-multi-agent-delegation/run_delegation_experiment.py
```
