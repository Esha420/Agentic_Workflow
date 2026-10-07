# Agent Lab — Engineering Implementation Plan

## 1. Executive Summary & Context

Agent Lab is an **interactive control plane for durable, stateful, multi-agent research sessions**, composing Google AX and Agent Substrate into a higher-level platform:

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

With **Milestone 1 (Durable Agent)** and **Experiment 002 (Architectural Investigation)** completed and empirically verified, this implementation plan details the concrete engineering blueprint for **Milestone 2 (Agent Lab Control Plane + API + Web UI)** through **Milestone 7 (Speculative Execution)**.

```text
M1: Can an agent survive?                              ✅ Verified (Exp 001)
Architectural Investigation                            ✅ Proven (Exp 002)
M2: Can humans operate it?                             ✅ Completed & Verified (M2)
M3: Can we identify it?                                ✅ Completed & Verified (Exp 003)
M4: Can we control what it is allowed to do?           ✅ Completed & Verified (Exp 004)
M5: Can multiple agents safely collaborate?            ✅ Completed & Verified (Exp 005)
M6: Can we fork their state?                           ✅ Completed & Verified (Exp 006)
M7: Can we run competing branches & promote winner?    ✅ Completed & Verified (Exp 007)

```

---

## 2. Milestone 2 Implementation Plan: Agent Lab Control Plane + API + Web UI

### 2.1 Objectives
1. **Agent Lab Control Plane:** Build out the backend service layers governing Research Sessions, Agents, Tasks, Workspaces, Lifecycles, and Checkpoints above the AX Adapter.
2. **Unified REST API Server:** Provide high-performance, typed REST endpoints conforming to `openapi.yaml`.
3. **Client Decoupling:** Promote the CLI to an HTTP client calling the unified **Agent Lab API**, eliminating direct coupling between the CLI and internal storage/adapters.
4. **Interactive Web UI:** Provide a rich, real-time dashboard exposing the Agent Lab mental model:
   - Dashboard (sessions, active agents, reclaimed compute, activity stream)
   - Research Session View (metadata, interactive timeline, workspace tree, agent states, actions)

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

### 2.2 Target Directory Structure
```text
agent-lab/
├── api/
│   ├── openapi.yaml           # Existing OpenAPI contract
│   ├── server.py              # FastAPI / ASGI application entrypoint
│   ├── dependencies.py        # Service & store dependency injection
│   └── routes/
│       ├── __init__.py
│       ├── sessions.py        # /api/v1/research-sessions CRUD & lifecycle
│       ├── tasks.py           # /api/v1/tasks
│       ├── checkpoints.py     # /api/v1/checkpoints
│       └── workspace.py       # /api/v1/research-sessions/{id}/workspace
├── cli/
│   ├── __init__.py
│   ├── client.py              # HTTP client interacting with Agent Lab API
│   └── main.py                # CLI commands delegating to client.py
├── ui/
│   ├── index.html             # Dashboard & session explorer SPA
│   ├── css/
│   │   └── style.css          # Glassmorphic, dark-mode design system
│   └── js/
│       ├── api.js             # Frontend API client
│       ├── app.js             # Router & state management
│       ├── components/
│       │   ├── dashboard.js   # Session overview & summary metrics
│       │   ├── session.js     # Session detail, timeline, and actions
│       │   └── workspace.js   # Workspace file hierarchy explorer
└── tests/
    └── unit/
        ├── test_api.py        # FastAPI endpoint tests
        └── test_cli_client.py # CLI client HTTP tests
```

### 2.3 Step-by-Step Execution Sequence

#### Step 2.3.1: REST API Server Implementation
- **Framework:** FastAPI with Uvicorn (or standard library ASGI runner).
- **Service Dependency Injection:**
  - `ResearchSessionService`
  - `ClusterAXAdapter`
  - `StorageAdapter` (SQLite/PostgreSQL)
