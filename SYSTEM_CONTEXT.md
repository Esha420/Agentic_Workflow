# Agent Lab — System Context

## 1. Project Purpose

Agent Lab is an experimental platform for building long-lived, stateful AI agents on top of Google AX and Agent Substrate.

The goal is to move beyond short-lived chatbot-style agents and investigate agents that behave more like persistent computational processes:

- maintain a filesystem and working environment
- retain research artifacts and notes
- use Git repositories and MCP tools
- wait for external events without continuously consuming compute
- suspend when idle
- resume from checkpointed state
- eventually fork their execution state into multiple speculative branches
- compare branch outcomes and select or promote a result

The project is intended to become a reusable system rather than a single demonstration.

---

## 2. Core Research Question

The central question is:

> **Can an AI agent be treated as a durable, inspectable, checkpointable computational process rather than as a sequence of independent model calls?**

Agent Lab will investigate this through two capabilities.

### Capability 1 — Long-lived Research Agents

A research agent receives a persistent workspace containing:
- source repositories
- research notes
- documentation
- generated artifacts
- MCP tools
- approved external network access
- agent configuration

The agent may work for an extended period.

When the agent becomes idle or waits for an external event, the system should be able to suspend it and reclaim its worker resources.

Later, the agent should resume with its previous workspace and execution state available.

### Capability 2 — Speculative Task Branching

A checkpointed task should eventually be usable as the starting point for multiple independent tasks.

```
                    Research Task
                          │
                      checkpoint
                          │
         ┌────────────────┼────────────────┐
         │                │                │
      Branch A         Branch B         Branch C
    (Approach A)     (Approach B)     (Approach C)
         │                │                │
      results          results          results
         └────────────────┼────────────────┘
                          │
                     comparison
                          │
                          ▼
                    winning branch
```

Each branch should operate independently while preserving the common state from the checkpoint.

The branches can then be evaluated using:
- correctness
- test results
- research quality
- generated artifacts
- execution time
- token/model cost
- external API usage
- human evaluation

The best branch can eventually be promoted.

---

## 3. Platform

The system is built on:
- **Google AX**
- **Agent Substrate**
- gVisor-isolated workers
- persistent workspace storage
- AX Gateway
- MCP servers
- an agent runtime
- a project-level lifecycle manager

AX provides the fundamental task lifecycle.

Agent Substrate provides the actor execution layer and worker scheduling.

Agent Lab provides the higher-level application semantics:
- research sessions
- task creation
- lifecycle management
- checkpoints
- branches
- branch metadata
- comparison
- promotion

---

## 4. Architectural Boundary

Agent Lab must not unnecessarily reimplement functionality already provided by AX or Agent Substrate.

### AX owns
- Task resources
- Workspace resources
- Gateway resources
- task lifecycle
- task suspension
- task resumption
- task-to-actor mapping
- interaction with Agent Substrate

### Agent Substrate owns
- actor execution
- worker placement
- sandbox isolation
- actor suspension/checkpointing
- actor restoration
- worker resource reclamation

### Agent Lab owns
- research-session abstraction
- task templates
- dynamic task creation
- task metadata
- lifecycle orchestration
- checkpoint bookkeeping
- branch creation
- branch relationships
- experiment metadata
- result comparison
- branch promotion

**Principle:**
> AX and Agent Substrate provide the execution substrate. Agent Lab provides the application-level semantics.

---

## 5. Existing Environment

The initial implementation reuses the existing AX + Agent Substrate environment.

Current infrastructure includes:
- isolated KinD cluster
- AX Control Plane
- Agent Substrate WorkerPool
- multiple gVisor workers
- AX Gateway
- RustFS-backed snapshots
- OpenClaw agent runtime
- runtime observer
- callback/resume routing
- external MCP services
- Slack/terminal gateway for operator interaction

The existing suspend/resume implementation should be reused rather than replaced.

The existing runtime observer detects waiting states and can trigger:

```
Agent
  │
  ▼
WAITING_FOR_EXTERNAL_API
  │
  ▼
runtime observer
  │
  ▼
ax suspend
  │
  ▼
Agent Substrate checkpoint
  │
  ▼
worker released
```

The resume path restores the task and allows execution to continue.

---

## 6. Task Creation Model

