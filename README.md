# Agent Lab

> **An interactive control plane for durable, stateful, multi-agent research sessions, with dynamically managed identity, capability, communication scope, checkpointing, and speculative execution.**

---

## 1. Overview

**Agent Lab** is a persistent, multi-agent research and experimentation platform built on top of [Google AX](https://github.com/google/ax) (Orchestration Substrate) and **Agent Substrate** (Execution Substrate).

> **The Composition Principle:**
> 
> **Agent Lab owns application-level semantics and trust decisions; AX owns task orchestration; Agent Substrate owns isolated agent execution and state restoration. Agent Lab does not replace AX or Substrate—it composes them into a higher-level durable, interactive, multi-agent research platform.**

Rather than treating AI agents as short-lived, stateless chatbot loops that discard context between runs, Agent Lab models agents as **durable, inspectable, checkpointable, and securely communicating computational processes**:

- **Accumulate State:** Retain code, research findings, documentation, tool outputs, and environment changes in a durable, versioned `/workspace`.
- **Suspend & Reclaim:** Detect when an agent is waiting for external events or human input, checkpoint its execution state, and reclaim physical gVisor worker compute.
- **Resume Seamlessly:** Restore the agent hours or days later on another worker with its workspace, research notes, and execution trajectory intact.
- **Client-Decoupled Control Plane:** The CLI is promoted to a client of the unified **Agent Lab API**, sharing the exact same backend control plane as the interactive **Web UI** and external integrations.
- **Trust & Scope Plane:** Workload identity tokens, dynamic capabilities, and task-scoped policies govern agent-to-agent communication without requiring static peer-to-peer permissions.
- **Speculative Task Branching:** Fork a checkpointed research state into competing hypothesis branches (e.g., Approach A vs. Approach B vs. Test-Driven Approach), execute them independently with branch-scoped identities, compare outcomes, and promote the winner.

---

## 2. Evolved Architecture

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

## 3. Client Decoupling: Promoting the CLI to a Client

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

Every command maps directly to API endpoints:
- `agent-lab research create` $\longrightarrow$ `POST /api/v1/research-sessions`
- `agent-lab research suspend` $\longrightarrow$ `POST /api/v1/research-sessions/{id}/suspend`
- `agent-lab research resume` $\longrightarrow$ `POST /api/v1/research-sessions/{id}/resume`
- Web UI and CLI execute identical domain workflows through `ResearchSessionService` and the `AX Adapter`.

---

## 4. Trust & Communication Layer

Agent Lab introduces identity and dynamic scope as a **Trust & Communication layer** that operates above AX without disturbing the low-level lifecycle and checkpointing architecture:

```
AX Task Creation ──► Workload Identity ──► Agent Registry ──► Capability & Policy Evaluation ──► Scope Issuance
```

### The Four-Stage Authorization Model
1. **Authentication (OIDC / Workload Identity):** *"Who is this agent?"*
2. **Capability Registry (Agent Registry):** *"What can this type of agent potentially do?"*
3. **Policy Evaluation (Policy Engine):** *"What may it do RIGHT NOW in this specific context?"*
4. **Scope Issuance (Scope Issuer):** *"What is this agent authorized to perform?"*

### Dynamic Scope Evaluation (Intersection Model)
Agents do not hold static, long-lived peer-to-peer permissions. Effective authorization is dynamically evaluated from the intersection of context and policy constraints:

$$\text{Effective Scope} = \text{Evaluate}(\text{Identity}, \text{Task Context}, \text{Workspace Context}, \text{Requested Capability}, \text{Delegated Authority}, \text{Policy Constraints})$$

The platform includes a **Policy Simulator** and dynamic **Agent Communication Graph** to inspect, test, and audit inter-agent invocation boundaries.

---

## 5. Architectural Boundaries & Mental Model

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

| Layer | Responsibility |
|---|---|
| **Agent Lab (Application & Control Plane)** | `ResearchSession` abstraction, session lifecycle state machine, checkpoint lineage, branch orchestration & comparison, Trust & Scope plane (task-scoped OIDC-compatible workload identity, agent registry, dynamic capabilities, policy engine, delegation) |
| **AX (Infrastructure Orchestration Layer)** | Task, Workspace, and Gateway CRDs; Task lifecycle reconciliation; `ax suspend` / `ax resume`; actor mapping |
| **Agent Substrate (Isolated Execution Substrate)** | Actor execution, worker scheduling, gVisor KVM isolation, sandbox checkpointing & restoration, worker pool reclamation |

---

## 6. Expanded ResearchSession Model

A `ResearchSession` is the unit of **durable context** and **authorization context**:

```
ResearchSession
├── Identity
│   ├── owner
│   └── tenant
│
├── Task
│
├── Workspace
│
├── Agents
│   ├── primary agent
│   ├── delegated agents
│   └── capabilities
│
├── Authorization
│   ├── scopes
│   ├── policies
│   └── delegation chain
│
├── Checkpoints
│
├── Branches
│
├── Events
│
└── Results
```

---

## 7. Multi-Milestone Roadmap

The evolution builds incrementally on top of Milestone 1's proven durability primitive:

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

## 8. Current Status: Milestone 1 Completed (Verified)

We adhere to the **Current Implementation Rule**: *Do not build the complete platform before proving the primitive.*

**Milestone 1 (Durable Agent)** has been **completed and empirically validated** with full cluster evidence:
1. Reusable Research Agent Task Template dynamically instantiated via `agent-lab research create`.
2. Durable workspace state accumulated under `/workspace/research/` prior to suspension.
3. Autonomous idle wait detection triggering automatic task suspension.
4. Physical compute worker reclaimed (worker allocation dropped from 1 to 0).
5. Cross-worker migration proven: restored onto a different physical worker pod and successfully completed research synthesis.

```text
Start ──► Research and Notes ──► External Wait ──► Suspend ──► Worker Reclaimed ──► Resume ──► Continue Research
```

Complete execution evidence, timestamps, worker IDs, and snapshot details are documented in [`experiments/001-persistent-research/results.md`](experiments/001-persistent-research/results.md).

For deep architectural specifications, implementation plans, and execution milestones, see [ARCHITECTURE.md](ARCHITECTURE.md), [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), and [ROADMAP.md](ROADMAP.md).
