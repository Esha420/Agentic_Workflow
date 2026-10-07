# Experiment 004 Results: Trust & Scope Plane Verification

- **Experiment ID:** `EXP-004-TRUST-AND-SCOPE`
- **Milestone:** Milestone 4 (Trust & Scope Plane)
- **Status:** **PASSED (100% SUCCESS ACROSS ALL 5 PHASES)**
- **Executed:** October 7, 2026
- **Test Runner:** [`run_scope_experiment.py`](file:///home/berrybytes/Office/agent/agent-lab/experiments/004-trust-and-scope/run_scope_experiment.py)

---

## 1. Executive Summary

Experiment 004 empirically verified the **Trust & Scope Plane** of Agent Lab. The experiment answered the foundational question: **"What is this agent allowed to do right now?"**

All five verification phases succeeded with 100% adherence to security invariants:
1. **Capability Registry:** Verified schema contracts and role/action/resource filters across 6 typed capabilities.
2. **Contextual Intersection Policy Engine:** Evaluated the 6-dimension contextual intersection model ($$Identity \cap Task \cap Workspace \cap Capability \cap Delegation \cap Policy$$) and granted bounded effective scope.
3. **Cryptographic Scope Tokens & Invocation Quotas:** Minted short-lived HS256 JWT scope tokens. Demonstrated call-by-call quota decrementing ($3 \to 2 \to 1 \to 0$) and verified fail-closed denial on quota exhaustion.
4. **Fail-Closed Boundary Invariants:** Repelled all 5 negative test vectors (role mismatch, resource path escape, task context injection, scope token theft, and identity revocation).
5. **In-Path Agent Gateway & Provenance:** Authorized valid invocations using dual-token verification (Workload Identity + Scope Token) and persisted auditable provenance records in SQLite.

---

## 2. Quantitative Phase Results

| Phase | Evaluation Target | Invariant Tested | Outcome | Status |
|---|---|---|---|---|
| **Phase 1** | Capability Registry | Typed contracts, role/action/path filters | 6 capabilities registered; all filters enforce boundary rules | **PASSED** |
| **Phase 2** | Contextual Intersection | 6-Dimension Policy Evaluation | `ALLOWED` with bounded `effective_scope` (`web_research`, `search`, `/workspace/research/sources.json`) | **PASSED** |
| **Phase 3** | Scope Tokens & Quotas | HS256 Token Minting & Quota Enforcement | 3 calls consumed ($3 \to 2 \to 1 \to 0$); 4th call fail-closed rejected | **PASSED** |
| **Phase 4** | Fail-Closed Boundaries | 5 Negative Attack/Violation Vectors | All 5 vectors blocked fail-closed (`DENIED` / `Allowed=False`) | **PASSED** |
| **Phase 5** | Gateway & Audit | Dual-Token Interception & Provenance | Valid invocation authorized; audit event persisted with full provenance | **PASSED** |

---

## 3. Detailed Phase Verification

### Phase 1: Capability Registry & Typed Contracts
The authoritative `CapabilityRegistry` was queried for all registered capabilities:
- `web_research`: Roles: `['research-agent', 'lead-researcher']`, Actions: `['fetch', 'search', 'summarize']`, Pattern: `/workspace/research/*`, TTL: `900s`.
- `document_analysis`: Roles: `['research-agent', 'reviewer-agent']`, Actions: `['read', 'analyze', 'extract']`, Pattern: `/workspace/*`, TTL: `900s`.
- `repo_read`: Roles: `['research-agent', 'coder-agent', 'reviewer-agent']`, Actions: `['read', 'search_code', 'list_files']`, Pattern: `/workspace/*`, TTL: `1200s`.
- `code_review`: Roles: `['reviewer-agent', 'research-agent']`, Actions: `['inspect', 'comment', 'approve']`, Pattern: `/workspace/*`, TTL: `900s`.
- `code_generation`: Roles: `['coder-agent']`, Actions: `['generate', 'refactor', 'patch']`, Pattern: `/workspace/*`, TTL: `600s`.
- `prod_deploy`: Roles: `['deployment-admin']`, Actions: `['deploy', 'rollback']`, Pattern: `/workspace/deploy/*`, TTL: `300s`.

*Verification:* Untrusted roles (`untrusted-role`), unauthorized actions (`format_drive`), and path escapes (`/etc/shadow`) were rejected by capability boundary methods.

### Phase 2: Contextual Intersection Policy Engine
An active agent (`researcher-42`, subject `agent:researcher-42`) with workload identity token bound to task `T-900-research` and workspace `WS-acme-research` requested `web_research:search` on `/workspace/research/sources.json`.
- **Verdict:** `ALLOWED`
- **Rule ID:** `rule-research-collaboration`
- **Effective Scope:**
  ```json
  {
    "subject": "agent:researcher-42",
    "role": "research-agent",
    "tenant": "acme-corp",
    "environment": "staging",
    "task_id": "T-900-research",
    "workspace_id": "WS-acme-research",
    "capability": "web_research",
    "granted_action": "search",
    "resource_path": "/workspace/research/sources.json",
    "max_invocations": 10,
    "ttl_seconds": 900,
    "delegation_depth": 0
  }
  ```

### Phase 3: Cryptographic Scope Tokens & Invocation Quotas
- Issued short-lived Scope Token `scp-ab716030ad` with `max_invocations = 3` and `ttl_seconds = 600`.
- Invocation 1: Validated $\to$ Invocations remaining: 2.
- Invocation 2: Validated $\to$ Invocations remaining: 1.
- Invocation 3: Validated $\to$ Invocations remaining: 0.
- Invocation 4: **Rejected fail-closed:** `ScopeIssuerError: Scope quota exhausted: 3 calls consumed`.

### Phase 4: Negative Security Invariants (5 Vectors)
1. **Role Mismatch:** `coder-agent` requesting `prod_deploy:deploy`:
   - *Outcome:* `DENIED` (`Role 'coder-agent' is not authorized for capability 'prod_deploy'`).
2. **Resource Path Escape:** `research-agent` requesting `/etc/shadow`:
   - *Outcome:* `DENIED` (`Resource path '/etc/shadow' violates capability boundary '/workspace/research/*'`).
3. **Task Context Injection:** Token bound to `T-900-research` presented for `T-TAMPERED-TASK`:
   - *Outcome:* `DENIED` (`Identity verification failed: Task binding mismatch: expected 'T-TAMPERED-TASK', token contains 'T-900-research'`).
4. **Scope Token Theft (Subject Mismatch):** `coder-88` presenting `researcher-42`'s scope token at the gateway:
   - *Outcome:* `Allowed=False` (`Gateway rejected: Scope subject 'agent:researcher-42' does not match identity subject 'agent:coder-88'`).
5. **Revoked Identity Token at Gateway:** Quarantined identity token presented at the gateway:
   - *Outcome:* `Allowed=False` (`Gateway rejected: Identity invalid (Token tok-4dd2eaa457cd is recorded as revoked in persistent store)`).

### Phase 5: Agent Gateway In-Path Authorizer & Audit Provenance
- Legitimate request intercepted at Agent Gateway boundary with valid Workload Identity Token and Scope Token.
- **Decision:** `Allowed=True`, `Audit ID = gtw-18d0deb4`, `Quota Left = 3`.
- **Audit Persistence:** Stored in SQLite `audit_events` table with:
  - `actor`: `agent-gateway`
  - `to_status`: `ALLOWED`
  - `reason`: `Invocation authorized by Agent Gateway`
  - `details`: `{'subject': 'agent:researcher-42', 'capability': 'web_research', 'action': 'search', 'resource': '/workspace/research/sources.json', 'allowed': True}`

---

## 4. Architectural Invariants Confirmed

1. **Dual-Token Gatekeeping:** The Agent Gateway strictly enforces that an agent must prove **WHO** it is (M3 Workload Identity Token) AND **WHAT** it is permitted to execute (M4 Scope Token).
2. **Anti-Theft Subject Binding:** A stolen scope token is unusable by another agent because the gateway cryptographically compares `Scope.sub == Identity.sub`.
3. **Fail-Closed by Default:** Every dimension (role, capability, action, resource, task, quota, revocation) defaults to deny if any claim or constraint fails.
4. **Independent Identity vs Policy:** The Agent Registry and Identity Manager are decoupled from capability evaluation; the Policy Engine is decoupled from execution and worker compute.

---

## 5. Progression to Milestone 5

With Milestone 4 verified, Agent Lab now has:
- **Milestone 2:** Application & Control Plane + REST API + Interactive UI ✅
- **Milestone 3:** Real Agent Workload Identity + Migration Invariance ✅
- **Milestone 4:** Trust & Scope Plane + Policy Engine + Gateway Authorizer ✅

Next: **Milestone 5 — Multi-Agent Collaboration & Safe Delegation**
("Can multiple agents securely discover, communicate, and delegate authority under bounded scope constraints?")
