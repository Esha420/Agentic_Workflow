# Agent Lab Roadmap

## Overview: The Research Narrative & Progression

Agent Lab structures its engineering progression around seven foundational questions:

| Milestone | Purpose | Research Question | Status |
|---|---|---|---|
| **1. Durable Agent** | Prove persistent state + suspend/resume + worker reclamation | *Can an agent survive?* | ✅ Verified (Exp 001) |
| **2. Control Plane + API + Web UI** | Make Agent Lab interactive and client-independent | *Can humans operate it?* | ✅ Completed & Verified (M2) |
| **3. Real Agent Identity** | Establish verifiable workload identity | *Can we identify it?* | ✅ Completed & Verified (Exp 003) |
| **4. Trust & Scope Plane** | Introduce capability/policy-based authorization service | *Can we control what it is allowed to do?* | ✅ Completed & Verified (Exp 004) |
| **5. Agent Communication** | Multi-agent delegation & gateway enforcement | *Can multiple agents safely collaborate?* | ✅ Completed & Verified (Exp 005) |
| **6. Checkpoint Branching** | Fork durable state and authorization context | *Can we fork their state?* | ✅ Completed & Verified (Exp 006) |
| **7. Speculative Execution** | Compete, evaluate, and promote branches | *Can we run competing autonomous branches and promote the result?* | ✅ Completed & Verified (Exp 007) |
| **8. External OIDC & Scope** | Layer external OIDC agentic identity over SPIFFE | *Can OIDC provide logical identity over SPIFFE workload identity?* | ✅ Verified (Exp 008) |



```text
Agent Lab
    │ application semantics
    │ agent orchestration
    │ trust / authorization
    ↓
AX
    │ infrastructure orchestration
    │ Task / Workspace / Gateway
    ↓
Agent Substrate
    │ isolated execution
    │ suspend / restore / migration
    ↓
Workers
```

---

## Milestone 0 — Platform Foundation

**Goal:** Establish clean repository foundation, system context, and environment verification.

- [x] Create Agent Lab repository structure
- [x] Document production-shaped architecture in [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md)
- [x] Document execution roadmap in [ROADMAP.md](ROADMAP.md)
- [x] Verify existing AX + Agent Substrate KinD cluster environment via [scripts/setup.sh](scripts/setup.sh)
- [x] Provide initial operational scripts and experiment 001 protocol

---

## Milestone 1 — Durable Agent (Completed & Empirically Verified)

**Goal:** Prove the foundational primitive: an agent can persist $\rightarrow$ wait $\rightarrow$ suspend $\rightarrow$ release compute $\rightarrow$ resume elsewhere $\rightarrow$ continue (*Can an agent survive?*).

- [x] Reusable Research Agent Task Template dynamically instantiated via `agent-lab research create`
- [x] Durable workspace state accumulated under `/workspace/research/` prior to suspension
- [x] Autonomous idle wait detection triggering automatic task suspension
- [x] Physical compute worker reclaimed (worker allocation dropped from 1 to 0)
- [x] Cross-worker migration proven: restored onto a different physical worker pod and completed research synthesis
- [x] Empirical evidence documented in [experiments/001-persistent-research/results.md](experiments/001-persistent-research/results.md)

---

## Architectural Investigation (Experiment 002 — Completed & Verified)

**Goal:** Empirically verify the core architectural assumptions before platform buildout.

- [x] **AX Orchestration Scope:** Proven that AX is the infrastructure orchestration layer; Agent Lab Control Plane is strictly required above AX.
- [x] **Workload Identity:** Selected task-scoped OIDC-compatible JWT workload identity architecture; verified claims uniqueness and tamper resistance.
- [x] **Identity Persistence:** Proven that logical identity survives worker migration and state restoration.
- [x] **Dynamic Authorization:** Validated contextual intersection model with fail-closed enforcement across 4 violation dimensions.
- [x] **Dynamic Discovery:** Proven that agents can discover eligible peers by capability with automated failover.
- [x] **Delegation & Gateway Enforcement:** Verified $\text{Child Scope} \subseteq \text{Parent Scope}$ and fail-closed gateway proxy interception.
- [x] **API Boundary & Auditability:** Verified unified REST contracts and structured audit provenance reconstruction.
- [x] Documented in [experiments/002-architectural-investigation/results.md](experiments/002-architectural-investigation/results.md).

---

## Milestone 2 — Agent Lab Control Plane + API + Web UI (Completed & Verified)

**Goal:** Build the unified Agent Lab API and interactive Web UI, promoting the CLI to a client (*Can humans operate it?*).

