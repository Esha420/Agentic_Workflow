# Agent Lab Roadmap

## Milestone 0 — Project Foundation

**Goal:** Create a clean repository and document the architecture.

- [x] Create Agent Lab repository structure
- [x] Add [SYSTEM_CONTEXT.md](file:///home/berrybytes/Office/agent/agent-lab/SYSTEM_CONTEXT.md)
- [ ] Add `ARCHITECTURE.md`
- [x] Add [ROADMAP.md](file:///home/berrybytes/Office/agent/agent-lab/ROADMAP.md)
- [ ] Document existing AX + Agent Substrate environment
- [ ] Define research-session abstraction
- [ ] Define task-template abstraction

---

## Milestone 1 — Long-Lived Research Agent

**Goal:** Create the first real persistent research agent.

### Environment
- [ ] Define reusable AX Workspace
- [ ] Define research-agent Task template
- [ ] Configure approved Gateway access
- [ ] Connect research MCP tools
- [ ] Provide Git repository access

### Research Agent
- [ ] Create research-agent image/runtime
- [ ] Give agent a persistent `/workspace`
- [ ] Define research directory structure
- [ ] Add persistent notes
- [ ] Add research objective

### Lifecycle
- [ ] Dynamically create AX Task
- [ ] Observe Task lifecycle
- [ ] Detect waiting state
- [ ] Suspend task
- [ ] Verify worker reclamation
- [ ] Resume task
- [ ] Verify workspace persistence
- [ ] Verify research continuity

### Success Test
The agent should be able to:
```
start → research → write notes → suspend
      → worker reclaimed
      → resume → read previous notes → continue
```

---

## Milestone 2 — Research Session Manager

**Goal:** Stop treating AX Tasks as the user-facing abstraction.

Introduce `ResearchSession`. The manager should maintain:
- `session_id`
- `task_id`
- `workspace`
- `objective`
- `status`
- `checkpoints`
- `artifacts`

### Tasks
- [ ] Implement session creation
- [ ] Implement dynamic AX Task creation
- [ ] Store session metadata
- [ ] Add session status
- [ ] Add suspend operation
- [ ] Add resume operation
- [ ] Add artifact tracking
- [ ] Add checkpoint records

---

## Milestone 3 — Explicit Checkpoints

**Goal:** Make checkpoints first-class application objects.

### Tasks
- [ ] Create checkpoint record
- [ ] Associate checkpoint with AX Task
- [ ] Record workspace metadata
- [ ] Record research phase
- [ ] Record artifact state
- [ ] Implement checkpoint listing
- [ ] Implement resume-from-checkpoint semantics

---

## Milestone 4 — Speculative Branching

**Goal:** Create multiple independent research executions from one checkpoint.

```
checkpoint-003
      │
      ├── branch-A
      ├── branch-B
      └── branch-C
```

### Tasks
- [ ] Define Branch object
- [ ] Define parent/child relationship
- [ ] Create branch workspace/state
- [ ] Create branch AX Tasks
- [ ] Apply branch-specific objectives
- [ ] Run branches concurrently
- [ ] Collect artifacts
- [ ] Collect execution metrics

---

## Milestone 5 — Branch Comparison

**Goal:** Determine which speculative execution produced the best result.

### Metrics
- Correctness
- Tests passed
- Artifact quality
- Research completeness
- Execution time
- Token usage
- External API usage
- Human evaluation

### Tasks
- [ ] Define result schema
- [ ] Collect branch metrics
- [ ] Generate comparison report
- [ ] Rank branches
- [ ] Select winner

---

## Milestone 6 — Branch Promotion

**Goal:** Allow the winning branch to become the primary research state.

### Tasks
- [ ] Define promotion semantics
- [ ] Preserve branch history
- [ ] Promote workspace state
- [ ] Update primary session
- [ ] Retain rejected branches for auditability

---

## Milestone 7 — Native AX Branching Integration

**Goal:** Replace custom branching mechanics when AX provides native stateful task branching.

### Tasks
- [ ] Evaluate native branching API
- [ ] Compare against Agent Lab implementation
- [ ] Replace custom branching mechanism where appropriate
- [ ] Preserve Agent Lab's ResearchSession/Branch abstraction
- [ ] Benchmark native vs application-level branching

---

## Current Priority

> **Only Milestone 0 and Milestone 1 should be implemented initially.**

Do not begin speculative branching until persistent suspend/resume has been demonstrated reliably.

The first proof should be:
```
CREATE
  │
  ▼
WORK
  │
  ▼
STATE ACCUMULATES
  │
  ▼
SUSPEND
  │
  ▼
WORKER RECLAIMED
  │
  ▼
RESUME
  │
  ▼
STATE RESTORED
  │
  ▼
CONTINUE
```
That is the foundation for everything else.
