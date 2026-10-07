# Experiment 002 — Architectural Investigation Results & Definitive Conclusions

## 1. Executive Summary

Experiment 002 executed the comprehensive verification and investigation suite across all seven core architectural questions prior to platform implementation.

### Validation Verdict Table

| Experiment | Core Question Investigated | Status | Empirical Verdict |
|---|---|---|---|
| **1. AX Dynamic Orchestration** | *Is AX capable of being the dynamic orchestration layer, or do we need an additional orchestration component above AX?* | **PROVEN** | **Agent Lab Control Plane is strictly required above AX.** AX is the infrastructure orchestration layer (reconciling Task/Workspace/Gateway CRDs); it possesses zero native agent routing, capability discovery, or delegation logic. |
| **2. Workload Identity** | *What should be the canonical identity of an Agent Lab agent?* | **PROVEN** | **Task-scoped OIDC-compatible JWT workload identity is the selected identity architecture.** Directly carries cryptographic claims (`sub`, `iss`, `aud`, `tenant`, `role`, `task_id`, `workspace_id`) without requiring heavy external SPIRE daemonsets, while maintaining compatibility with Kubernetes Projected ServiceAccount tokens. Concrete IdP integration will be finalized during Milestone 3. |
| **3. Identity Persistence** | *Does the agent's logical identity remain stable even though physical execution environment changes?* | **PROVEN** | **Identity persists seamlessly across worker migrations.** Logical identity ($I_{\text{agent}}$) is bound to the durable session/task context, remaining stable and cryptographically valid when restored from Worker A (`2s6cd`) to Worker B (`8b9vz`). |
| **4. Dynamic Authorization** | *Can effective scope be calculated dynamically from context rather than maintaining static agent-to-agent permissions?* | **PROVEN** | **Contextual Intersection Model succeeds.** `Evaluate(Identity, Task Context, Workspace Context, Requested Capability, Delegated Authority, Policy Constraints)` dynamically computes effective scopes and fails closed across all violation dimensions. |
| **5. Dynamic Discovery** | *Can agents discover eligible peers by capability instead of static names?* | **PROVEN** | **Capability-based discovery completely replaces hardcoded agent names.** System dynamically resolves `"I need document_analysis"` $\rightarrow$ Capability Registry $\rightarrow$ Policy filter $\rightarrow$ Eligible agent, with automated failover when agents suspend. |
| **6. Delegation & Enforcement** | *Where is the actual security boundary, and does it enforce Child Scope ⊆ Parent Scope?* | **PROVEN** | **Security boundary is at the Agent Gateway.** Enforces $\text{Child Scope} \subseteq \text{Parent Scope}$ (authority escalation denied). Tested 5 invalid request permutations; **100% failed closed** (401/403). |
| **7. API/UI Control Plane Boundary** | *Can CLI/UI/other clients operate the same Agent Lab API without bypassing the architecture, and can transactions be fully reconstructed?* | **PROVEN** | **Unified API contract proven.** CLI, Web UI, and external integrations invoke identical REST endpoints. Structured audit logging captures full transaction provenance. |

---

## 2. Detailed Experimental Findings

### Experiment 1: AX Dynamic Orchestration Verification

**Investigated Question:** *Can AX dynamically create, select, route, and delegate agents, or do we need an additional orchestration component above AX?*

#### Cluster & Controller Inspection
Inspection of `ax-system/ax-controller` and `ax-system/ax-server`:
- `ax-controller` reconciles Kubernetes CRDs (`Task`, `Workspace`, `Gateway`) into Agent Substrate actors via `api.ate-system.svc.cluster.local:443`.
- `ax apply -f` dynamically instantiates tasks and binds workspaces.
- **Critical Architectural Limitation Identified:**
  - AX has **no concept of agent roles or personas**.
  - AX has **no Capability Registry**.
  - AX has **no inter-agent message routing** or peer-to-peer discovery.
  - AX has **no delegation mechanics** or policy engine.
  - When an agent is suspended or becomes unavailable, AX merely transitions the task phase to `Suspended`; it does not autonomously select or route work to an alternative agent.

#### Definitive Conclusion
**AX is the infrastructure orchestration layer**, while **Agent Substrate is the isolated execution substrate**. The **Agent Lab Control Plane** is strictly required above AX to govern capability discovery, peer selection, inter-agent delegation, failover routing, and research session semantics.

---

### Experiment 2: Agent Workload Identity Verification

**Investigated Question:** *What should be the canonical identity of an Agent Lab agent?*