```text
                 ┌── CLI (`agent-lab`)
                 │
                 ├── Web UI (Dashboard)
                 │
                 └── External Clients (Slack / CI)
                         │
                         ▼
                 Agent Lab API
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
Research Sessions     Agents            Tasks
Workspaces            Lifecycle      Checkpoints
                         │
                         ▼
                    AX Adapter
                         │
                         ▼
                         AX
```

### 1. Unified Agent Lab API
- [x] Implement REST API server exposing:
  - `POST /api/v1/research-sessions` — Create research session
  - `GET /api/v1/research-sessions` — List all sessions
  - `GET /api/v1/research-sessions/{id}` — Session status and metadata
  - `POST /api/v1/research-sessions/{id}/suspend` — Trigger session suspension
  - `POST /api/v1/research-sessions/{id}/resume` — Trigger session resumption
  - `POST /api/v1/research-sessions/{id}/checkpoints` — Create checkpoint
  - `GET /api/v1/research-sessions/{id}/timeline` — Retrieve lifecycle timeline
  - `GET /api/v1/research-sessions/{id}/workspace` — Browse workspace file hierarchy
  - `GET /api/v1/research-sessions/{id}/artifacts/{file}` — Read artifact content
- [x] Refactor `agent-lab` CLI to call the Agent Lab API via HTTP client (`agent-lab/cli/client.py`)
- [x] Provide complete unit test coverage (13 tests passing in `tests/unit/`)

### 2. Interactive Web UI
- [x] **Dashboard:**
  - Active research session count, running agents, suspended agents, recorded checkpoints
  - Active research session cards with duration, workspace link, and status
  - Health & connectivity status indicators
- [x] **Research Session Experience:**
  - Header: Task ID, Workspace ID, Agent ID, Worker node, Checkpoint, Started timestamp
  - **Timeline:** Visual audit trail of lifecycle transitions, external waits, checkpoints, and worker reclamation
  - **Workspace Explorer:** Interactive file tree for `/workspace` with Markdown artifact preview pane
  - **Agents & Identity:** Identity details, OIDC token attributes, agent capabilities, and allowed/denied communication topologies
  - **Control Actions:** Suspend, Resume, Checkpoint, Branch action triggers
- [x] **Policy Simulator:**
  - Interactive evaluation of the contextual intersection model with live scope resolution display

---

## Milestone 3 — Real Agent Identity (Completed & Empirically Verified)

**Goal:** Turn Experiment 2/3 into an actual identity subsystem (*Can we identify it?*).

```text
Agent Creation ──► Identity Issuance ──► Task-Scoped Identity ──► Execution ──► Suspend ──► Migrate ──► Resume ──► Identity Remains Valid
```

- [x] Integrate pluggable OIDC-compatible identity mechanism (`OIDCWorkloadIdentityProvider`) via `IdentityProviderInterface`
- [x] Implement **Agent Registry** service (`services/agents/registry.py`) tracking logical roles, tenants, capabilities, and lifecycle states
- [x] Bind task-scoped identity tokens into AX Task definitions via environment variables and durable `/workspace/.identity/token.jwt`
- [x] Empirically prove: Dynamically created agents receive stable, verifiable identities across worker migrations (Worker A $\rightarrow$ Worker B)
- [x] Documented in [experiments/003-agent-identity/results.md](experiments/003-agent-identity/results.md)

---

## Milestone 4 — Trust & Scope Plane (Completed & Empirically Verified)

**Goal:** Turn Experiment 4 into a real capability- and policy-based authorization service (*Can we control what it is allowed to do?*).

$$\text{Effective Scope} = \text{Evaluate}(\text{Identity}, \text{Task Context}, \text{Workspace Context}, \text{Requested Capability}, \text{Delegated Authority}, \text{Policy Constraints})$$

- [x] Implement **Capability Registry** (`web_research`, `document_analysis`, `repo_read`, `code_review`, `code_generation`, `prod_deploy`)
- [x] Implement **Policy Engine Service** evaluating the 6-dimension contextual intersection model
- [x] Build **Scope Issuer** generating short-lived, task-bound authorization tokens with invocation quotas
- [x] Implement in-path **Agent Gateway Authorizer** enforcing dual token verification (Workload Identity + Scope Token) and anti-theft subject binding
- [x] Ensure fail-closed enforcement across all dimension boundaries and persist audit provenance to SQLite
- [x] Documented in [experiments/004-trust-and-scope/results.md](experiments/004-trust-and-scope/results.md)

---

## Milestone 5 — Agent Communication (Completed & Empirically Verified)

**Goal:** Implement inter-agent collaboration and gateway enforcement (*Can multiple agents safely collaborate?*).

$$\text{Child Scope} \subseteq \text{Parent Scope}$$

