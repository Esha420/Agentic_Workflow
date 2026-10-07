# Agent Lab — Production Architecture Specification

## 1. Architectural Philosophy: "Production-Shaped, Iteration-Scaled"

**Agent Lab** is an **interactive control plane for durable, stateful, multi-agent research sessions**, built on top of [Google AX](https://github.com/google/ax) and **Agent Substrate**.

### The Composition Principle
> **Agent Lab owns application-level semantics and trust decisions; AX owns task orchestration; Agent Substrate owns isolated agent execution and state restoration. Agent Lab does not replace AX or Substrate—it composes them into a higher-level durable, interactive, multi-agent research platform.**

The platform enforces a three-tier separation of concerns:
1. **Agent Lab:** The **Application & Control Plane** governing application semantics, research sessions, agent orchestration, and trust/authorization.
2. **AX:** The **Infrastructure Orchestration Layer** managing Kubernetes CRDs (`Task`, `Workspace`, `Gateway`), task lifecycle reconciliation, and actor mapping.
3. **Agent Substrate:** The **Isolated Execution Substrate** providing gVisor hardware-isolated worker scheduling, runtime actor sandboxing, and RustFS S3 memory checkpointing.

The new identity and dynamic scope subsystem is introduced as an independent **Trust & Communication layer** sitting within the Agent Lab Control Plane, governing authorization without disturbing the foundational Milestone 1 lifecycle and checkpointing architecture.

---

## 2. Evolved System Topology

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

## 3. Decoupling the CLI: Promoting CLI to a Client

In the initial prototype, the CLI acted as the entrypoint directly invoking the Manager. The evolved architecture promotes the CLI to **one of several first-class clients** communicating with the platform exclusively through the **Agent Lab API**:

```
                 ┌── CLI (`agent-lab`)
                 │
                 ├── Web UI (Operator Dashboard)
                 │
                 ├── REST / OpenAPI Clients
                 │
                 └── External Integrations (Slack / CI-CD)
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

Running `agent-lab research create` in the terminal issues `POST /api/v1/research-sessions` to the Agent Lab API. No separate code paths exist for CLI execution versus Web UI execution.

---

## 4. Trust & Scope Plane (Trust & Communication Layer)

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

### 4.1 Two Distinct Identity Dimensions

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

### 4.2 The Four-Stage Authorization Model

We maintain a strict conceptual distinction between authentication, capability definition, contextual policy evaluation, and scope issuance:

```
OIDC
  │
  ▼
Authentication / Identity
  │  "Who is this agent?"
  ▼
Agent Registry
  │
  ▼
Capabilities / Attributes
  │  "What can this type of agent potentially do?"
  ▼
Policy Engine
  │
  ▼
Task + Workspace + Delegation + Constraints
  │  "What may it do RIGHT NOW in this specific context?"
  ▼
Scope Issuer
  │
  ▼
Short-Lived Authorization Token
     "What is this agent authorized to perform?"
```

### 4.3 Dynamic Scope Evaluation (Intersection Model)

Authorization is not a simple additive sum; it is evaluated at invocation time as the **intersection** of identity, task context, workspace boundaries, requested capability, delegated authority, and policy rules:

$$\text{Effective Scope} = \text{Evaluate}(\text{Identity}, \text{Task Context}, \text{Workspace Context}, \text{Requested Capability}, \text{Delegated Authority}, \text{Policy Constraints})$$

```text
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

### 4.4 Inter-Agent Delegation
When Agent A invokes Agent B:
1. Agent A presents its capability request to the **Scope & Trust Plane**.
2. The **Policy Engine** evaluates the intersection above (ensuring $\text{Child Scope} \subseteq \text{Parent Scope}$).
3. If approved, a short-lived scoped invocation token is issued for Agent B.
4. An immutable **AuditEvent** is recorded in the metadata store.

### 4.5 The Dual Identity Model: Logical Agentic Identity (OIDC) over Workload Identity (SPIFFE)

Agent Lab does not replace AX's workload identity. Instead, it adds another orthogonal identity dimension:

| Layer | Protocol | Question Answered | Lifecycle |
|---|---|---|---|
| **Agent Lab / OIDC** | **OIDC / JWT** | *"Who is this logical autonomous agent, acting in what task/workspace context?"* | **Durable & portable:** Follows the logical agent across suspension, checkpointing, branching, and worker migration. |
| **AX / Substrate** | **SPIFFE / mTLS** | *"What workload/Actor is currently executing and communicating?"* | **Execution-bound:** Associated with the current Actor/workload and managed by the substrate. |

> **Integration Boundary:** Agent Lab implements the integration boundary required for an external OIDC provider and empirically validates the resulting identity and authorization model through `ExternalOIDCProviderAdapter`. In production, this adapter can be replaced with a live `Auth0ProviderAdapter` or `ZitadelProviderAdapter` without altering any M3–M7 invariants.

```text
Logical Agent
      │
      │ durable identity
      ▼
Agent Lab OIDC
      │
      │ executes through
      ▼
AX Actor
      │
      │ workload identity
      ▼
SPIFFE
      │
      ▼
Worker
```

```text
                    ┌──────────────────────────┐
                    │ External OIDC Provider   │
                    │ Auth0 / ZITADEL / Ory    │
                    └────────────┬─────────────┘
                                 │
                         Federated Identity
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │       Agent Lab          │
                    │                          │
                    │ Agent Registry           │
                    │ Identity Manager         │
                    │ Policy Engine            │
                    │ Delegation Engine        │
                    └────────────┬─────────────┘
                                 │
                    Task-scoped Agent JWT
                    + coarse dynamic scope
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │     Agent Gateway        │
                    │                          │
                    │ JWT validation           │
                    │ Task/workspace binding   │
                    │ Scope enforcement        │
                    │ Fine-grained policy      │
                    │ Audit                    │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │      AX / Substrate      │
                    │                          │
                    │ Actor                    │
                    │ SPIFFE workload identity │
                    │ mTLS                     │
                    │ Sandbox                  �- **AX / Substrate:** Enforces physical actor isolation and SPIFFE mTLS transport.

---
nsport.
ogical identity and coarse capability boundary.
- **Policy Engine:** Determines whether the specific tool, path regex, remaining quota, and delegation depth permit the operation right now.
- **AX / Substrate:** Enforces physical actor isolation and SPIFFE mTLS transport.
└────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │      AX / Substrate      │
                    │                          │
                    │ Actor                    │
                    │ SPIFFE workload identity │
                    │ mTLS                     │
                    │ Sandbox                  │
                    └────────────┬─────────────┘
                                 │
                              Worker
```

#### Dynamic Authorization Context Progression
The issued JWT carries coarse, cryptographically signed claims (e.g. `scope: "document:read web:search"`). The token itself is an immutable signed statement: *"This agent was issued these coarse capabilities."*

What is dynamic is the **authorization context progression**:
$$\text{Agent Creation} \longrightarrow \text{Capabilities Determined} \longrightarrow \text{Scope Issued} \longrightarrow \text{Gateway Invocations} \longrightarrow \text{Policy / Quota / Delegation State Changes} \longrightarrow \text{Effective Authorization Changes}$$

The **Agent Gateway & Policy Engine** evaluate every invocation in real time:
- **JWT:** Confirms logical identity and coarse capability boundary.
- **Policy Engine:** Determines whether the specific tool, path regex, remaining quota, and delegation depth permit the operation right now.
- **AX / Substrate:** Enforces physical actor isolation and SPIFFE mTLS transport.


---

## 5. Expanded ResearchSession Domain Contract

The `ResearchSession` entity is expanded from a simple task wrapper into the **unit of durable context and authorization context**:

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

### Deterministic Lifecycle State Machine
$$\text{CREATED} \rightarrow \text{STARTING} \rightarrow \text{RUNNING} \leftrightarrow \text{WAITING} \rightarrow \text{SUSPENDING} \rightarrow \text{SUSPENDED} \rightarrow \text{RESUMING} \rightarrow \text{RUNNING} \rightarrow \text{COMPLETED}$$
Every transition is guarded by optimistic locking (`version`), validated against invariants, and recorded in `audit_events`.

---

## 6. User Interface Specification & Mental Model

The Web UI exposes the Agent Lab mental model rather than raw infrastructure containers.

### 6.1 Dashboard
Provides top-level situational awareness across sessions, agents, and compute states:
```
Dashboard
┌──────────────────────────────────────────────────────────────┐
│ Agent Lab                                      Esha  ● Online │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Research Sessions        Running Agents       Suspended     │
│       12                       4                    7         │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ Active Research                                             │
│                                                              │
│  Security Architecture Investigation                         │
│  ● RUNNING        Agent: researcher-27                       │
│  Workspace: security-research                                │
│  Duration: 4h 12m                                            │
│                                                              │
│  [Open Session]                                              │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ Recent Activity                                              │
│                                                              │
│  11:02 Agent researcher-27 suspended                         │
│  10:59 External API waiting detected                         │
│  10:58 Checkpoint cp-184 created                             │
│  10:51 Agent reviewer-04 completed review                    │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 Research Session View (Primary Experience)
The core operational view displaying live task metadata, execution timeline, workspace tree, agent states, and lifecycle actions:
```
Security Architecture Investigation
────────────────────────────────────────────────────────────

RUNNING

Task                 T-482
Workspace            ws-security
Agent                researcher-27
Worker               worker-2
Checkpoint           cp-184
Started              Oct 7, 06:51

────────────────────────────────────────────────────────────

TIMELINE

06:51  Session created
06:52  Agent started
07:04  Repository cloned
07:31  Research notes updated
08:02  External API requested
08:02  Agent waiting
08:03  Checkpoint created
08:03  Worker reclaimed
09:41  Agent resumed
10:12  Research continued
10:54  Reviewer requested

────────────────────────────────────────────────────────────

WORKSPACE

📁 research/
  📄 findings.md
  📄 architecture.md
  📄 experiments.md
📁 code/
📁 artifacts/

────────────────────────────────────────────────────────────

AGENTS

researcher-27       ● RUNNING
reviewer-04         ● WAITING
security-agent-12   ● SUSPENDED

────────────────────────────────────────────────────────────

[ Suspend ] [ Resume ] [ Checkpoint ] [ Branch ]
```

### 6.3 Agent Identity & Scope Inspector
Provides real-time visibility into workload identity, active capabilities, and communication authorizations:
```
Agents
────────────────────────────────────────────

researcher-27

Identity
  Provider:       OIDC
  Subject:        agent:researcher-27
  Role:           research-agent
  Tenant:         acme
  Environment:    staging

Capabilities
  ✓ web_research
  ✓ document_analysis
  ✓ repository_read

Current Scope
  Task:           T-482
  Workspace:      WS-12
  Expires:        11:12
  Delegation:     1

Communication
  → reviewer-04       ALLOWED
  → coder-17          ALLOWED
  → deployment-01     DENIED

[ View Policy ] [ View Audit ]
```

### 6.4 Dynamic Agent Communication Graph
Visualizes authorized communication topologies generated on the fly from active policies and task context:
```
                         ┌──────────────┐
                         │   Planner    │
                         │ researcher-01│
                         └──────┬───────┘
                                │
                         code_review
                                │
                                ▼
                       ┌────────────────┐
                       │    Reviewer    │
                       │   agent-27     │
                       └───────┬────────┘
                               │
                         review_result
                               │
                               ▼
                       ┌────────────────┐
                       │     Coder      │
                       │   agent-42     │
                       └────────────────┘

                       ✕
                  Deployment Agent
                  (not authorized)
```

### 6.5 Policy Simulator
Allows operators to test and verify authorization policies against speculative actions before running multi-agent tasks:
```
Policy Simulator
─────────────────────────────────────────────

Caller:        researcher-27
Action:        invoke
Capability:    code_review
Target:        reviewer-04
Task:          T-482
Workspace:     WS-security
Environment:   staging

             [ Evaluate ]

─────────────────────────────────────────────

✓ ALLOWED

Reason:
  Identity             ✓ research-agent
  Capability           ✓ code_review
  Task scope           ✓ T-482
  Workspace            ✓ WS-security
  Environment          ✓ staging
  Delegation depth     ✓ 1 / 2
  TTL                  ✓ valid

Effective Scope:
  code_review
  repository: read-only
  TTL: 15 minutes
  max_calls: 10
```

---

## 7. Multi-Milestone Progression Architecture

The engineering progression is structured around the core research narrative:

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

## 8. Layer Implementation Mapping

| Layer | Directory | Implementation Components |
|---|---|---|
| **API Contract** | `api/` | OpenAPI 3.0 specification (`openapi.yaml`), REST route definitions |
| **Domain** | `domain/` | `ResearchSession`, `Task`, `Workspace`, `Checkpoint`, `AgentIdentity`, `CapabilityScope`, `Policy`, `LifecycleStateMachine` |
| **Trust & Scope** | `services/trust/` | `WorkloadIdentityProvider`, `AgentRegistry`, `PolicyEngine`, `DelegationManager`, `PolicySimulator` |
| **Control Services** | `services/orchestrator/` | `ResearchSessionService`, `LifecycleCoordinator`, `WorkerReclamationMonitor`, `BranchManager` |
| **Adapters** | `adapters/` | `ClusterAXAdapter` (typed AX control plane interface), `StorageAdapter` (SQLite/PostgreSQL metadata, audit store) |
| **Clients** | `cli/` & `ui/` | CLI client (`agent-lab research create|status|suspend|resume`), Web UI (Dashboard, Session View, Graph, Simulator) |
| **Testing** | `tests/` | Unit, integration, and policy simulation test suites |
