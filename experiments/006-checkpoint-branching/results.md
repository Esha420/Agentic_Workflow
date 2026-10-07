# Experiment 006 Results: Checkpoint Branching & State Invariant Investigation

- **Experiment ID:** `EXP-006-CHECKPOINT-BRANCHING`
- **Milestone:** Milestone 6 (Checkpoint Branching)
- **Status:** **PASSED (100% SUCCESS ACROSS ALL 10 PHASES)**
- **Executed:** October 7, 2026
- **Test Runner:** [`run_branching_experiment.py`](file:///home/berrybytes/Office/agent/agent-lab/experiments/006-checkpoint-branching/run_branching_experiment.py)

---

## 1. Executive Summary

Experiment 006 empirically investigated and validated the **Checkpoint Branching** architectural capability of Agent Lab. The experiment answered the foundational question: **"Can an authorized agent fork its durable execution state into independent branches while preserving correct identity, authorization context, and lineage?"**

The core security and state invariants were proven across 10 adversarial and structural test phases:
1. **Core State Security Invariant:**
   $$\text{Branch Authorization} \subseteq \text{Source Authorization}$$
   A branch evolves its state independently, but state branching **never** becomes an authorization-escalation mechanism.
2. **Immutable Parent Checkpoint:** Parent checkpoints remain 100% read-only and immutable. Downstream branch mutations do not touch the parent snapshot.
3. **Branch Isolation & Zero Cross-Contamination:** State mutations in Branch A are completely isolated from Branch B.
4. **Independent Workload Identity:** Every branch receives an independent, verifiable task-scoped identity token without subject collision.
5. **Lineage DAG Reconstruction:** Full checkpoint-branch-child tree was reconstructed and verified from the SQLite metadata ledger.

---

## 2. Quantitative Phase Results

| Phase | Test Scenario | Verified Invariant | Outcome | Status |
|---|---|---|---|---|
| **Phase 1** | Baseline Session & Parent Checkpoint Creation ($C_1$) | Root state immutability baseline | Checkpoint `chk-root-c1` saved (Gen 1) | **PASSED** |
| **Phase 2** | Dual Branch Creation ($C_1 \to \text{Branch A}$, $C_1 \to \text{Branch B}$) | Independent branch instantiation | Branches `branch-A-sampling` and `branch-B-semantic` created (Gen 2) | **PASSED** |
| **Phase 3** | Containment Invariant Verification | $\text{Branch Auth} \subseteq \text{Source Auth}$ | Verified across capability, actions, resource pattern, quota, and TTL | **PASSED** |
| **Phase 4** | Branch Capability Escalation Attempt (`prod_deploy`) | Scope containment boundary | `DENIED` (`Capability escalation denied: requested branch capability 'prod_deploy' is not granted`) | **PASSED** |
| **Phase 5** | Branch Resource Path Escape Attempt (`/workspace/finance/*`) | Path containment boundary | `DENIED` (`Resource escalation denied: requested path escapes source boundary`) | **PASSED** |
| **Phase 6** | Independent Branch Workload Identity | Non-colliding M3 identity | Distinct subjects (`agent:br-A` vs `agent:br-B`), tokens, and task bindings validated | **PASSED** |
| **Phase 7** | Workspace State Divergence & File Isolation | Zero cross-contamination | Branch A files invisible in Branch B; zero cross-bleed | **PASSED** |
| **Phase 8** | Parent Checkpoint Immutability | Immutability under divergence | Parent $C_1$ and root workspace unmodified | **PASSED** |
| **Phase 9** | Commit Branch Checkpoints ($C_{2A}$ and $C_{2B}$) | Branch state persistence | Committed `chk-branch-a-c2` and `chk-branch-b-c2` (Gen 2) | **PASSED** |
| **Phase 10**| Lineage DAG & Audit Provenance Reconstruction | Complete execution DAG | DAG reconstructed: $C_1 \to \{B_A \to C_{2A}, B_B \to C_{2B}\}$, 6 audit events verified | **PASSED** |

---

## 3. Detailed Phase Analysis

### Phase 1: Baseline Parent Checkpoint ($C_1$)
- **Session:** `RS-EXP006-3423fb`
- **Root Agent:** `researcher-root` (`agent:researcher-root`)
- **Root Scope:** `document_analysis` with `/workspace/research/*` (quota: 20 calls, TTL: 7200s, depth: 2).
- **Parent Checkpoint:** `chk-root-c1` committed at Generation 1.

### Phase 2: Dual Branch Creation from $C_1$
Forked $C_1$ into two parallel hypothesis branches:
- **Branch A:** `branch-A-sampling` (Hypothesis: "Fast statistical sampling approach", Gen 2, Quota: 8).
- **Branch B:** `branch-B-semantic` (Hypothesis: "Deep semantic verification approach", Gen 2, Quota: 12).
Each branch retained:
- `branch_id`
- `parent_checkpoint_id` (`chk-root-c1`)
- `agent_id`
- `task_id`
- `workspace_id`
- `identity_subject`
- `scope_id`
- `delegation_chain`
- `workspace_generation`
- `snapshot_reference`
- `created_at`

### Phase 3: Mathematical Containment Proof
The issued Scope Token for Branch A was verified:
- Capability: `document_analysis` == Source capability (`document_analysis`).
- Action: `read` $\in$ Source allowed actions (`['read']`).
- Resource: `/workspace/research/sampling/*` is a strict subpattern of `/workspace/research/*`.
- Quota: $8 \le 20$.
- TTL: $3600 \text{s} \le 7200 \text{s}$.

### Phases 4 & 5: Adversarial Rejection
- **Capability Escalation:** A branch requesting `prod_deploy` was rejected fail-closed with `BranchEscalationDenied`.
- **Resource Boundary Escape:** A branch requesting `/workspace/finance/payroll/*` was rejected fail-closed with `BranchEscalationDenied`.

### Phase 6: Cryptographic Workload Identity Isolation
- Branch A Subject: `agent:agent-branch-A-sampling` (bound to `T-branch-branch-A-sampling`).
- Branch B Subject: `agent:agent-branch-B-semantic` (bound to `T-branch-branch-B-semantic`).
Both tokens cryptographically validated against `OIDCWorkloadIdentityProvider` with zero identity confusion.

### Phase 7: State Divergence & Workspace Isolation
- Branch A created `sampling_findings.json` (`speedup: 4.2x, accuracy: 0.91`).
- Branch B created `semantic_findings.json` (`speedup: 1.1x, accuracy: 0.994`).
- Confirmed that Branch A's files do not exist in Branch B's workspace directory, and vice-versa.

### Phase 8: Parent Immutability
- Refreshed Checkpoint $C_1$ from database: Generation remained 1, `parent_checkpoint_id` remained `None`.
- Filesystem inspection verified that neither `sampling_findings.json` nor `semantic_findings.json` touched the parent workspace.

### Phase 9: Committing Branch Checkpoints ($C_{2A}$ and $C_{2B}$)
Both branches successfully committed subsequent checkpoints:
- $C_{2A}$: `chk-branch-a-c2` (Parent: `chk-root-c1`, Branch: `branch-A-sampling`, Gen: 2).
- $C_{2B}$: `chk-branch-b-c2` (Parent: `chk-root-c1`, Branch: `branch-B-semantic`, Gen: 2).

### Phase 10: Full Lineage DAG Reconstruction
Queried the DAG from `SQLiteMetadataStore`:
```text
               Checkpoint C1 (chk-root-c1)
                     │
              ┌──────┴──────┐
              ▼             ▼
          Branch A       Branch B
        (Sampling)      (Semantic)
              │             │
              ▼             ▼
        Checkpoint C2A  Checkpoint C2B
      (chk-branch-a-c2)(chk-branch-b-c2)
```
The complete tree and all 6 audit events were reconstructed without missing links.

---

## 4. Architectural Progression & Next Milestone

The architectural progression across milestones is complete:

```text
M3: Real Agent Identity          ==> "Who is this agent?"
    ↓
M4: Trust & Scope Plane          ==> "What is this agent allowed to do?"
    ↓
M5: Agent Communication          ==> "Can multiple agents safely collaborate?" (Child Scope ⊆ Parent Scope)
    ↓
M6: Checkpoint Branching         ==> "Can we fork their state?" (Branch Auth ⊆ Source Auth)
    ↓
M7: Speculative Execution        ==> "Can we run competing branches & promote the winner?"
```

Milestone 6 is **Completed & Verified (Exp 006)**. We are ready to proceed to **Milestone 7: Speculative Execution**.