```text
Agent A ("I need document_analysis") ──► Capability Registry ──► Policy Evaluation ──► Eligible Agents ──► Agent Gateway ──► Agent B
```

- [x] Implement inter-agent delegation protocols through the `CommunicationManager` and `DelegationEngine`
- [x] Enforce the core security invariant: $\text{Child Scope} \subseteq \text{Parent Scope}$ (authority escalation blocked fail-closed)
- [x] Enforce fail-closed security at the **Agent Gateway** with dual verification and anti-theft subject binding
- [x] Reconstruct multi-hop delegation provenance chains ($A \to B \to C$) from immutable SQLite audit logs
- [x] Documented in [experiments/005-multi-agent-delegation/results.md](experiments/005-multi-agent-delegation/results.md)

---

## Milestone 6 — Checkpoint Branching (Completed & Empirically Verified)

**Goal:** Fork durable state and authorization context into competing execution branches (*Can we fork their state?*).

Core Invariant:
$$\text{Branch Authorization} \subseteq \text{Source Authorization}$$

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

- [x] Implement Checkpoint Branching Controller (`services/checkpoints/branching.py`)
- [x] Enforce the core state invariant: $\text{Branch Authorization} \subseteq \text{Source Authorization}$
- [x] Clone checkpoint state and materialize branch-specific workspaces with zero cross-contamination
- [x] Assign dedicated task-scoped identity and communication scopes per branch
- [x] Enable branches to commit independent checkpoints ($C_{2A}, C_{2B}$) with parent provenance
- [x] Reconstruct complete Directed Acyclic Graph (DAG) lineage from immutable SQLite store
- [x] Documented in [experiments/006-checkpoint-branching/results.md](experiments/006-checkpoint-branching/results.md)

---

## Milestone 7 — Speculative Execution (Completed & Empirically Verified)

**Goal:** Compete, evaluate, and promote branches (*Can we run competing autonomous branches and promote the result?*).

```text
                    Checkpoint
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
        Agent A      Agent B      Agent C
      (Hypothesis) (Hypothesis) (Hypothesis)
           │            │            │
           └────────────┼────────────┘
                        ▼
                Evaluation Matrix
                   (7 Dimensions)
                        ▼
                Winning Promotion
                        │
                        ▼
                   Primary HEAD
```

- [x] Implement Speculative Execution Controller (`services/speculative/controller.py`) orchestrating concurrent hypothesis branches
- [x] Build Multi-Dimensional Evaluation Matrix evaluating 7 dimensions (Correctness, Evidence, Completeness, Efficiency, Reliability, Policy Compliance, Reproducibility) with explicit configurable weights
- [x] Enforce strict policy compliance disqualification: zero-tolerance rejection of unauthorized / escalating branches
- [x] Implement Branch Promotion Controller (`services/speculative/promoter.py`) advancing Primary HEAD atomically and idempotently
- [x] Enforce core Milestone 7 invariant: **Promotion changes the active state reference, not the historical truth of the execution graph**
- [x] REST API endpoints (`/speculative/run`, `/speculative/promote`, `/speculative/head`, `/speculative/evaluations`) & CLI commands (`agent-lab speculative run`, `promote`, `head`, `evaluations`)
- [x] End-to-end empirical verification documented in [experiments/007-speculative-execution/results.md](experiments/007-speculative-execution/results.md)

---

## Current Status & Next Action

- **Milestone 1 — Durable Agent:** **Completed and Empirically Validated** ([experiments/001-persistent-research/results.md](experiments/001-persistent-research/results.md)).
- **Milestone 2 — Control Plane + API + Web UI:** **Completed and Verified**.
- **Milestone 3 — Real Agent Identity:** **Completed and Empirically Validated** ([experiments/003-agent-identity/results.md](experiments/003-agent-identity/results.md)).
- **Milestone 4 — Trust & Scope Plane:** **Completed and Empirically Validated** ([experiments/004-trust-and-scope/results.md](experiments/004-trust-and-scope/results.md)).
- **Milestone 5 — Safe Delegation:** **Completed and Empirically Validated** ([experiments/005-multi-agent-delegation/results.md](experiments/005-multi-agent-delegation/results.md)).
- **Milestone 6 — Checkpoint Branching:** **Completed and Empirically Validated** ([experiments/006-checkpoint-branching/results.md](experiments/006-checkpoint-branching/results.md)).
- **Milestone 7 — Speculative Execution & Promotion:** **Completed and Empirically Validated** ([experiments/007-speculative-execution/results.md](experiments/007-speculative-execution/results.md)).
- **Architecture Sequence Complete:** Identify $\to$ Authorize $\to$ Delegate $\to$ Branch $\to$ Compete $\to$ Promote.

