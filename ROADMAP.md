# Agent Lab Roadmap

## Milestone 0 — Platform Foundation

**Goal:** Establish clean repository foundation, system context, and environment verification.

- [x] Create Agent Lab repository structure
- [x] Document production-shaped architecture in [SYSTEM_CONTEXT.md](file:///home/berrybytes/Office/agent/agent-lab/SYSTEM_CONTEXT.md)
- [x] Document execution roadmap in [ROADMAP.md](file:///home/berrybytes/Office/agent/agent-lab/ROADMAP.md)
- [x] Verify existing AX + Agent Substrate KinD cluster environment via [scripts/setup.sh](file:///home/berrybytes/Office/agent/agent-lab/scripts/setup.sh)
- [x] Provide initial operational scripts and experiment 001 protocol

---

## Milestone 1 — Production-Shaped Persistent Research Agent

**Goal:** Implement the control-plane abstractions, domain contracts, lifecycle state machine, and AX Adapter to run, suspend, reclaim, resume, and audit a durable research agent.

### Phase 1: Domain & API Contracts
- [ ] Define OpenAPI 3.0 specification for research sessions, tasks, and checkpoints ([api/openapi.yaml](file:///home/berrybytes/Office/agent/agent-lab/api/openapi.yaml))
- [ ] Implement core domain models ([domain/sessions/](file:///home/berrybytes/Office/agent/agent-lab/domain/sessions/), [domain/tasks/](file:///home/berrybytes/Office/agent/agent-lab/domain/tasks/), [domain/workspaces/](file:///home/berrybytes/Office/agent/agent-lab/domain/workspaces/))
- [ ] Implement formal lifecycle state machine with validation and invariants ([domain/lifecycle/](file:///home/berrybytes/Office/agent/agent-lab/domain/lifecycle/))
- [ ] Implement idempotency and audit trail mechanics

### Phase 2: Orchestration & AX Adapter
- [ ] Build typed AX Adapter ([adapters/ax/](file:///home/berrybytes/Office/agent/agent-lab/adapters/ax/)) abstracting Task/Workspace lifecycle operations away from raw shell scripts
- [ ] Build metadata store interface with SQLite/Postgres persistence ([adapters/storage/](file:///home/berrybytes/Office/agent/agent-lab/adapters/storage/))
- [ ] Build Orchestrator service ([services/orchestrator/](file:///home/berrybytes/Office/agent/agent-lab/services/orchestrator/)) coordinating state transitions and worker reclamation
- [ ] Implement platform CLI ([cli/](file:///home/berrybytes/Office/agent/agent-lab/cli/)) exposing `agent-lab research create|status|suspend|resume|logs`

### Phase 3: Live Verification & Testing
- [ ] Execute `exp001-research-agent` through the Orchestrator and CLI
- [ ] Verify automatic / policy-driven detection of `WAITING_FOR_EXTERNAL_API`
- [ ] Suspend task and verify physical gVisor worker reclamation in `worker-pool`
- [ ] Resume task and verify state restoration from `/workspace/state.json`
- [ ] Verify final research report generation at `/workspace/report.md`
- [ ] Add automated unit and integration tests for state machine, adapter, and idempotency

---

## Milestone 2 — Autonomous Event-Driven Control Loop

**Goal:** Connect the runtime observer and callback receiver to Agent Lab's Event Bus so that suspensions and resumptions happen automatically without operator polling.

- [ ] Implement Agent Lab webhook listener / Event Consumer
- [ ] Ingest observer events (`TASK_WAITING`, `TASK_RESUMED`, `SNAPSHOT_SAVED`)
- [ ] Apply automated suspension policies based on idle timeout and external job type
- [ ] Calculate and record exact compute savings (`worker_seconds_saved`)

---

## Milestone 3 — Explicit Checkpoint Management

**Goal:** Treat checkpoints as first-class, immutable platform artifacts.

- [ ] Implement Checkpoint Manager
- [ ] Snapshot `/workspace` metadata, file manifests, and RustFS memory snapshot references
- [ ] Expose checkpoint inspection and listing via API and CLI
- [ ] Validate deterministic restore from historical checkpoints

---

## Milestone 4 — Speculative Task Branching

**Goal:** Fork a checkpointed research session into competing execution branches.

```
checkpoint-003
      │
      ├── branch-A (Hypothesis A)
      ├── branch-B (Hypothesis B)
      └── branch-C (Test-Driven Approach)
```

- [ ] Implement Branch Manager
- [ ] Clone checkpoint state and materialize branch-specific workspaces
- [ ] Launch parallel AX Tasks with differentiated objectives
- [ ] Execute branches concurrently across the worker pool
- [ ] Stream branch-specific telemetry and logs

---

## Milestone 5 — Quantitative Branch Comparison & Promotion

**Goal:** Compare speculative branches against quantitative metrics and promote the winning state.

- [ ] Collect branch metrics (correctness, test coverage, artifact depth, duration, token cost)
- [ ] Generate comparative analysis matrix and markdown report
- [ ] Implement branch promotion semantics (reintegrate winning branch into primary session)
- [ ] Archive rejected branches for auditability and lineage tracking

---

## Milestone 6 — Native AX Branching Integration

**Goal:** Seamlessly adopt native stateful branching when available in AX.

- [ ] Benchmark native AX branching vs. Agent Lab application-level branching
- [ ] Implement native AX branching driver in the AX Adapter
- [ ] Maintain consistent `ResearchSession` and `Branch` user-facing contracts

---

## Current Focus

We are executing **Milestone 1**:
1. Domain models & API contract
2. Formal lifecycle state machine with idempotency
3. AX Adapter & metadata persistence
4. Orchestrator & CLI integration
5. End-to-end verification of `exp001-research-agent`
