# Experiment 004: Trust & Scope Plane Verification

## 1. Context & Research Objective

In Milestone 2, we established the Agent Lab application control plane, unified API, and Web UI. In Milestone 3, we implemented and verified task-scoped cryptographic workload identity (`WHO is this agent?`) with migration invariance across physical compute workers.

The central research question for **Milestone 4** is:
> **"What is this agent allowed to do right now?"**
> Can Agent Lab dynamically evaluate authorization at invocation time using contextual intersection, issue cryptographically signed, short-lived Scope Tokens with quota enforcement, repel unauthorized actions fail-closed at the Agent Gateway boundary, and preserve full audit provenance?

---

## 2. Core Architecture & Separation of Concerns

```text
       Agent Invocation Request
                  │
                  ▼
       ┌─────────────────────┐
       │   Policy Engine     │
       │   (6 Dimensions)    │
       └──────────┬──────────┘
                  │ Effective Scope
                  ▼
       ┌─────────────────────┐
       │    Scope Issuer     │───► Issues Short-Lived Scope Token (HS256 JWT, Quota-Tracked)
       └──────────┬──────────┘
                  │
                  ▼
       ┌─────────────────────┐
       │   Agent Gateway     │───► Dual Verification:
       │ In-Path Authorizer  │       1. Workload Identity Token (M3 - WHO)
       └──────────┬──────────┘       2. Scope Token (M4 - WHAT)
                  │                  3. Subject Binding Invariant (Anti-Theft)
                  ├── ALLOW / DENY
                  ▼
       ┌─────────────────────┐
       │ Persistent Audit Log│───► SQLite audit_events with actor, resource, provenance
       └─────────────────────┘
```

### The 6-Dimension Contextual Intersection Formula
$$\text{Effective Scope} = \text{Evaluate}(\text{Identity} \cap \text{Task Context} \cap \text{Workspace Context} \cap \text{Requested Capability} \cap \text{Delegated Authority} \cap \text{Policy Constraints})$$

1. **Identity Dimension:** Verified OIDC-compatible workload identity token (M3).
2. **Task Dimension:** Identity token claims `task_id` must match execution context.
3. **Workspace Dimension:** Identity token claims `workspace_id` must match target filesystem sandbox.
4. **Capability Dimension:** Target capability must be registered, and agent's `role` must be in `Capability.allowed_roles`.
5. **Action & Resource Dimension:** Requested action must be in `Capability.allowed_actions`, and target resource path must match `Capability.resource_path_pattern`.
6. **Delegation & Policy Dimension:** Delegation depth $\le$ `max_delegation_depth`; explicit `DENY` rules strictly override any `ALLOW`.

---

## 3. Experimental Test Plan (5 Phases)

1. **Phase 1: Capability Registry & Typed Boundaries:**
   Authoritative schema lookup for typed capabilities (`web_research`, `document_analysis`, `repo_read`, `code_review`, `code_generation`, `prod_deploy`).
2. **Phase 2: Contextual Intersection Policy Engine Evaluation:**
   Evaluation of legitimate requests yielding explicit `ALLOWED` verdict with bounded effective scope.
3. **Phase 3: Cryptographic Scope Token Issuance & Invocation Quotas:**
   Minting of short-lived Scope Tokens with quota tracking: verifying that repeated invocations decrement `invocations_remaining` until exhaustion triggers fail-closed denial.
4. **Phase 4: Fail-Closed Security Boundary Invariants (Negative Vectors):**
   - *Vector 1 (Role Mismatch):* Non-privileged role requesting restricted capability.
   - *Vector 2 (Path Escape):* Requesting access outside `/workspace/*` (e.g. `/etc/shadow`).
   - *Vector 3 (Task Mismatch):* Valid token submitted with tampered task ID.
   - *Vector 4 (Scope Theft):* Agent B attempting to use Agent A's scope token at the gateway.
   - *Vector 5 (Revoked Identity):* Revoked token rejected at the gateway.
5. **Phase 5: In-Path Gateway Authorizer & Audit Provenance:**
   Interception at Agent Gateway, dual token validation, and persistence of immutable audit events.

---

## 4. Execution Command

```bash
python3 experiments/004-trust-and-scope/run_scope_experiment.py
```
