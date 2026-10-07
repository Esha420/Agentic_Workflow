# Experiment 003: Empirical Results & Verification

## Executive Verdict: **SUCCESS**

**Milestone 3 (Real Agent Identity & Migration Invariance)** was empirically verified across all 5 verification phases.

```text
==============================================================================
  AGENT LAB — EXPERIMENT 003: REAL AGENT IDENTITY & MIGRATION INVARIANCE
==============================================================================

[Phase 1] Testing Agent Registry Separation of Concerns...
  ✓ Registered logical agent: researcher-27
  ✓ Subject:                  agent:researcher-27
  ✓ Tenant / Env:             acme / staging
  ✓ Capabilities:             ['web_research', 'document_analysis', 'repo_read']
  ✓ Lifecycle State:          REGISTERED

[Phase 2] Issuing Task-Scoped OIDC Workload Identity Token...
  ✓ Token JTI:       tok-260cfe87d870
  ✓ Issuer:          https://identity.agent-lab.internal
  ✓ Audience:        agent-gateway
  ✓ Subject:         agent:researcher-27
  ✓ Bound Task ID:   T-482-autonomous-research
  ✓ Bound Workspace: WS-security-mesh
  ✓ Token Preview:   eyJhbGciOiJIUzI1NiIs...zsXe79grq6xNnLAc
  ✓ Cryptographic signature & claims verified: VALID

[Phase 3] Executing Cross-Worker Migration Invariance Test...
  [Step 3.1] Task 'T-482-autonomous-research' active on Worker A (10.244.0.26)...
             Worker A mounts identity token into sandbox /workspace/.identity/token.jwt
  [Step 3.2] Triggering SUSPEND on Worker A (Idle Compute Reclamation)...
             Worker A allocation released -> worker count: 0
             Agent lifecycle state: SUSPENDED
  [Step 3.3] Triggering RESUME on Worker B (10.244.0.38)...
             Worker B allocated (10.244.0.38) -> worker count: 1
             Agent lifecycle state: ACTIVE
  [Step 3.4] Reading identity token from Worker B restored filesystem...
  [Step 3.5] Cryptographic Invariance Verification on Worker B:
             - Same Subject:          agent:researcher-27 (MATCH)
             - Same Task Binding:     T-482-autonomous-research (MATCH)
             - Same WS Binding:       WS-security-mesh (MATCH)
             - Cryptographic Sig:     VALID (Verified by IdP)
             - Identity Re-mapping:   ZERO (Completely invariant)

[Phase 4] Testing Complete Identity Lifecycle & Revocation...
  Sequence: CREATE -> ISSUE -> ACTIVE -> SUSPENDED -> ACTIVE -> COMPLETED -> REVOKED
  ✓ Agent transitioned to: TERMINATED
  ✓ Post-termination validation: valid=False, error='Token tok-260cfe87d870 is recorded as revoked in persistent store'
  ✓ Identity Status: valid=False, revoked=True

[Phase 5] Testing Tamper Resistance & Contextual Bounds...
  ✓ Tampered signature rejection: valid=False
  ✓ Task mismatch rejection: valid=False
  ✓ Workspace mismatch rejection: valid=False

==============================================================================
  EXPERIMENT 003: ALL PHASES COMPLETED SUCCESSFULLY (VERDICT: SUCCESS)
==============================================================================
```

---

## Detailed Findings by Architectural Boundary

### 1. Agent Registry Directory vs Identity Provider
- The **Agent Registry** operates strictly as an application-level directory. It records metadata (`agent_id`, `role`, `tenant`, `environment`, `capabilities`) and logical lifecycle states (`REGISTERED`, `ACTIVE`, `SUSPENDED`, `DRAINING`, `TERMINATED`).
- The **Identity Provider** (`OIDCWorkloadIdentityProvider`) is the sole cryptographic authority issuing signed JWTs.
- This separation prevents the registry from attempting to emulate an identity provider and enables pluggable IdP mechanisms (SPIRE, Kubernetes Projected Tokens, external OIDC) without altering the Agent Lab control plane.

### 2. Task-Scoped Workload Identity Token Schema
The issued token adheres to standard OIDC claims with task-scoped contextual bindings:
```json
{
  "iss": "https://identity.agent-lab.internal",
  "sub": "agent:researcher-27",
  "aud": "agent-gateway",
  "iat": 1791355904,
  "nbf": 1791355904,
  "exp": 1791359504,
  "jti": "tok-260cfe87d870",
  "task_id": "T-482-autonomous-research",
  "workspace_id": "WS-security-mesh",
  "role": "research-agent",
  "tenant": "acme",
  "environment": "staging",
  "capabilities": [
    "web_research",
    "document_analysis",
    "repo_read"
  ]
}
```

### 3. Migration Invariance Proven Cryptographically
- When an agent is suspended, compute workers are reclaimed and the task is dropped from active physical memory.
- Upon resumption onto an entirely different physical pod (Worker B at `10.244.0.38`), the token restored from durable storage is validated against the IdP.
- **Verification Outcomes:**
  1. Signature verification: **PASSED** (signature matches IdP key).
  2. Subject continuity: **PASSED** (`agent:researcher-27` identical before and after migration).
  3. Contextual binding continuity: **PASSED** (`task_id` and `workspace_id` unchanged).
  4. Worker pod decoupling: The agent's identity is completely independent of the physical worker node IP. No identity re-mapping occurred.

### 4. Lifecycle Completeness & Revocation
- We demonstrated that logical identity has a well-defined lifecycle, resolving the open architectural question:
  $$\text{REGISTERED} \longrightarrow \text{ACTIVE} \longleftrightarrow \text{SUSPENDED} \longrightarrow \text{TERMINATED}$$
- Upon task completion, terminating the agent immediately invalidates active tokens.
- Calls to the Agent Gateway validation endpoint with the revoked token return:
  ```json
  {
    "valid": false,
    "error": "Token tok-260cfe87d870 is recorded as revoked in persistent store"
  }
  ```
- Any attempts to tamper with signatures or spoof bound task IDs fail closed immediately.

---

## Conclusion & Readiness for Milestone 4

Milestone 3 has established the answer to:
> **Who is this agent?**
> Logical agent `researcher-27`, belonging to tenant `acme`, with verified subject `agent:researcher-27`, bound to task `T-482-autonomous-research` and workspace `WS-security-mesh`, maintaining cryptographic integrity across physical worker migrations.

Now, **Milestone 4 (Trust & Scope Plane)** can build directly upon this foundation to answer:
> **What is this agent allowed to do right now?**
$$\text{Effective Scope} = \text{Evaluate}(\text{Identity}, \text{Task}, \text{Workspace}, \text{Capability}, \text{Delegated Authority}, \text{Policy Constraints})$$
