# Experiment 001 — Expected Results & Verification Criteria

## 1. Expected Lifecycle Sequence

| Phase | Agent State | AX Task Phase | Substrate Actor State | Physical Worker Status |
|---|---|---|---|---|
| **Launch** | Initializing | `Pending` → `Running` | `Running` | 1 Worker Allocated |
| **Research** | Literature parsing & theorem matrix | `Running` | `Running` | Active (CPU/RAM consumed) |
| **Wait** | `WAITING_FOR_EXTERNAL_API` | `Running` | `Waiting` | Active until suspended |
| **Suspend** | Checkpointed to disk | `Suspended` | `Suspended` / `Snapshotting` | **Worker Released** (0 Workers Allocated) |
| **Resume** | Restoring | `Resumed` → `Running` | `Restoring` → `Running` | 1 Worker Allocated (possibly different worker node) |
| **Complete** | Final report written | `Completed` / `Running` | `Completed` | Released back to pool |

---

## 2. Verification Checkpoints

### Checkpoint A: Durable State File
Before suspension, the agent must have created `/workspace/state.json`:
- `role`: `"research"`
- `job_id`: Non-empty external operation identifier
- `status`: `"WAITING_FOR_EXTERNAL_JOB"` or intermediate synthesis state
- `checkpoint_step`: Non-zero progress indicator

### Checkpoint B: Physical Worker Reclamation
When `ax get task exp001-research-agent` reports `Suspended`:
- `kubectl get workerpools.ate.dev -n ate-system` or `kubectl get pods -n ax-system -l app=worker-pool` shows no active gVisor containers bound to the actor.
- Physical compute resources are freed for other tasks.

### Checkpoint C: Resumption & State Continuity
Upon calling `./scripts/resume.sh exp001-research-agent`:
- The task transitions back to `Running`.
- The agent process detects `/workspace/state.json`.
- The agent does **not** re-run phase A synthesis from scratch.
- The external job ID matches the one initiated prior to suspension.

### Checkpoint D: Final Report Synthesis
The completed run must produce `/workspace/report.md` containing:
- Title: *"OpenClaw Research Agent: Distributed Systems Synthesis Report"*
- Persona: `Research Agent`
- Operation Type: `synthesis`
- Section: *"Infrastructure Continuity & Integrity Stamp"*
- Job Created Exactly Once confirmation.