Task manifests should be treated as templates, not as manually created instances.

The system should distinguish between:

### Task Template
Defines:
- agent image
- command
- environment
- workspace bindings
- gateway
- resource requirements

### Task Instance
Represents one actual research execution.

Instances should be created dynamically by Agent Lab.

```
research-task-template
        │
        ├── research-session-001
        ├── research-session-002
        └── research-session-003
```

Branching will use the same principle:

```
research-session-001
        │
        ├── branch-a
        ├── branch-b
        └── branch-c
```

---

## 7. Workspace Model

A Workspace represents the persistent environment available to an agent.

It may contain:
- Git repositories
- notes
- documentation
- MCP configuration
- skills
- generated artifacts
- research state

The workspace is mounted into the task, normally under:
```
/workspace
```

The workspace is considered part of the agent's state.

**Important principle:**
The agent should be able to stop and restart without losing its accumulated research environment.

AX currently describes `/workspace` as the durable directory that survives suspend/resume; the restored task receives the same files even though its process tree is recreated. This distinction is important for our design.

---

## 8. Agent State

Agent Lab treats state as multiple layers:

### Layer 1 — Filesystem State
```
/workspace/
├── research/
├── notes/
├── source/
├── artifacts/
└── .agent/
```
This contains durable research information.

### Layer 2 — Process/Execution State
The currently running agent process and its execution context.
AX + Agent Substrate are responsible for checkpointing and restoring this layer.

### Layer 3 — Application Metadata
Stored outside the task filesystem.

Example:
- `research_session`
- `task_id`
- `parent_task_id`
- `branch_id`
- `created_at`
- `checkpoint_id`
- `status`
- `objective`
- `result`
- `cost`

Agent Lab owns this metadata.

---

## 9. Research Session

A research session is the primary user-facing abstraction.

A session contains:
```
ResearchSession
├── id
├── objective
├── workspace
├── task_id
├── status
├── checkpoints
├── branches
└── artifacts
```

**Example:**
- **Session:** `investigate-repository-security`
- **Objective:** Understand the security architecture of repository X and propose three possible improvements.
- **Workspace:** `research-repository-x`
- **Task:** `research-7f29c`

The user should not need to reason directly about AX actors.

---

## 10. Checkpoints

A checkpoint represents a recoverable point in a research session.

```
Research Session
       │
       ├── Checkpoint 001
       ├── Checkpoint 002
       └── Checkpoint 003
```

A checkpoint should record:
- AX task identity
- task state
- workspace state
- timestamp
- objective
- current phase
- generated artifacts
- metadata needed for recovery

The initial implementation should rely on AX's native suspend/resume mechanism.

Agent Lab should initially record checkpoint metadata rather than implementing an independent snapshot system.

---

## 11. Branching Model

Branching is a higher-level Agent Lab feature.

A branch is derived from a checkpoint:

```
          checkpoint-003
                 │
        ┌────────┴────────┐
        ▼                 ▼
     branch-A          branch-B
        │                 │
        ▼                 ▼
     result-A          result-B
```

A branch should contain:
```
Branch
├── branch_id
├── parent_session_id
├── parent_task_id
├── source_checkpoint
├── objective_override
├── task_id
├── status
├── result
└── metrics
```

The branch must not mutate the parent's state.

---

## 12. Initial Branching Strategy

Native AX task branching may not yet be available.

Therefore the first implementation will use a higher-level branching controller.

Conceptually:
1. Suspend source task
2. Identify the checkpoint/state
3. Materialize a branch workspace/state
4. Create a new AX Task
5. Attach the branch state
6. Apply branch-specific instructions
7. Run branches independently
8. Collect results
9. Compare results

This is intentionally implemented above AX.

When AX provides native stateful branching, Agent Lab should be able to replace this mechanism without changing the user-facing research-session abstraction.

---

## 13. First Real-Life Use Case

The first real application should be a persistent software research agent.

### Example Objective
> "Investigate a GitHub repository, understand a specific architectural problem, experiment with possible solutions, document findings, and keep the research environment alive until the investigation is complete."

The agent should have:
- Repository
- Notes
- Documentation
- MCP tools
- Browser/network access
- Research instructions

The agent may work over multiple sessions.

### Example Lifecycle

