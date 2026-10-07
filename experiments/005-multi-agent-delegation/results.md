# Experiment 005 Results: Multi-Agent Delegation & Invariant Enforcement

- **Experiment ID:** `EXP-005-MULTI-AGENT-DELEGATION`
- **Milestone:** Milestone 5 (Multi-Agent Communication & Delegation)
- **Status:** **PASSED (100% SUCCESS ACROSS ALL 10 PHASES)**
- **Executed:** October 7, 2026
- **Test Runner:** [`run_delegation_experiment.py`](file:///home/berrybytes/Office/agent/agent-lab/experiments/005-multi-agent-delegation/run_delegation_experiment.py)

---

## 1. Executive Summary

Experiment 005 empirically verified the **Multi-Agent Communication & Safe Delegation** layer of Agent Lab. The experiment answered the foundational question: **"Can multiple agents safely collaborate without privilege escalation?"**

All ten adversarial verification phases succeeded with 100% adherence to the core security invariant:
$$\text{Child Scope} \subseteq \text{Parent Scope}$$

No sequence of valid delegations was capable of producing authority that was not present in the original authorized parent scope. Every unauthorized, out-of-bounds, cross-task, cross-tenant, or depth-exhausted delegation request was rejected **fail-closed**.

---

## 2. Quantitative Phase Results

| Phase | Test Scenario | Verified Invariant | Outcome | Status |
|---|---|---|---|---|
| **Phase 1** | Agent A (`planner-01`) delegates to Agent B (`researcher-27`) | Authorized capability delegation | `ALLOWED`, Child Scope `dlg-958210dea4` issued | **PASSED** |
| **Phase 2** | Child Scope subset verification | $\text{Child} \subseteq \text{Parent}$ | Verified across capability, actions, resource pattern, quota, TTL, and depth | **PASSED** |
| **Phase 3** | Agent B attempts capability escalation (`prod_deploy`) | Non-granted capability blocked | `DENIED` (`Capability escalation denied`) | **PASSED** |
| **Phase 4** | Agent B attempts resource path escalation | Resource escape blocked | `DENIED` (`Resource escalation denied`) | **PASSED** |
| **Phase 5** | Agent B attempts cross-task delegation | Contextual task binding enforced | `DENIED` (`Task binding mismatch`) | **PASSED** |
| **Phase 6** | Agent B attempts cross-tenant delegation (`rival-corp`) | Tenant boundary enforced | `DENIED` (`Cross-tenant delegation denied`) | **PASSED** |
| **Phase 7** | Delegation depth reaches zero | Zero-depth restriction enforced | Hop 2 (depth 0) `ALLOWED`; Hop 3 `DENIED` (`Delegation depth exhausted`) | **PASSED** |
| **Phase 8** | Revoked parent scope cascade | Revocation invalidates downstream | `Allowed=False` (`Delegation invalidated: Parent scope is revoked`) | **PASSED** |
| **Phase 9** | Multi-hop provenance chain audit | End-to-end chain reconstruction | Chain verified: `planner-01 -> researcher-27 -> document-agent-42` | **PASSED** |
| **Phase 10**| Gateway fail-closed enforcement point | In-path dual token verification | Token theft blocked, resource escape blocked, valid invocation allowed | **PASSED** |

---

## 3. Detailed Phase Analysis

### Phase 1 & 2: Bounded Delegation & Invariant Containment
- **Parent Scope (`planner-01`):**
  - Capability: `document_analysis`
  - Action: `read`
  - Resource: `/workspace/research/*`
  - Max Calls: 10
  - Delegation Depth: 2
- **Child Scope (`researcher-27`):**
  - Capability: `document_analysis`
  - Action: `read`
  - Resource: `/workspace/research/sources/*` (strict subdirectory)
  - Max Calls: 5 ($\le 10$)
  - Delegation Depth: 1 ($2 - 1 = 1$)
  - Expiration: $\le$ Parent Expiration

### Phases 3–6: Adversarial Escalation Rejections
- **Capability Escalation:** `researcher-27` attempted to delegate `prod_deploy` to `document-agent-42`. The Delegation Engine detected that `prod_deploy` was not present in the parent scope and rejected the request fail-closed.
- **Resource Escalation:** `researcher-27` attempted to delegate `/workspace/finance/payroll/*`. The engine detected that the path escaped the parent's `/workspace/research/sources/*` boundary and rejected it.
- **Cross-Task Attack:** A delegation request presenting `task_id = "T-TAMPERED-TASK-999"` against a token bound to `T-482-autonomous-research` was rejected immediately.
- **Cross-Tenant Attack:** A delegation request to `rival-spy-007` (tenant `rival-corp`) from a caller in tenant `acme` was blocked fail-closed under strict tenant isolation.

### Phase 7: Finite Delegation Depth Invariant
1. Hop 1 (`planner-01` $\to$ `researcher-27`): Depth decremented from 2 to 1.
2. Hop 2 (`researcher-27` $\to$ `document-agent-42`): Depth decremented from 1 to 0 (`ALLOWED`).
3. Hop 3 (`document-agent-42` $\to$ `sub-agent-04`): Attempted delegation with parent depth = 0. **Result:** `DENIED` (`Delegation depth exhausted: parent scope remaining delegation depth is 0`).

### Phase 8: Revocation Cascading
When root scope `scp-63a18abdc1` was revoked, in-path gateway authorization using child scope `dlg-958210dea4` failed immediately:
- `Allowed=False`
- `Reason: Gateway rejected: Delegated scope unauthorized (Delegation invalidated: Parent scope 'scp-63a18abdc1' is revoked)`.

### Phase 9: End-to-End Provenance Reconstruction
Inspected child token claims and queried persistent SQLite `audit_events`:
- Root Subject: `agent:planner-01`
- Immediate Delegator: `agent:researcher-27`
- Current Holder: `agent:document-agent-42`
- Provenance Chain:
  $$\text{agent:planner-01} \longrightarrow \text{agent:researcher-27} \longrightarrow \text{agent:document-agent-42}$$

### Phase 10: Gateway Interception Point
The Agent Gateway authorizer was validated as the single in-path enforcement gate:
1. Scope theft (Agent A presenting Agent C's child token): Blocked (`Scope subject does not match identity subject`).
2. Resource boundary escape (Agent C attempting to read `/workspace/research/other.txt` outside `/workspace/research/sources/pdf/*`): Blocked.
3. Legitimate invocation: Approved (`Allowed=True`), quota decremented, decision logged to immutable audit ledger.

---

## 4. Architectural Completion of Trust Pipeline

With Milestone 5 verified, the complete trust and delegation chain is mathematically closed:

```text
Milestone 3 (WHO)
   Workload Identity Token (OIDC-compatible JWT)
            │
            ▼
Milestone 4 (WHAT)
   Effective Scope Token (Contextual Intersection)
            │
            ▼
Milestone 5 (DELEGATION)
   Delegated Child Scope Token (Child Scope ⊆ Parent Scope)
            │
            ▼
Agent Gateway (IN-PATH)
   Dual-Token + Provenance Verification
            │
            ▼
Execution Substrate (Worker Pods)
```

The trust pipeline is now fully prepared for **Milestone 6: Checkpoint Branching** (forking durable state alongside authorization context).