#### Comparative Analysis
We compared four identity architectures:
1. **Kubernetes Projected ServiceAccount Tokens:** Native to cluster pods, short-lived, signed by the kube-apiserver OIDC issuer. Excellent for pod-level identity, but unaware of multi-agent session semantics (task ID, workspace ID, role).
2. **SPIFFE/SPIRE:** Standardized SPIFFE IDs (`spiffe://agent-lab/ns/default/sa/researcher-27`), but requires heavy daemonset infrastructure (SPIRE server + agent), adding significant operational overhead in lightweight KinD/gVisor sandboxes.
3. **Task-Scoped OIDC-Compatible JWT Workload Identity (Selected Architecture):**
   - Cryptographically signed token carrying essential application claims:
     ```json
     {
       "sub": "agent:researcher-27",
       "role": "research-agent",
       "tenant": "acme",
       "environment": "staging",
       "task_id": "T-482",
       "workspace_id": "WS-security",
       "iss": "agent-lab-trust-plane",
       "aud": "agent-gateway",
       "iat": 1791350000,
       "exp": 1791353600
     }
     ```
   - **Empirical Test:** Minted distinct tokens for `agent-001`, `agent-002`, `agent-003`. Verified cryptographic signatures, distinct subject claims, and tamper resistance (tampered tokens immediately rejected).

#### Definitive Conclusion
**Task-scoped OIDC-compatible JWT workload identity is the selected identity architecture.** OIDC/JWT workload identity remains the implementation direction for Milestone 3, with the concrete identity-provider integration to be finalized during implementation.

---

### Experiment 3: Identity Persistence Across Worker Migration

**Investigated Question:** *Does the agent's logical identity remain stable even though its physical execution environment changes?*

#### Empirical Migration Verification
We evaluated Agent-27 (`agent:researcher-27`) across the three physical lifecycle phases established in Milestone 1:
1. **Phase 1 (Active on Worker A):** Running on `worker-pool-6dbd6964f6-2s6cd` (`10.244.0.28`). Identity token signature valid; claims resolve to `T-482` and `WS-security`.
2. **Phase 2 (Suspended / Reclaimed):** gVisor worker compute reclaimed to `<none>`. State checkpointed in durable storage.
3. **Phase 3 (Restored on Worker B):** Resumed on `worker-pool-6dbd6964f6-8b9vz` (`10.244.0.26`).

#### Empirical Result
- The agent's logical identity token remained **100% valid and verified** without re-issuance.
- The cryptographic subject (`agent:researcher-27`), task binding (`T-482`), and workspace binding (`WS-security`) remained identical.

#### Definitive Conclusion
**Logical workload identity is bound to the durable session/task context, completely decoupled from ephemeral physical worker pods.** Worker migrations and memory restores do not invalidate agent identity.

---

### Experiment 4: Dynamic Authorization & Scope Evaluation

**Investigated Question:** *Can effective authorization be computed dynamically from context rather than maintaining static agent-to-agent permissions?*

#### The Intersection Model
Evaluated using the formalized intersection function:
$$\text{Effective Scope} = \text{Evaluate}(\text{Identity}, \text{Task Context}, \text{Workspace Context}, \text{Requested Capability}, \text{Delegated Authority}, \text{Policy Constraints})$$

#### Test Results Across Dimensions
| Test Scenario | Parameters Tested | Observed Output | Verdict |
|---|---|---|---|
| **4.1 Valid Context** | Role `research-agent`, capability `code_review`, matching task & workspace, staging | `ALLOWED` — Issued Effective Scope: `{capability: 'code_review', ttl: 900s, max_calls: 10}` | **PASSED** |
| **4.2 Unauthorized Capability** | Role `research-agent`, capability `production_deploy` | `DENIED` — Reason: *"No matching policy permits role 'research-agent' to request capability 'production_deploy'"* | **PASSED (Fail-Closed)** |
| **4.3 Cross-Task Violation** | Caller Task `T-482`, Target Task `T-999-DIFFERENT` | `DENIED` — Reason: *"Task boundary violation: caller task 'T-482' != target task 'T-999-DIFFERENT'"* | **PASSED (Fail-Closed)** |
| **4.4 Environment Mismatch** | Environment `production` (Policy requires `staging`) | `DENIED` — Reason: *"Environment mismatch: rule requires 'staging', got 'production'"* | **PASSED (Fail-Closed)** |
| **4.5 Excessive Delegation** | Delegation depth `3` (Policy limit: `2`) | `DENIED` — Reason: *"Delegation depth exceeded: depth 3 > max 2"* | **PASSED (Fail-Closed)** |

#### Definitive Conclusion
Dynamic authorization computes effective scopes at invocation time with full contextual precision. **Static peer-to-peer permissions are unnecessary.**

---

### Experiment 5: Dynamic Agent Discovery by Capability

**Investigated Question:** *Can agents discover eligible peers by capability instead of hardcoding static agent names?*