- **Endpoints to Implement:**
  | Method | Path | Description |
  |---|---|---|
  | `POST` | `/api/v1/research-sessions` | Create and initialize a new research session |
  | `GET` | `/api/v1/research-sessions` | List research sessions with optional status filter |
  | `GET` | `/api/v1/research-sessions/{id}` | Retrieve session details, task phase, worker node |
  | `POST` | `/api/v1/research-sessions/{id}/suspend` | Suspend running session and reclaim worker |
  | `POST` | `/api/v1/research-sessions/{id}/resume` | Resume suspended session on available worker |
  | `POST` | `/api/v1/research-sessions/{id}/checkpoints`| Explicitly create a state checkpoint |
  | `GET` | `/api/v1/research-sessions/{id}/timeline` | Retrieve timeline events and state transitions |
  | `GET` | `/api/v1/research-sessions/{id}/workspace`| Retrieve workspace file tree and artifact list |
  | `GET` | `/api/v1/healthz` | Liveness and database connectivity check |

#### Step 2.3.2: CLI Refactoring (Promote to Client)
- Create `cli/client.py`:
  - `AgentLabClient(base_url="http://localhost:8000")`
  - Encapsulates HTTP calls, timeout handling, and formatted error responses.
- Update `cli/main.py`:
  - Replace direct `ResearchSessionService` calls with calls to `AgentLabClient`.
  - Add `--api-url` flag and `AGENT_LAB_API_URL` environment variable support.
  - Retain exact CLI syntax: `agent-lab research create|status|suspend|resume|report`.

#### Step 2.3.3: Interactive Web UI Implementation
- **Design Principles:**
  - Sleek dark-mode aesthetic with modern typography (Inter/Roboto) and responsive layout.
  - Visual status badges (🟢 RUNNING, 🟡 WAITING, 🟣 SUSPENDED, 🔵 COMPLETED).
- **Core Views:**
  1. **Dashboard:**
     - Metric cards: Active Sessions, Running Agents, Suspended (Compute Reclaimed).
     - Active Research cards with duration, objective, and `Open Session` action.
     - Live activity stream showing recent audit events.
  2. **Session Detail View:**
     - Session summary header (Session ID, Task ID, Worker Node, Active Checkpoint, Duration).
     - **Timeline Component:** Visual vertical timeline showing event timestamps (Session created $\rightarrow$ Task started $\rightarrow$ External wait $\rightarrow$ Suspended $\rightarrow$ Worker reclaimed $\rightarrow$ Resumed).
     - **Workspace Explorer:** Tree view of `/workspace` displaying findings, notes, and generated reports.
     - **Control Bar:** Interactive buttons for `Suspend`, `Resume`, `Checkpoint`, `Branch`.

#### Step 2.3.4: Verification & Integration Testing
- Start API server on localhost.
- Run `agent-lab research create --topic "Testing API Client"` via CLI and verify request reaches server.
- Query `GET /api/v1/research-sessions` and assert created session is returned.
- Load UI in browser, verify session appears on Dashboard and Session Detail views.
- Trigger `suspend` via UI button and verify state changes to `SUSPENDED` with compute reclaimed.

---

## 3. Milestone 3 Implementation Plan: Real Agent Identity

### 3.1 Objective
Turn Experiment 2 and 3 into an actual identity subsystem (*Can we identify it?*).

```text
Agent Creation ──► Identity Issuance ──► Task-Scoped Identity ──► Execution ──► Suspend ──► Migrate ──► Resume ──► Identity Remains Valid
```

### 3.2 Key Technical Architecture
Task-scoped OIDC-compatible JWT workload identity is the selected identity architecture. During Milestone 3:
1. Finalize the concrete identity provider mechanism (e.g. Kubernetes projected ServiceAccount tokens or dedicated token issuer).
2. Build the **Agent Registry Service** tracking registered agent roles, tenants, and environments.
3. Bind identity tokens into AX Task definitions via projected volumes or environment variables.
4. Verify cryptographic validation survives worker migrations and state restorations.

