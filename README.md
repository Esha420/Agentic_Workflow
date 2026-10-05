# Agent Lab

> **A persistent, checkpointable research environment where an agent can work for days, sleep when idle, resume with its workspace intact, and fork its execution state into competing speculative branches.**

---

## 1. Overview

**Agent Lab** is an experimental platform for building long-lived, stateful AI agents on top of [Google AX](https://github.com/google/ax) and **Agent Substrate**.

Rather than treating AI agents as short-lived, stateless chatbot loops that discard their context between runs, Agent Lab models agents as **durable, inspectable, checkpointable computational processes**:

- **Accumulate State:** Retain code, research findings, documentation, tool outputs, and environment changes in a durable `/workspace`.
- **Suspend & Reclaim:** Detect when an agent is waiting for external events or user input, checkpoint its state, and reclaim expensive gVisor worker compute.
- **Resume Seamlessly:** Restore the agent hours or days later on another worker with its workspace, research notes, and execution trajectory intact.
- **Speculative Task Branching:** Fork a checkpointed research state into competing hypothesis branches (e.g., Approach A vs. Approach B vs. Test-Driven Approach), execute them independently, compare outcomes, and promote the winner.

---

## 2. Conceptual Architecture

```
                         ┌─────────────────────┐
                         │    Agent Lab CLI    │
                         │  create / run /     │
                         │  suspend / resume   │
                         │  branch / compare   │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   Research Manager  │
                         │                     │
                         │ task lifecycle      │
                         │ checkpoints         │
                         │ branches            │
                         │ results             │
                         └──────────┬──────────┘
                                    │
                       ┌────────────┴────────────┐
                       │                         │
                       ▼                         ▼
                ┌─────────────┐          ┌─────────────┐
                │     AX      │          │ Metadata DB │
                │             │          │             │
                │ Task        │          │ research    │
                │ Workspace   │          │ sessions    │
                │ Gateway     │          │ branches    │
                └──────┬──────┘          └─────────────┘
                       │
                       ▼
                ┌─────────────┐
                │    Agent    │
                │  Substrate  │
                │             │
                │ gVisor      │
                │ workers     │
                └──────┬──────┘
                       │
                       ▼
              Persistent /workspace
                       │
              ┌────────┴────────┐
              │                 │
              ▼                 ▼
        Git repositories      Research
        notes/code/docs       artifacts
```

---

## 3. Project Progression

Agent Lab is organized around three evolutionary phases:

```
Phase 1: Long-Lived Research Agent
         │  (Persistent /workspace, external wait detection, suspend/resume, worker reclamation)
         ▼
Phase 2: Checkpoint-Aware Branching
         │  (Application-level branching controller, checkpoint metadata, state cloning)
         ▼
Phase 3: Speculative Execution & Promotion
            (Concurrent branch execution, quantitative comparison, automated promotion)
```

### Speculative Execution Flow

```
                         Research Task
                              │
                          checkpoint
                              │
                    ┌─────────┴─────────┐
                    │                   │
                 Branch A            Branch B
               (Hypothesis A)      (Hypothesis B)
                    │                   │
                 results             results
                    │                   │
                    └─────────┬─────────┘
                              │
                          comparison
                              │
                              ▼
                        winning branch
```

---

## 4. Architectural Boundaries

Agent Lab builds *on top of* AX and Agent Substrate without duplicating their core responsibilities:

| Layer | Responsibility |
|---|---|
| **AX** | Task, Workspace, and Gateway CRDs; Task lifecycle; `ax suspend` / `ax resume`; actor mapping |
| **Agent Substrate** | Actor execution, worker scheduling, gVisor isolation, sandbox checkpointing & restoration, worker reclamation |
| **Agent Lab** | `ResearchSession` abstraction, dynamic task templating, checkpoint bookkeeping, branch orchestration, result evaluation & promotion |

---

## 5. Repository Structure

```
agent-lab/
├── README.md                 # Project introduction and architecture overview
├── SYSTEM_CONTEXT.md         # Source of truth: design rationale, principles, boundaries
├── ROADMAP.md                # Multi-milestone execution plan (Milestones 0 to 7)
├── ARCHITECTURE.md           # Deep dive on data structures, interfaces, and state layers
├── DEVELOPMENT.md            # Local development, environment setup, and verification
│
├── manifests/                # Reusable AX resource templates
│   ├── workspace.yaml        # AX Workspace specification (Git, MCP, skills)
│   ├── gateway.yaml          # AX Gateway egress allowlists
│   └── task-template.yaml    # Parameterized Task template
│
├── agent/                    # Research agent workload & prompt templates
│   ├── runner/               # Agent entrypoint and execution hooks
│   ├── research/             # Literature synthesis, code investigation logic
│   └── prompts/              # Research instructions and guidance
│
├── manager/                  # Research Session & Branching Controller
│   ├── api/                  # High-level session orchestration API
│   ├── lifecycle/            # Suspend/resume orchestration and observer integration
│   ├── checkpoint/           # Checkpoint metadata store and restore logic
│   ├── branching/            # Branch creation and parallel execution
│   └── storage/              # Metadata persistence
│
├── cli/                      # Agent Lab CLI (`agent-lab create/suspend/resume/branch`)
│
├── experiments/              # Controlled experimental milestones
│   ├── 001-persistent-research/   # Milestone 1: Workspace persistence & worker reclamation
│   ├── 002-suspend-resume/        # Milestone 2: Timed external API waits & auto-suspend
│   ├── 003-worker-reclamation/    # Milestone 3: Substrate worker pool inspection
│   └── 004-speculative-branching/ # Milestone 4: Parallel branch comparison
│
└── scripts/                  # Workflow automation helpers
    ├── setup.sh
    ├── create-research-task.sh
    ├── suspend.sh
    ├── resume.sh
    └── cleanup.sh
```

---

## 6. Current Status: Milestone 1 Completed (Verified)

We adhere to the **Current Implementation Rule**: *Do not build the complete platform before proving the primitive.*

**Milestone 1 (Long-Lived Research Agent)** has been **completed and empirically validated** with full cluster evidence:
1. Reusable Research Agent Task Template dynamically instantiated via `agent-lab research create`.
2. Durable workspace state accumulated under `/workspace/research/` prior to suspension.
3. Autonomous idle wait detection triggering automatic task suspension.
4. Physical compute worker reclaimed (worker allocation dropped from 1 to 0).
5. Cross-worker migration proven: restored onto a different physical worker pod and successfully completed research synthesis.

```text
Start ──► Research and Notes ──► External Wait ──► Suspend ──► Worker Reclaimed ──► Resume ──► Continue Research
```

Complete empirical execution evidence, timestamps, worker IDs, and snapshot details are documented in [`experiments/001-persistent-research/results.md`](experiments/001-persistent-research/results.md).

For the comprehensive specification, architectural blueprints, and roadmap, see [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [ROADMAP.md](ROADMAP.md).
