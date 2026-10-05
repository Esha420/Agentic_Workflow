# Agent Lab — Production Architecture Specification

## 1. Architectural Philosophy: "Production-Shaped, Iteration-Scaled"

Agent Lab is a **control-plane platform for durable AI research sessions**, built on Google AX and Agent Substrate.

The architecture strictly separates the **Control Plane** (application semantics, session state machine, checkpoint lineage, branch comparison, policies) from the **Execution Plane** (AX Task reconciliation, Substrate gVisor sandboxing, worker pool scheduling, and RustFS S3 memory checkpointing).

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
             (Cluster / API)    (SQLite/PG)
                    │
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
```

---

## 2. Platform Core Contracts

### 2.1 ResearchSession
- **Identity:** Persistent entity representing a research investigation.
- **State Machine:** Deterministic transitions managed by `LifecycleStateMachine`:
  $$\text{CREATED} \rightarrow \text{STARTING} \rightarrow \text{RUNNING} \leftrightarrow \text{WAITING} \rightarrow \text{SUSPENDING} \rightarrow \text{SUSPENDED} \rightarrow \text{RESUMING} \rightarrow \text{RUNNING} \rightarrow \text{COMPLETED}$$
- **Optimistic Concurrency:** Every transition increments `version` to prevent race conditions from concurrent CLI / webhooks.
- **Auditability:** Every transition generates an immutable `AuditEvent` with timestamp, actor, rationale, and details.

### 2.2 Task
- **Decoupled Workload:** Isolated execution unit mapped to an AX Task CRD.
- **Zero Awareness:** The agent runtime (`openclaw`) has zero Kubernetes or Substrate awareness; it interacts exclusively with `/workspace` and standard POSIX files.

### 2.3 Checkpoint
- **State Lineage:** Captures session state, workspace generation hash, and underlying Substrate memory snapshot keys.
- **Git-like Mental Model:**
  - Workspace $\sim$ Git repository
  - Checkpoint $\sim$ Git commit
  - Branch $\sim$ Speculative execution branch
  - Promotion $\sim$ Git merge to primary HEAD

---

## 3. Layer Implementation Overview

| Layer | Directory | Implementation Components |
|---|---|---|
| **Contract** | `api/` | OpenAPI 3.0 specification (`openapi.yaml`) |
| **Domain** | `domain/` | `ResearchSession`, `Task`, `Workspace`, `Checkpoint`, `LifecycleStateMachine`, `SuspensionPolicy` |
| **Adapters** | `adapters/` | `ClusterAXAdapter` (typed AX control plane interface), `SQLiteMetadataStore` (idempotency, audit trail) |
| **Services** | `services/` | `ResearchSessionService` (lifecycle coordinator, worker reclamation monitor) |
| **Client** | `cli/` | `agent-lab` CLI (`research create`, `list`, `status`, `suspend`, `resume`, `report`) |
| **Testing** | `tests/` | Unit tests for state machine, optimistic locking, and orchestrator lifecycle |
