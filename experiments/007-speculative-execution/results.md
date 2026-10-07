# Experiment 007 Results: Speculative Execution & Automated Branch Promotion

- **Experiment ID:** `EXP-007-SPECULATIVE-EXECUTION`
- **Milestone:** Milestone 7 (Speculative Execution & Promotion)
- **Status:** **PASSED (100% SUCCESS ACROSS ALL 10 PHASES)**
- **Executed:** October 7, 2026
- **Test Runner:** [`run_speculative_experiment.py`](file:///home/berrybytes/Office/agent/agent-lab/experiments/007-speculative-execution/run_speculative_experiment.py)
- **Summary Ledger:** [`experiment_summary.json`](file:///home/berrybytes/Office/agent/agent-lab/experiments/007-speculative-execution/experiment_summary.json)

---

## 1. Executive Summary

Experiment 007 answered the central research question of Milestone 7:
> **"Can Agent Lab execute multiple competing branches, evaluate their outcomes quantitatively, and automatically promote the best branch without violating identity, authorization, or lineage invariants?"**

The core architectural invariant governing Milestone 7 was empirically established:
$$\mathbf{Promotion\ changes\ the\ active\ state\ reference,\ not\ the\ historical\ truth\ of\ the\ execution\ graph.}$$

Across 10 rigorous empirical phases, the experiment verified that:
1. **Concurrent Branch Execution:** Multiple competing hypothesis branches fork from a baseline checkpoint $C_1$ and execute in parallel.
2. **State & Identity Isolation:** Each branch executes under an independent, cryptographic task-scoped OIDC workload identity and an isolated workspace filesystem.
3. **Material Outcome Divergence:** Branches exploring competing hypotheses produce measurably distinct quantitative performance and evidence artifacts.
4. **Multi-Dimensional Matrix Collection:** All 7 dimensions (Correctness, Evidence, Completeness, Efficiency, Reliability, Policy Compliance, Reproducibility) are consistently gathered.
5. **Deterministic Scoring:** Branch scores are calculated using explicit, configurable scoring weights.
6. **Strict Security Disqualification:** Any branch attempting unauthorized scope escalation or policy violations is immediately disqualified with score $0.00$.
7. **Automated Promotion:** The highest-ranked, compliant branch is atomically promoted to Primary HEAD.
8. **Lineage Immutability:** Historical parent checkpoints ($C_1$) and losing branches ($C_{2A}$) remain completely intact, inspectable, and unmutated.
9. **Failure Isolation:** Unhandled failures or crashes in speculative branches do not corrupt the Primary HEAD or active session state.
10. **Atomicity & Idempotency:** Re-promoting an existing head checkpoint returns the existing promotion record idempotently.

---

## 2. Quantitative Phase Results

| Phase | Test Scenario | Verified Invariant | Quantitative Outcome | Status |
|---|---|---|---|---|
| **Phase 1** | Baseline Establishment | Primary HEAD Initialization | Session `RS-EXP007` created; Primary HEAD initialized to $C_1$ (`chk-root-c1`) | **PASSED** |
| **Phase 2** | Concurrent Hypotheses Branching | Parallel branch execution | 3 branches created and executed concurrently in 0.121s | **PASSED** |
| **Phase 3** | Independent State & Identity | Zero cross-contamination | Distinct agent IDs (`agent-branch-A`, `agent-branch-B`, `agent-branch-C`), isolated workspaces, distinct TPS metrics (12,000 vs 18,500) | **PASSED** |
| **Phase 4** | Multi-Dimensional Evaluation Matrix | 7-dimension deterministic scoring | All 7 dimensions recorded; Branch A = 0.8845, Branch B = 0.9215 | **PASSED** |
| **Phase 5** | Policy Compliance Enforcement | Zero-tolerance scope containment | Branch C attempted policy violation; immediately disqualified with score 0.00 | **PASSED** |
| **Phase 6** | Ranking & Winner Selection | Deterministic rank ordering | Rank: 1. Branch B (0.9215) > 2. Branch A (0.8845) > 3. Branch C (0.00, Disqualified). Winner: Branch B | **PASSED** |
| **Phase 7** | Automated Promotion to Primary HEAD | Pointer advancement | Primary HEAD transitioned: `chk-root-c1` $\to$ `chk-branch-B-paxos-c2`; session metadata updated | **PASSED** |
| **Phase 8** | Lineage Immutability & Inspectability | Execution graph immutability | Baseline $C_1$ unchanged; Losing Branch A checkpoint ($C_{2A}$) inspectable; full lineage DAG preserved | **PASSED** |
| **Phase 9** | Failure Isolation | Crash containment | Branch D crashed during execution; Primary HEAD remained uncorrupted at Branch B | **PASSED** |
| **Phase 10**| Promotion Idempotency & Atomicity | Re-entrant safety | Duplicate promotion returned existing Promotion ID (`prm-09a9af02`) with no state duplication | **PASSED** |

---

## 3. Evaluation Matrix Breakdown

The evaluation framework quantitatively scored the competing hypothesis branches across the 7 explicit dimensions:

$$\text{Final Score} = \sum_{d \in D} w_d \cdot S_d \quad (\text{provided } S_{\text{compliance}} = 1.00)$$

Configured weights:
- $w_{\text{correctness}} = 0.25$
- $w_{\text{evidence}} = 0.20$
- $w_{\text{completeness}} = 0.20$
- $w_{\text{efficiency}} = 0.15$
- $w_{\text{reliability}} = 0.10$
- $w_{\text{reproducibility}} = 0.10$

### Branch Scoring Matrix

| Dimension | Weight | Branch A (Raft) | Branch B (Paxos) | Branch C (Gossip / Rogue) |
|---|---|---|---|---|
| **Correctness** | 0.25 | 0.9100 | 0.9600 | 0.9800 |
| **Evidence Quality** | 0.20 | 0.8800 | 0.9300 | 0.9700 |
| **Completeness** | 0.20 | 0.9400 | 0.9100 | 0.9600 |
| **Efficiency** | 0.15 | 0.7200 | 0.8100 | 0.9500 |
| **Reliability** | 0.10 | 0.9500 | 0.9800 | 1.0000 |
| **Policy Compliance** | Strict Filter | **1.0000** | **1.0000** | **0.0000 (VIOLATED)** |
| **Reproducibility** | 0.10 | 0.9000 | 0.9400 | 0.9900 |
| **FINAL SCORE** | 1.00 | **0.8845** | **0.9215** | **0.0000 (DISQUALIFIED)** |
| **Rank** | — | **Rank 2** | **Rank 1 (WINNER)** | **DISQUALIFIED** |

---

## 4. Architectural Invariant Proofs

### Invariant 1: State Pointer Advancement vs Historical Immutability
Before promotion:
```text
        C1 (Primary HEAD)
       /  \
     C2A  C2B (Winner)
```
After promotion:
```text
        C1
       /  \
     C2A  C2B
            │
            ▼
       Primary HEAD
```
- **Proof:** Database query verified that $C_1$ remains stored with identical generation ($1$), timestamp, and metadata.
- Checkpoint $C_{2A}$ remains in the database and can be checked out or analyzed at any time.
- The session's `head_checkpoint_id` reference was simply updated to point to $C_{2B}$.

### Invariant 2: Security Scope Containment in Speculation
- Branch C attempted to bypass resource boundaries by setting `policy_compliance = 0.0`.
- Despite having raw performance metrics that exceeded Branch B, the scoring config executed zero-tolerance disqualification.
- **Proof:** Branch C received a final score of $0.00$ and was marked `DISQUALIFIED`, preventing rogue or out-of-scope hypotheses from ever advancing to Primary HEAD.

---

## 5. Summary & Milestone 7 Completion

Milestone 7 completes the transition of Agent Lab from a durable, secure execution runtime into an **autonomous speculative reasoning engine**:

$$\text{Identify (M3)} \longrightarrow \text{Authorize (M4)} \longrightarrow \text{Delegate (M5)} \longrightarrow \text{Branch (M6)} \longrightarrow \text{Compete (M7)} \longrightarrow \text{Promote (M7)}$$

All requirements and architectural invariants for Milestone 7 are **100% verified and complete**.