---

## 4. Milestone 4 Implementation Plan: Trust & Scope Plane (Completed & Empirically Verified)

### 4.1 Objective
Turn Experiment 4 into a real capability- and policy-based authorization service (*Can we control what it is allowed to do?*).


$$\text{Effective Scope} = \text{Evaluate}(\text{Identity}, \text{Task Context}, \text{Workspace Context}, \text{Requested Capability}, \text{Delegated Authority}, \text{Policy Constraints})$$

### 4.2 Core Deliverables
- [x] **Capability Registry:** Typed registry of agent capabilities (`web_research`, `document_analysis`, `repo_read`, `code_review`, `code_generation`, `prod_deploy`).
- [x] **Policy Engine Service:** Evaluates the 6-dimension contextual intersection model at invocation time fail-closed.
- [x] **Scope Issuer:** Generates short-lived, task-bound Scope Tokens (`HS256` JWT) with invocation quotas.
- [x] **Agent Gateway Authorizer:** In-path authorizer intercepting invocations, enforcing dual token verification (Workload Identity + Scope Token) and anti-theft subject binding.
- [x] **Fail-Closed Verification & Provenance:** Empirically verified across 5 phases in [experiments/004-trust-and-scope/results.md](experiments/004-trust-and-scope/results.md).

---

## 5. Milestone 5 Implementation: Multi-Agent Communication & Safe Delegation (Completed)

### 5.1 Objective
Implement the inter-agent collaboration and gateway enforcement demonstrated in Experiment 005 (*Can multiple agents safely collaborate?*).

Core Security Invariant:
$$\text{Child Scope} \subseteq \text{Parent Scope}$$

An agent can delegate authority it already possesses, but can never create, transfer, or escalate authority beyond its own effective scope.

```text
                 Agent A (Parent)
                        │ Verified Identity (M3)
                        ▼
                 Effective Scope (M4)
                        │
                        ▼
               Delegation Request (M5)
                        │
                        ▼
             ┌─────────────────────┐
             │  Delegation Engine  │
             │                     │
             │  Parent Scope       │
             │  Requested Scope    │
             │  Target Agent       │
             │  Delegation Policy  │
             └──────────┬──────────┘
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
              Agent Gateway
                   │
                   ▼
             Agent B (Child)
```

### 5.2 Core Deliverables
- [x] **Agent Communication Contract:** `DelegationRequest` defining caller identity, target agent, task context, requested capabilities, actions, resource paths, TTL, and delegation depth.
- [x] **Delegation Engine:** Strict containment verification (`Child Scope ⊆ Parent Scope` across capabilities, actions, subpaths, quotas, and depth decrement).
- [x] **Provenance Chain Tracking:** Child scopes retain full provenance (`delegated_by`, `delegation_chain`, `original_subject`).
- [x] **Agent Gateway Interceptor:** In-path gateway enforcement intercepting all inter-agent traffic; validates dual tokens (M3 identity + M4/M5 scope) and checks parent revocation cascades.
- [x] **Adversarial Verification:** 10/10 adversarial test phases passed fail-closed in [experiments/005-multi-agent-delegation/results.md](experiments/005-multi-agent-delegation/results.md).

---

## 6. Milestone 6 Implementation: Checkpoint Branching (Completed)

### 6.1 Objective
Fork durable research state, creating isolated execution branches from verified checkpoints (*Can we fork their state?*).

Core Invariant:
$$\text{Branch Authorization} \subseteq \text{Source Authorization}$$

A branch may evolve its state independently, but branching must never become an authorization-escalation mechanism.

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

