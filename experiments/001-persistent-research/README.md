# Experiment 001 — Persistent Research Agent

## Objective

Validate that an autonomous research agent can:
1. Initialize a structured research workspace in `/workspace`.
2. Perform literature indexing, ontology parsing, and proof matrix construction.
3. Call an asynchronous external tool/API and enter a state of waiting (`WAITING_FOR_EXTERNAL_API`).
4. Atomically persist its execution state to `/workspace/state.json`.
5. Undergo an `ax suspend` triggered by the runtime observer, flushing memory state and **releasing its physical gVisor worker back to the pool**.
6. Undergo an `ax resume` upon job completion, restoring execution on any available worker.
7. Recover accumulated state from `/workspace`, verify continuity, and output the final research report at `/workspace/report.md`.

---

## Directory Structure

```
001-persistent-research/
├── README.md                 # Experiment overview and protocol
├── research-objective.md     # Research topic, ontology, and hypotheses
├── workspace.yaml            # Experiment-specific AX Workspace
├── task-template.yaml        # AX Task manifest
├── gateway.yaml              # Egress network allowlist
└── expected-results.md       # Validation criteria and verification commands
```

---

## Lifecycle Flow

```
Agent Starts (Research Role)
          │
          ▼
Parse Ontology & Literature
          │
          ▼
Write Initial Notes to /workspace/state.json
          │
          ▼
Submit Async Job to External API / MCP
          │
          ▼
Enter Waiting State (WAITING_FOR_EXTERNAL_API)
          │
          ▼
Runtime Observer Triggers `ax suspend task`
          │
          ▼
Agent Substrate Checkpoints Sandbox State & Releases Worker
          │  (Zero CPU/RAM occupied during wait)
          ▼
External Job Finishes (Webhook Callback Triggered)
          │
          ▼
Callback Receiver / Controller Triggers `ax resume task`
          │
          ▼
Task Restored onto Available Worker
          │
          ▼
Agent Reads /workspace/state.json & Resumes Execution
          │
          ▼
Final Synthesis Written to /workspace/report.md
```

---

## Execution Protocol

Run via the Agent Lab helper scripts:

```bash
# 1. Create and launch research session
./scripts/create-research-task.sh research-session-001

# 2. Watch task execution and observe transition to SUSPENDED
./scripts/ax.sh watch task research-session-001

# 3. Verify worker pool reclamation in Agent Substrate
./scripts/check-workers.sh

# 4. Observe automatic or manual resume
./scripts/resume.sh research-session-001

# 5. Inspect generated research artifacts
./scripts/ax.sh ssh research-session-001 -- cat /workspace/report.md
```
