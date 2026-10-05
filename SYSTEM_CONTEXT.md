# Agent Lab — System Context

## 1. Project Purpose & Definition

**Agent Lab** is a **control-plane platform for durable AI research sessions**, built on top of [Google AX](https://github.com/google/ax) and **Agent Substrate**.

The system moves beyond short-lived, stateless chatbot loops and treats AI agents as **durable, inspectable, checkpointable computational processes**:

- **Accumulate State:** Retain code, research findings, documentation, tool outputs, and environment changes in a durable, versioned `/workspace`.
- **Suspend & Reclaim:** Detect when an agent is waiting for external events or human input, checkpoint its state, and reclaim expensive gVisor worker compute.
- **Resume Seamlessly:** Restore the agent hours or days later on another worker with its workspace, research notes, and execution trajectory intact.
- **Speculative Task Branching:** Fork a checkpointed research state into competing hypothesis branches (e.g., Approach A vs. Approach B vs. Test-Driven Approach), execute them independently, compare outcomes, and promote the winner.

### Core Architectural Principle
> **"Don't build a production-scale system; build a production-shaped system."**
> 
> We introduce the exact boundaries, contracts, observability, security, lifecycle management, configuration, and failure handling that a real platform requires, while keeping the implementation concise, transparent, and iterable.

---

## 2. Core Research Question

> **Can an AI agent be treated as a durable, inspectable, checkpointable computational process rather than as a sequence of independent model calls?**

Agent Lab investigates this through two fundamental capabilities:
1. **Long-Lived Research Sessions:** Durable `/workspace`, external wait detection, hardware sandbox suspension, worker pool reclamation, and seamless resumption.
2. **Speculative Task Branching:** Cloning checkpointed workspace and execution state to run competing hypotheses in parallel, quantitatively comparing artifacts and metrics, and promoting the best outcome.

---

## 3. Production Architecture Topology

```
                         ┌──────────────────────┐
                         │    Operator / UI     │
                         │  CLI / API / Slack   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │    Agent Lab API     │
                         │                      │
                         │  Auth / Validation   │
                         │  Research Sessions   │
                         │  Tasks / Branches    │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │     Orchestrator     │
                         │                      │
                         │  Lifecycle Manager   │
                         │  Checkpoint Manager  │
                         │  Branch Manager      │
                         └──────────┬───────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
               AX Adapter      Metadata DB      Event Bus
                    │         (PostgreSQL)
                    ▼
             ┌──────────────┐
             │      AX      │
             │ Task         │
             │ Workspace    │
             │ Gateway      │
             └──────┬───────┘
                    │
                    ▼
             Agent Substrate
                    │
             ┌──────┴──────┐
             ▼             ▼
          Worker 1       Worker 2
          (gVisor)       (gVisor)
             │             │
             ▼             ▼
          Agent A        Agent B

┌────────────────────────────────────────────────────────────┐
│                    Platform Concerns                       │
│                                                            │
│ Identity │ RBAC │ Secrets │ Audit │ Metrics │ Logs │ Trace │
└────────────────────────────────────────────────────────────┘
```

---

## 4. Separation of Concerns: Control Plane vs. Execution Plane

The fundamental boundary is between **what should happen** (Control Plane) and **how the workload runs** (Execution Plane).

```
                CONTROL PLANE (Agent Lab)
        ┌─────────────────────────────────────────┐
        │  ResearchSession │ Task │ Checkpoint    │
        │  Branch │ Artifact │ Policy │ Audit     │
        │                                         │
        │  Session Manager  • Task Orchestrator   │
        │  Checkpoint Manager • Branch Manager    │
        │  Suspension Policy Engine               │
        └────────────────────┬────────────────────┘
                             │
                             │ Typed API / Events
                             ▼
                EXECUTION PLANE (AX + Substrate)
        ┌─────────────────────────────────────────┐
        │  AX                                     │
        │  • Task & Workspace CRDs                │
        │  • Gateway Egress Filtering             │
        │  • Task Lifecycle Reconciler            │
        │                                         │
        │  Agent Substrate                        │
        │  • gVisor Hardware-Isolated Sandboxes   │
        │  • Pre-warmed WorkerPool Scheduling     │
        │  • RustFS S3 Memory Checkpoint Store    │
        └─────────────────────────────────────────┘
```

### Control Plane (Agent Lab owns)
- `ResearchSession` lifecycle and domain abstractions
- Dynamic task templating and execution mapping
- Checkpoint registry, lineage, and metadata
- Speculative branch coordination and objective overrides
- Branch artifact comparison and winner promotion
- Application-level audit logging, idempotency, and policies

### Execution Plane (AX + Agent Substrate owns)
- Workload container execution and sandbox sandboxing
- gVisor KVM-isolated worker placement and scheduling
- Low-level sandbox memory checkpointing and restoration
- Worker pool resource reclamation during task suspension
- Workspace durable volume persistence across migrations
- Gateway egress network allowlisting

---

## 5. Domain Model & Entities

```
     ┌───────────────────────┐
     │    ResearchSession    │
     └───────────┬───────────┘
                 │ 1
                 │
                 │ *
     ┌───────────▼───────────┐         ┌───────────────────────┐
     │         Task          │◄────────┤       Workspace       │
     └───────────┬───────────┘         │  (Repo, Notes, MCP)   │
                 │ 1                   └───────────┬───────────┘
                 │                                 │ versioned
                 │ *                               │
     ┌───────────▼───────────┐                     │
     │      Checkpoint       │◄────────────────────┘
     └───────────┬───────────┘
                 │ 1
                 │
                 │ *
     ┌───────────▼───────────┐
     │        Branch         │
     └───────────────────────┘
```

### ResearchSession
The root entity representing an investigation.
- `id`: Unique session identifier (e.g., `rs-investigate-auth-7f9a`)
- `status`: Current session status (`CREATED`, `STARTING`, `RUNNING`, `WAITING`, `SUSPENDED`, `COMPLETED`, `FAILED`, `CANCELLED`)
- `objective`: High-level research goal
- `workspace_id`: Reference to persistent workspace
- `active_task_id`: Identifier of current active execution task
- `created_at` / `updated_at`: Timestamps

### Task
An isolated unit of execution scheduled via the AX Adapter.
- `id`: Task identifier in AX (e.g., `task-rs-investigate-auth-1`)
- `session_id`: Parent research session
- `phase`: Current AX execution phase (`Pending`, `Running`, `Suspended`, `Completed`, `Failed`)
- `worker_node`: Worker node hosting the sandbox
- `started_at` / `finished_at`: Execution window

### Checkpoint
An immutable snapshot of session state at a specific point in time.
- `id`: Checkpoint ID (`chk-001`)
- `session_id`: Parent session
- `task_id`: Origin task
- `workspace_version`: Snapshot identifier or hash of `/workspace`
- `execution_state`: AX checkpoint reference (S3 snapshot key)
- `created_at`: Timestamp
- `metadata`: Phase indicator, open tools, external job IDs

### Branch
A speculative execution forking from a specific checkpoint.
- `id`: Branch identifier (`br-approach-a`)
- `parent_session_id`: Origin session
- `source_checkpoint_id`: Root checkpoint
- `task_id`: Dedicated AX task executing the branch
- `objective`: Hypothesis or targeted variation
- `status`: Execution status
- `result`: Structured output or patch artifact
- `metrics`: Quantitative evaluation (tokens, runtime, tests, cost)

---

## 6. Formal Lifecycle State Machine

Transitions between states are explicit, validated, and audited.

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

### Valid Transition Table

| Current State | Event | Target State | Action / Invariant |
|---|---|---|---|
| `CREATED` | `start` | `STARTING` | Validate config, bind workspace, create AX Task |
| `STARTING` | `task_ready` | `RUNNING` | Worker allocated, sandbox started |
| `RUNNING` | `wait_event` | `WAITING` | Agent dispatched async external request |
| `WAITING` | `suspend` | `SUSPENDING` | Trigger `ax suspend task`, initiate memory snapshot |
| `SUSPENDING` | `suspended` | `SUSPENDED` | Snapshot confirmed in RustFS; **worker released** |
| `SUSPENDED` | `resume` | `RESUMING` | External callback or operator triggers `ax resume task` |
| `RESUMING` | `resumed` | `RUNNING` | Sandbox restored on available worker; `/workspace` attached |
| `RUNNING` | `complete` | `COMPLETED` | Research objective accomplished, `/workspace/report.md` written |
| `*` | `fail` | `FAILED` | Process error, sandbox crash, or policy violation |
| `*` | `cancel` | `CANCELLED` | Explicit operator cancellation |

---

## 7. First-Class Platform Concerns

### 7.1 Idempotency & Concurrency
Network timeouts, duplicate webhooks, or retried operator commands must never cause duplicate tasks or invalid state transitions.
- Every mutating request includes an `idempotency_key` and `request_id`.
- Every transition validates against an optimistic lock version `version` on the entity.
- If a duplicate operation is received, the existing entity state is returned immediately without re-executing.

### 7.2 Observability & Telemetry
Every operation emits structured metadata with distributed tracing:
- **Trace Context:** `trace_id`, `span_id`, `session_id`, `task_id`, `branch_id`.
- **Platform Metrics:**
  - `agent_lab_sessions_total{status}`
  - `agent_lab_tasks_active`
  - `agent_lab_suspensions_total`
  - `agent_lab_resumptions_total`
  - `agent_lab_worker_seconds_saved` (Active vs. Suspended duration)
  - `agent_lab_checkpoint_duration_seconds`

### 7.3 Security & Sandbox Boundaries
- **Workload Isolation:** Agents execute inside gVisor (`runsc`) sandboxes with KVM hardware virtualization.
- **Network Filtering:** Outbound egress is strictly governed by the AX Gateway allowlist.
- **Tenant Boundaries:** Research workspaces are bound strictly to their originating session; an agent in Session A cannot access Session B's filesystem or secrets.
- **Secret Zero:** Credentials for external tools are injected at the Gateway/MCP layer, never baked into agent images or persisted in `/workspace`.

### 7.4 Git-like Semantics for Workspace State
State is treated as a versioned directed acyclic graph:
- **Workspace:** The root repository of accumulated notes, findings, and code.
- **Checkpoint:** Immutable snapshot equivalent to a `commit`.
- **Branch:** Forked execution equivalent to a `branch`.
- **Promotion:** Reintegration of winning branch artifacts equivalent to a `merge`.

---

## 8. Failure Handling & Testing Strategy

A production-shaped platform explicitly accounts for infrastructure failure:
1. **Unit Tests:** State machine transition validation, policy evaluation, schema parsing.
2. **Integration Tests:** Adapter communication with AX control plane and PostgreSQL metadata store.
3. **End-to-End Tests:** Full lifecycle verification: Create $\rightarrow$ Run $\rightarrow$ Wait $\rightarrow$ Suspend $\rightarrow$ Reclaim $\rightarrow$ Resume $\rightarrow$ Complete.
4. **Failure Injection Tests:**
   - Worker crash during active execution
   - Network timeout during `suspend` or `resume`
   - Duplicate callback webhooks
   - AX Control Plane temporary unavailability
   - Workspace mount failure or corrupted snapshot

---

## 9. Non-Goals (Iterative Boundaries)

To keep the platform agile while production-shaped:
- We will not build a custom container runtime (we leverage Substrate's gVisor).
- We will not write a custom storage driver (we leverage Substrate's RustFS S3 snapshot store).
- We will not replace AX's Task/Workspace CRD reconciler.
- We will implement production-shaped interfaces, domain services, and CLI tools that interact with AX through clean adapters rather than ad-hoc shell scripts.