### 6.2 Core Deliverables
- [x] **Checkpoint Branching Controller:** [`CheckpointBranchingController`](file:///home/berrybytes/Office/agent/agent-lab/services/checkpoints/branching.py) cloning durable workspace state, AX task definitions, and state metadata.
- [x] **Branch Authorization Invariant Containment:** Mathematical verification that branch capability, actions, resource paths, quotas, and TTL are strictly bounded by source scope.
- [x] **Independent Branch Workload Identity:** Branch agents provisioned with distinct cryptographic identity tokens (`agent:br-A` vs `agent:br-B`) via M3 `IdentityManager`.
- [x] **Durable State Isolation:** Cloned workspace volumes ensure zero file cross-contamination between parallel hypothesis branches.
- [x] **Checkpoint Lineage Tree:** Reconstructs complete DAG lineage ($C_1 \to \{C_{2A}, C_{2B}\}$) from the immutable metadata store.
- [x] **Branch API & CLI:** REST endpoints (`POST /api/v1/checkpoints/{id}/branch`, `GET /api/v1/sessions/{id}/branches`, `GET /api/v1/sessions/{id}/lineage`) and CLI commands (`agent-lab branch create`, `agent-lab branch list`, `agent-lab branch lineage`).
- [x] **Empirical Verification:** 10/10 test phases passed fail-closed in [experiments/006-checkpoint-branching/results.md](experiments/006-checkpoint-branching/results.md).

---

## 7. Milestone 7 Implementation Plan: Speculative Execution (Completed & Empirically Verified)

### 7.1 Objective
Execute competing hypothesis branches concurrently, collect multi-dimensional quantitative evaluation metrics, and promote the winning branch state back into the primary lineage (*Can we run competing autonomous branches and promote the result?*).

```text
                    Verified Checkpoint
                            │
               ┌────────────┼────────────┐
               ▼            ▼            ▼
            Branch A     Branch B     Branch C
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

### 7.2 Core Deliverables
- [x] **Speculative Execution Orchestrator:** [`SpeculativeExecutionController`](file:///home/berrybytes/Office/agent/agent-lab/services/speculative/controller.py) coordinating concurrent execution runs across competing branches without bypassing Gateway, Policy Engine, Identity Manager, or Checkpoint Controller.
- [x] **Multi-Dimensional Evaluation Engine:** [`MultiDimensionalEvaluator`](file:///home/berrybytes/Office/agent/agent-lab/services/speculative/evaluator.py) evaluating the 7 dimensions:
  - Correctness
  - Evidence quality
  - Completeness
  - Efficiency
  - Reliability
  - Policy compliance (Strict zero-tolerance filter)
  - Reproducibility
- [x] **Branch Promotion Controller:** [`BranchPromotionController`](file:///home/berrybytes/Office/agent/agent-lab/services/speculative/promoter.py) atomically advancing the Primary HEAD reference while leaving historical lineage completely immutable.
- [x] **Core Milestone 7 Invariant Enforced:**
  $$\text{Promotion changes the active state reference, not the historical truth of the execution graph.}$$
- [x] **Speculative Execution API & CLI:** REST endpoints (`POST /speculative/run`, `POST /speculative/promote`, `GET /speculative/head`, `GET /speculative/evaluations`) and CLI commands (`agent-lab speculative run`, `promote`, `head`, `evaluations`).
- [x] **Experiment 007:** End-to-end empirical verification of competing autonomous branches, scoring, and promotion (10/10 test phases passed) in [`experiments/007-speculative-execution/results.md`](file:///home/berrybytes/Office/agent/agent-lab/experiments/007-speculative-execution/results.md).

---

## 8. Milestone Progression Summary

With Milestone 7 verified, the entire 7-stage architectural progression of Agent Lab is complete:

$$\text{Identify (M3)} \longrightarrow \text{Authorize (M4)} \longrightarrow \text{Delegate (M5)} \longrightarrow \text{Branch (M6)} \longrightarrow \text{Compete (M7)} \longrightarrow \text{Promote (M7)}$$