```
DAY 1:
Create research session
        │
        ▼
Clone repository
        │
        ▼
Investigate architecture
        │
        ▼
Write notes
        │
        ▼
Call external API
        │
        ▼
Waiting
        │
        ▼
Suspend (worker released)

DAY 2:
Resume
        │
        ▼
Continue investigation
        │
        ▼
Form hypotheses
        │
        ▼
Checkpoint
        │
        ▼
Create branches

DAY 3:
Branch A → implementation approach A
Branch B → implementation approach B
Branch C → tests-first approach
        │
        ▼
Compare
        │
        ▼
Select best result
```

---

## 14. Design Principles

- **Principle 1 — Persistent over stateless:** The agent should accumulate useful state.
- **Principle 2 — Suspend rather than waste:** Waiting should not require a permanently allocated worker.
- **Principle 3 — State belongs to the task:** The filesystem and checkpointed execution state are part of the agent's identity.
- **Principle 4 — Separate orchestration from execution:** Agent Lab manages research semantics. AX manages task lifecycle. Agent Substrate manages execution.
- **Principle 5 — Dynamic task creation:** Users should create research sessions, not manually write one YAML file per execution.
- **Principle 6 — Branch from known state:** Speculative execution must begin from an explicit checkpoint.
- **Principle 7 — Reproducibility:** Every branch must be traceable to parent session, parent task, source checkpoint, workspace state, instructions, model configuration, and tools.
- **Principle 8 — Auditability:** A researcher should be able to answer: *"Why did this branch produce this result?"*

---

## 15. Non-Goals

The first version will **NOT** attempt to build:
- a new agent framework
- a new container runtime
- a new checkpointing system
- a replacement for AX
- a replacement for Agent Substrate
- a general-purpose workflow engine
- a fully autonomous production research platform

The purpose is to explore what becomes possible when durable agent execution is treated as a first-class primitive.

---

## 16. Success Criteria

### Milestone 1 — Persistent Agent
We can:
1. Create a research session.
2. Dynamically create its AX Task.
3. Populate a Workspace.
4. Run an agent.
5. Create meaningful research artifacts.
6. Suspend the task.
7. Verify worker resources are reclaimed.
8. Resume the task.
9. Verify the workspace and research state remain intact.
10. Continue the same investigation.

### Milestone 2 — Checkpointed Research
We can:
1. Explicitly checkpoint a research session.
2. Record checkpoint metadata.
3. Inspect checkpoint history.
4. Resume from a checkpoint.
5. Reproduce the research environment.

### Milestone 3 — Speculative Branching
We can:
1. Suspend a source task.
2. Create multiple branch tasks from the same checkpoint.
3. Give each branch a different objective.
4. Run branches concurrently.
5. Collect artifacts and metrics.
6. Compare results.
7. Identify a winning branch.

### Milestone 4 — Promotion
The winning branch can become the new primary research state.

---

## 17. Current Implementation Rule

Do not build the complete platform before proving the primitive.

Implementation order:
```
Persistent Workspace
        │
        ▼
Long-lived Agent
        │
        ▼
Suspend / Resume
        │
        ▼
Checkpoint Metadata
        │
        ▼
Research Session Manager
        │
        ▼
Branch Creation
        │
        ▼
Parallel Branch Execution
        │
        ▼
Result Comparison
        │
        ▼
Promotion
```

Each step must be demonstrated before adding the next abstraction.

---

## 18. Current Question

The first engineering question is:

> **Can we reliably create a real research session dynamically, allow the agent to accumulate state in `/workspace`, suspend it, reclaim the worker, resume it later, and continue exactly where it left off?**

Everything else depends on proving this primitive.

---

## 19. Guiding Mental Model

```
                RESEARCH SESSION
                       │
                 persistent identity
                       │
                ┌──────┴──────┐
                │             │
              TASK         WORKSPACE
                │             │
          execution       accumulated
             state            state
                │             │
                └──────┬──────┘
                       │
                  CHECKPOINT
                       │
              ┌────────┴────────┐
              │        │        │
           Branch A  Branch B  Branch C
              │        │        │
              └────────┼────────┘
                       │
                    COMPARE
                       │
                    PROMOTE
```

This is the core architecture of Agent Lab.
