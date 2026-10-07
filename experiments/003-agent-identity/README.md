# Experiment 003: Real Agent Identity & Migration Invariance

## 1. Context & Research Objective

In Milestone 1, we proved that an agent can survive idle compute reclamation and resume onto a new physical worker. In Experiment 002, we established the mathematical and architectural requirements for workload identity.

The question for **Milestone 3** is:
> **Can we reliably identify agents across physical compute migrations, and does that identity maintain a strict, fail-closed lifecycle?**

### Core Separation of Concerns
Agent Lab maintains a strict architectural boundary between identity, directory metadata, and execution:

| Component | Architectural Responsibility |
|---|---|
| **OIDC / Identity Provider** | Cryptographically establishes, signs, and validates **WHO** the agent is. |
| **Agent Registry** | Authoritative directory mapping logical agent identities $\leftrightarrow$ Agent Lab metadata (`role`, `tenant`, `capabilities`, `bindings`). Strictly independent of physical worker allocations. |
| **Policy Engine (M4)** | Determines what that identity is permitted to execute. |
| **AX** | Orchestrates infrastructure tasks (`Task`, `Workspace`). Unaware of cryptographic token signing. |
| **Agent Substrate** | Executes sandboxed compute workers (`Worker A`, `Worker B`). |

---

## 2. Invariance Topology & Hypothesis

```text
Logical Agent: researcher-27
Identity:      agent:researcher-27 (Signed OIDC-compatible JWT Token X)
Task:          T-482-autonomous-research
Workspace:     WS-security-mesh

                 Physical Worker A (10.244.0.26)
                               │
                             RUNNING
                               │
                            SUSPEND
                               │
                        Worker reclaimed
                               │
                            RESUME
                               │
                 Physical Worker B (10.244.0.38)
                               │
                             RUNNING

Result:
  Identity = X (Exact cryptographic token preserved)
  Subject  = agent:researcher-27
  Task     = T-482-autonomous-research
  WS       = WS-security-mesh
  Zero identity re-mapping or worker impersonation.
```

---

## 3. Five Experimental Verification Phases

1. **Phase 1: Agent Registry Separation of Concerns:**
   Verify that registering an agent creates a logical record without physical compute binding or faux identity generation.
2. **Phase 2: Cryptographic Identity Issuance:**
   Verify that `IdentityProviderInterface` issues a signed OIDC-compatible JWT with strict `sub`, `iss`, `aud`, `task_id`, `workspace_id`, and `jti` anti-replay claims.
3. **Phase 3: Worker Migration Invariance:**
   Simulate active execution on Worker A, idle suspension with compute worker reclamation, and resumption on Worker B. Cryptographically verify signature, claims, and context bindings on Worker B.
4. **Phase 4: Full Identity Lifecycle & Revocation:**
   Verify the full sequence:
   $$\text{CREATE} \longrightarrow \text{ISSUE} \longrightarrow \text{RUNNING} \longrightarrow \text{SUSPENDED} \longrightarrow \text{RESUMED} \longrightarrow \text{COMPLETED} \longrightarrow \text{REVOKED}$$
   Confirm that once an agent is terminated, its token is rejected fail-closed.
5. **Phase 5: Tamper Resistance & Contextual Bounds:**
   Verify immediate rejection when signature is altered or task/workspace claims are spoofed.

---

## 4. Execution

To run the experiment suite:
```bash
python3 experiments/003-agent-identity/run_identity_experiment.py
```
Outputs are written to `experiments/003-agent-identity/experiment_summary.json` and `experiments/003-agent-identity/results.md`.