#### Test Results
1. **Targeted Capability Query:** Researcher requested `"code_review"` in `prod`. Resolved strictly to `reviewer-04`.
2. **Multiple Provider Selection:** In `staging`, both `reviewer-04` and `reviewer-05` matched. Policy engine successfully ranked and selected eligible providers.
3. **Resilience / Failover:** When `reviewer-04` transitioned to `SUSPENDED`, discovery immediately routed to `reviewer-05`.
4. **Missing Capability:** Request for unprovided capability gracefully returned empty candidate list without system exceptions.

#### Definitive Conclusion
Capability-based discovery enables dynamic multi-agent topologies, eliminating brittle hardcoded agent couplings like `researcher -> coder-17`.

---

### Experiment 6: Delegation & Gateway Enforcement

**Investigated Question:** *Where is the actual security boundary, and does it enforce Child Scope ⊆ Parent Scope?*

#### Delegation Rule Validation: Child Scope ⊆ Parent Scope
- **Parent Authority:** `{web_search, document_read}`.
- **Child Delegation 1:** Delegating `{document_read}` $\longrightarrow$ **ALLOWED (200)**.
- **Child Delegation 2 (Authority Escalation):** Child attempted to request `{deploy}` $\longrightarrow$ **DENIED (403)**. Escalation was strictly prevented.

#### Gateway Fail-Closed Interception Tests
All requests routed through the **Agent Gateway** proxy interceptor:
- **Expired Token:** Rejected immediately with **401 Unauthorized**.
- **Wrong Workspace ID:** Rejected with **403 Forbidden** (cross-tenant isolation enforced).
- **Unauthorized Target Agent:** Rejected with **403 Forbidden**.
- **Authority Escalation:** Rejected with **403 Forbidden**.

#### Definitive Conclusion
**The actual security boundary is at the Agent Gateway.** The Gateway intercepts inter-agent traffic and enforces authentication, task-scoped boundaries, and policy validation before traffic reaches target worker containers.

---

### Experiment 7: API/UI Control Plane Boundary & Complete Auditability

**Investigated Question:** *Can CLI, Web UI, and external clients operate against the exact same API, and can transactions be completely reconstructed?*

#### Verified API Contracts
The following unified REST contracts were verified for both CLI and Web UI clients:
- `POST /api/v1/research-sessions`
- `GET /api/v1/research-sessions/{id}`
- `POST /api/v1/research-sessions/{id}/suspend`
- `POST /api/v1/research-sessions/{id}/resume`
- `POST /api/v1/research-sessions/{id}/checkpoints`
- `POST /api/v1/agents/{id}/scope/evaluate`
- `POST /api/v1/agents/{id}/delegate`

#### Complete Audit Provenance
Every evaluation and gateway interception produces an immutable `AuditRecord`:
```json
{
  "timestamp": "2026-10-07T11:44:44Z",
  "caller": "agent:researcher-27",
  "caller_identity": "agent:researcher-27:research-agent",
  "requested_capability": "document_read",
  "target": "doc-agent-01",
  "task_id": "T-482",
  "workspace_id": "WS-security",
  "policy_version": "v1",
  "decision": "ALLOWED",
  "reason": "Authorized by policy evaluation intersection",
  "delegation_chain": ["agent:planner-01", "agent:researcher-27"],
  "token_id": "tok-9c3f71b2a8d4"
}
```
**Provenance Reconstruction:** Given any audit record, operators can deterministically reconstruct *who called whom, under which identity, for which task, with which authority, and why it was allowed*.

---

## 3. Core Architectural Conclusions

The empirical investigation has established the definitive architectural ground truth:

```text
Agent Lab
    │ application semantics
    │ agent orchestration
    │ trust / authorization
    ↓
AX
    │ infrastructure orchestration
    │ Task / Workspace / Gateway
    ↓
Agent Substrate
    │ isolated execution
    │ suspend / restore / migration
    ↓
Workers
```

1. **Identity:** Task-scoped OIDC-compatible JWT workload identity is the selected identity architecture for Milestone 3, with concrete identity provider integration to be finalized during implementation.
2. **Authorization:** Dynamic authorization evaluated via the **Contextual Intersection Model** completely eliminates static peer-to-peer permissions.
3. **Orchestration:** AX is the **infrastructure orchestration layer**; the **Agent Lab Control Plane** is strictly necessary above AX to handle capability discovery, peer selection, delegation, and research sessions.
4. **Execution & Boundary:** Agent Substrate is the **isolated execution substrate** handling compute suspension and migration; the **Agent Gateway** serves as the strict, fail-closed enforcement boundary for inter-agent communication.

With these boundaries experimentally validated, the architecture is definitively established. We proceed directly to implementing **Milestone 2 (Agent Lab Control Plane + API + Web UI)**.
