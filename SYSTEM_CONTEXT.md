# Agent Lab — System Context

## 1. Project Purpose & Definition

**Agent Lab** is an **interactive control plane for durable, stateful, multi-agent research sessions**, built on top of [Google AX](https://github.com/google/ax) and **Agent Substrate**.

The system moves beyond short-lived, stateless chatbot loops and treats AI agents as **durable, inspectable, checkpointable, and securely communicating computational processes**:

- **Accumulate State:** Retain code, research findings, documentation, tool outputs, and environment changes in a durable, versioned `/workspace`.
- **Suspend & Reclaim:** Detect when an agent is waiting for external events or human input, checkpoint its execution state, and reclaim expensive physical gVisor worker compute.
- **Resume Seamlessly:** Restore the agent hours or days later on another worker with its workspace, research notes, and execution trajectory intact.
- **Client Decoupling:** The CLI is promoted to a client of the unified **Agent Lab API**, sharing the exact same backend control plane as the interactive **Web UI** and external integrations.
- **Trust & Scope Plane:** Identity (OIDC/workload tokens), dynamic capabilities, and task-scoped policies govern agent-to-agent communication without requiring static peer-to-peer permissions.
- **Speculative Task Branching:** Fork a checkpointed research state into competing hypothesis branches (e.g., Approach A vs. Approach B vs. Test-Driven Approach), execute them independently with branch-scoped identities, compare outcomes, and promote the winner.

### Foundational Architectural Principles

> **The Composition Principle:**
> 
> **Agent Lab owns application-level semantics and trust decisions; AX owns task orchestration; Agent Substrate owns isolated agent execution and state restoration. Agent Lab does not replace AX or Substrate—it composes them into a higher-level durable, interactive, multi-agent research platform.**

> **"Don't build a production-scale system; build a production-shaped system."**
> 
> We introduce the exact boundaries, contracts, observability, security, lifecycle management, configuration, and failure handling that a real platform requires, while keeping the implementation concise, transparent, and iterable.

---

## 2. Core Research Story: The Seven Progressive Questions

Agent Lab structures its engineering progression around seven foundational questions:

```text
M1: Can an agent survive?
       │  (Durable state + suspend/resume + worker reclamation)
       ▼
M2: Can humans operate it?
       │  (Unified API + interactive Web UI + client-decoupled CLI)
       ▼
M3: Can we identify it?
       │  (Verifiable workload identity + Agent Registry)
       ▼
M4: Can we control what it is allowed to do?
       │  (Dynamic capability & policy-based authorization)
       ▼
M5: Can multiple agents safely collaborate?
       │  (Inter-agent capability delegation + communication graph + policy simulation)
       ▼
M6: Can we fork their state?
       │  (Durable checkpoint branching with isolated task & authorization context)
       ▼
M7: Can we run competing autonomous branches and promote the result?
          (Speculative execution + quantitative comparison + winner promotion)
```

---

## 3. Production Architecture Topology

```
                         ┌──────────────────────────────┐
                         │       Agent Lab UI           │
                         │                              │
                         │  Research Sessions           │
                         │  Live Agent Activity         │
                         │  Tasks / Workspaces          │
                         │  Checkpoints / Timeline      │
                         │  Branches / Comparisons      │
                         │  Agent Communication Graph   │
                         │  Policies / Policy Simulator │
                         └──────────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │       Agent Lab API          │
                         │                              │
                         │  Authentication              │
                         │  Session API                 │
                         │  Task API                    │
                         │  Checkpoint API              │
                         │  Branch API                  │
                         │  Agent / Scope API           │
                         └──────────────┬───────────────┘
                                        │
              ┌─────────────────────────▼─────────────────────────┐
              │              AGENT LAB CONTROL PLANE              │
              │                                                    │
              │  ResearchSession Manager                           │
              │  Lifecycle Manager                                 │
              │  Checkpoint Manager                                │
              │  Branch Manager                                    │
              │  Agent Discovery / Capability Manager              │
              │  Communication / Delegation Manager                │
              └───────────────┬───────────────────┬────────────────┘
                              │                   │
                    ┌─────────▼────────┐  ┌──────▼───────────┐
                    │  Trust & Scope   │  │ Metadata / Event │
                    │  Plane           │  │ Infrastructure   │
                    │                  │  │                  │
                    │  Workload Identity│ │ PostgreSQL       │
                    │  Agent Registry  │  │ Event Bus        │
                    │  Capabilities    │  │ Audit Events     │
                    │  Policy Engine   │  │                  │
                    │  Delegation      │  │                  │
                    └─────────┬────────┘  └──────────────────┘
                              │
                              │ scoped authorization
                              ▼
                       ┌───────────────┐
                       │      AX       │
                       │               │
                       │ Task          │
                       │ Workspace     │
                       │ Gateway       │
                       │ Orchestration │
                       └───────┬───────┘
                               │
                               ▼
                       ┌───────────────┐
                       │    Substrate  │
                       │               │
                       │ gVisor Actors │
                       │ State         │
                       │ Checkpoints   │
                       └───────────────┘
```

---

## 4. Separation of Concerns: Architectural Layers

The system maintains a clean three-tier separation of concerns:

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

```
┌────────────────────────────────────────────────────────────────────────┐
│                   AGENT LAB (Application & Control Plane)              │
│                                                                        │
│ • ResearchSession abstraction & lifecycle state machine                │
│ • Checkpoint lineage and speculative branching coordinator             │
│ • Unified API serving CLI, Web UI, and external integrations           │
│ • Trust & Scope Plane: Workload identities, capabilities, policy engine│
│ • Inter-agent delegation, communication graph, policy simulator        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Scoped Task/Workspace requests
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               AX (Infrastructure Orchestration Layer)                  │
│                                                                        │
│ • Kubernetes CRDs: Task, Workspace, Gateway                            │
│ • Gateway egress network allowlisting                                  │
│ • Task lifecycle reconciler & actor scheduling mapping                 │
│ • Low-level suspend and resume triggers (`ax suspend` / `ax resume`)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Worker allocation & actor lifecycle
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             AGENT SUBSTRATE (Isolated Execution Substrate)             │
│                                                                        │
│ • gVisor KVM-isolated worker sandboxes (`runsc`)                       │
│ • Pre-warmed WorkerPool scheduling and reclamation                     │
│ • Low-level sandbox memory checkpointing & restoration (RustFS S3)     │
│ • Durable volume mounts across physical worker migrations              │
└────────────────────────────────────────────────────────────────────────┘
```

Agent Lab does not duplicate AX's task reconciliation or Substrate's worker pool management. It orchestrates high-level research intent and delegates execution to AX.

---

## 5. Client Decoupling: Promoting the CLI to a Client

The CLI is an interface to Agent Lab, not Agent Lab itself. All user interfaces and external integrations converge on the unified **Agent Lab API**:

```
                 ┌── CLI (`agent-lab`)
                 │
                 ├── Web UI (Interactive Dashboard)
                 │
                 ├── REST / OpenAPI Clients
                 │
                 └── External Integrations (Slack, Webhooks)
                         │
                         ▼
                 Agent Lab API
                         │
                         ▼
             Agent Lab Control Plane
```

### Unified Request Flow
Both CLI and Web UI execute identical domain pipelines:
```
UI / CLI
  │
  ▼
POST /api/v1/research-sessions
  │
  ▼
ResearchSessionService
  │
  ▼
Trust & Scope Validation
  │
  ▼
AX Adapter
  │
  ▼
AX Task CRD
```

---

## 6. Trust & Scope Plane (Trust & Communication Layer)

The Trust & Scope Plane provides verifiable identity, capability registration, dynamic authorization, and delegated communication for multi-agent workflows.

```
AX Task Creation
      │
      ▼
Workload Identity
      │
      ▼
OIDC / OIDC-compatible identity token
      │
      ▼
Agent Registry
      │
      ▼
Capability / Policy Evaluation
```

> **Selected Identity Architecture:**
> Task-scoped OIDC-compatible JWT workload identity is the selected identity architecture. OIDC/JWT workload identity remains the implementation direction for Milestone 3, with the concrete identity-provider integration (e.g. Kubernetes projected ServiceAccount tokens or dedicated token issuer) to be finalized during Milestone 3 implementation.

### 6.1 Two Distinct Identity Dimensions

```
Human Operator                               AI Agent Workload
      │                                             │
      ▼                                             ▼
OIDC Login                                    AX Task Creation
      │                                             │
      ▼                                             ▼
Agent Lab UI / API                            Workload Identity
      │                                             │
      ▼                                             ▼
User Identity & Roles                         OIDC Token (Agent Registry)
      │                                             │
      ▼                                             ▼
Authorized Platform Operations                Capabilities & Task Scopes
                                                    │
                                                    ▼
                                              Policy Engine Evaluation
```

1. **Human Identity:** Operators and researchers authenticate via OIDC to interact with the Agent Lab UI and API.
2. **Agent Identity:** Dynamically scheduled agents receive verifiable workload identities via OIDC-compatible tokens linked to their task, tenant, and environment.

### 6.2 The Four-Stage Authorization Model

We maintain a strict conceptual distinction between authentication, capability definition, and contextual authorization:

| Stage | Responsible Component | Question Answered |
|---|---|---|
| **Authentication** | OIDC Identity Provider | *"Who is this agent?"* |
| **Capability Registry** | Agent Registry | *"What can this type of agent potentially do?"* |
| **Policy Evaluation** | Policy Engine | *"What may it do RIGHT NOW in this specific context?"* |
| **Scope Issuance** | Scope Issuer | *"What is this agent authorized to perform?"* |

### 6.3 Dynamic Scope Evaluation (Intersection Model)

Authorization is not a simple additive sum; it is evaluated at call time as the **intersection** of identity, task context, workspace boundaries, requested capability, delegated authority, and policy rules:

$$\text{Effective Scope} = \text{Evaluate}(\text{Identity}, \text{Task Context}, \text{Workspace Context}, \text{Requested Capability}, \text{Delegated Authority}, \text{Policy Constraints})$$

```
                         Identity
                            ∩
                       Task Context
                            ∩
                    Workspace Boundary
                            ∩
                        Capability
                            ∩
                    Delegated Authority
                            ∩
                          Policy
                            │
                            ▼
                     Effective Scope
```

### 6.4 Inter-Agent Communication & Delegation
When Agent A invokes Agent B:
1. Agent A requests capability invocation from the **Scope & Trust Plane**.
2. The **Policy Engine** evaluates the intersection above.
3. If approved, a short-lived scoped invocation token is issued for Agent B.
4. An immutable **AuditEvent** is recorded in the metadata store.

---

## 7. Expanded ResearchSession Domain Model

The `ResearchSession` entity is the **unit of durable context and authorization context**:

```
ResearchSession
├── Identity
│   ├── owner           # Human researcher / operator
│   └── tenant          # Organization / tenant boundary
│
├── Task
│   ├── id              # Active AX Task ID
│   ├── phase           # Current execution phase
│   └── worker_node     # Assigned gVisor worker pod
│
├── Workspace
│   ├── id              # Persistent workspace reference
│   └── root_path       # Durable volume mount (/workspace)
│
├── Agents
│   ├── primary agent   # Lead research agent
│   ├── delegated agents# Child/specialist agents (reviewer, coder)
│   └── capabilities    # Registered capability set
│
├── Authorization
│   ├── scopes          # Dynamic effective scopes
│   ├── policies        # Tenant and session-level policies
│   └── delegation chain# Depth and invocation restrictions
│
├── Checkpoints
│   ├── lineage         # Directed acyclic graph of checkpoints
│   └── active_chk      # Head checkpoint reference
│
├── Branches
│   └── active_branches # Active speculative execution branches
│
├── Events
│   └── timeline        # Event stream (waits, suspends, resumes)
│
└── Results
    ├── report_path     # Final synthesis report (/workspace/report.md)
    └── artifacts       # Generated findings, code patches, logs
```

---

## 8. Formal Lifecycle State Machine

Transitions between states are deterministic, validated against domain invariants, and recorded in audit logs.

```
                 ┌─────────────┐
                 │   CREATED   │
                 └──────┬──────┘
                        │ start()
                        ▼
                 ┌─────────────┐
                 │   STARTING  │
                 └──────┬──────┘
                        │ task_ready()
                        ▼
                 ┌─────────────┐
          ┌─────►│   RUNNING   │◄─────┐
          │      └──────┬──────┘      │
          │             │ wait_event()│
          │             ▼             │
          │      ┌─────────────┐      │
          │      │   WAITING   │      │
          │      └──────┬──────┘      │
 resume() │             │ suspend()   │
          │             ▼             │
          │      ┌─────────────┐      │
          │      │ SUSPENDING  │      │
          │      └──────┬──────┘      │
          │             │ confirmed() │
          │             ▼             │
          │      ┌─────────────┐      │
          └──────┤  SUSPENDED  │      │
                 └──────┬──────┘      │
                        │ resume()    │
                        ▼             │
                 ┌─────────────┐      │
                 │  RESUMING   ├──────┘
                 └─────────────┘
```

### Transition Table

| Current State | Event | Target State | Invariant / Action |
|---|---|---|---|
| `CREATED` | `start` | `STARTING` | Validate config, bind workspace, issue AX Task CRD |
| `STARTING` | `task_ready` | `RUNNING` | Worker allocated, sandbox active |
| `RUNNING` | `wait_event` | `WAITING` | Agent dispatched asynchronous external request |
| `WAITING` | `suspend` | `SUSPENDING` | Trigger `ax suspend task`, initiate memory snapshot |
| `SUSPENDING` | `suspended` | `SUSPENDED` | Snapshot confirmed in RustFS; **worker released** |
| `SUSPENDED` | `resume` | `RESUMING` | External callback or operator triggers `ax resume task` |
| `RESUMING` | `resumed` | `RUNNING` | Sandbox restored on available worker; `/workspace` attached |
| `RUNNING` | `complete` | `COMPLETED` | Objective met, `/workspace/report.md` finalized |
| `*` | `fail` | `FAILED` | Process error, container crash, or policy violation |
| `*` | `cancel` | `CANCELLED` | Explicit operator cancellation |

---

## 9. Platform Concerns

### 9.1 Idempotency & Optimistic Concurrency
- Every mutating request includes an `idempotency_key` and `request_id`.
- Entity mutations check an optimistic version lock (`version`) to prevent race conditions.

### 9.2 Observability & Telemetry
- Structured events emitted to PostgreSQL and the Event Bus with distributed tracing (`trace_id`, `span_id`, `session_id`, `task_id`).
- Real-time compute tracking (`worker_seconds_saved` during suspension).

### 9.3 Security & Sandbox Boundaries
- **gVisor Isolation:** Agents execute inside `runsc` sandboxes with KVM virtualization.
- **Gateway Allowlist:** Egress traffic is strictly controlled by AX Gateway rules.
- **Dynamic Scope Enforcement:** Inter-agent calls are mediated by the Trust & Scope Policy Engine.

### 9.4 Git-like Semantics for Research State
- **Workspace:** Durable working directory of code, notes, and data.
- **Checkpoint:** Immutable snapshot (`commit`).
- **Branch:** Speculative hypothesis branch (`branch`).
- **Promotion:** Merging the winning hypothesis back into the primary lineage (`merge`).

---

## 10. Multi-Milestone Platform Evolution

| Milestone | Purpose | Research Question | Status |
|---|---|---|---|
| **1. Durable Agent** | Prove persistent state + suspend/resume + worker reclamation | *Can an agent survive?* | ✅ Verified |
| **2. API + Web UI** | Make Agent Lab interactive and client-independent | *Can humans operate it?* | Next |
| **3. OIDC Agent Identity** | Establish verifiable workload identity | *Can we identify it?* | Planned |
| **4. Dynamic Scope** | Introduce capability/policy-based authorization | *Can we control what it is allowed to do?* | Planned |
| **5. Multi-Agent Communication** | Actually exercise dynamic authorization | *Can multiple agents safely collaborate?* | Planned |
| **6. Checkpoint Branching** | Fork durable state and authorization context | *Can we fork their state?* | Planned |
| **7. Speculative Execution & Promotion** | Compete, evaluate, and promote branches | *Can we run competing autonomous branches and promote the result?* | Planned |

---

## 11. Non-Goals (Iterative Boundaries)

- We do not replace AX's Task/Workspace CRD reconciler.
- We do not build a custom container runtime (we leverage Substrate's gVisor).
- We do not write a custom storage driver (we leverage Substrate's RustFS S3 snapshot store).
- We do not enforce static peer-to-peer permissions; all communication is dynamic and task-scoped.
