# Experiment 008 Results: External OIDC Agent Identity & Dynamic Scope Investigation

- **Experiment ID:** `EXP-008-EXTERNAL-OIDC-DYNAMIC-SCOPE`
- **Milestone:** Architecture Investigation: External OIDC & Dynamic Scope
- **Status:** **PASSED (100% SUCCESS ACROSS ALL 10 TESTS)**
- **Executed:** October 7, 2026
- **Test Runner:** [`run_external_oidc_experiment.py`](file:///home/berrybytes/Office/agent/agent-lab/experiments/008-external-oidc-dynamic-scope/run_external_oidc_experiment.py)
- **Summary Ledger:** [`experiment_summary.json`](file:///home/berrybytes/Office/agent/agent-lab/experiments/008-external-oidc-dynamic-scope/experiment_summary.json)

---

## 1. Executive Summary

Experiment 008 empirically answered the central architectural question:
> **"Can a conventional OIDC provider provide the logical identity layer for autonomous agents while AX/Substrate continue providing workload identity underneath?"**

### The Core Architectural Insight
**AX and Agent Substrate already solve "Workload Identity"** via SPIFFE / mTLS / container actors (`spiffe://cluster.local/ns/default/sa/worker-actor-...`). What distributed autonomous agent systems lack is the **"Agentic Identity"** layer:

| Layer | Protocol | Question Answered | Lifecycle |
|---|---|---|---|
| **Agent Lab / OIDC** | **OIDC / JWT** | *"Who is this logical autonomous agent, acting in what task/workspace context?"* | **Durable & portable:** Follows the logical agent across suspension, checkpointing, branching, and worker migration. |
| **AX / Substrate** | **SPIFFE / mTLS** | *"What workload/Actor is currently executing and communicating?"* | **Execution-bound:** Associated with the current Actor/workload and managed by the substrate. |

> **Integration Scope Note:** Agent Lab implements the integration boundary required for an external OIDC provider and empirically validates the resulting identity and authorization model through `ExternalOIDCProviderAdapter`. In production, this adapter can be swapped with a live `Auth0ProviderAdapter` or `ZitadelProviderAdapter` without altering any M3–M7 invariants.


---

## 2. Quantitative Test Results

| Test # | Verified Invariant | Implementation Mechanism | Test Outcome | Status |
|---|---|---|---|---|
| **Test 1 & 2** | Dynamic Agent Creation & Unique OIDC Identity | `AgentRegistryService` + `ExternalOIDCProviderAdapter` (Auth0) | Agent A created (`agent:research-27`) with token `oidc-d8078e08b0b6` | **PASSED** |
| **Test 3** | RFC 9068 / OIDC Context Claims | Standard Claims: `sub`, `task_id`, `workspace_id`, `scope`, `spiffe_workload_id` | Signed JWT contains bound execution context and dynamic scope | **PASSED** |
| **Test 4** | Dynamic Scope Action Enforcement | Gateway Authorizer checks `document:read web:search` | `document:read` $\to$ ALLOWED<br>`web:search` $\to$ ALLOWED<br>`deployment:execute` $\to$ **DENIED** | **PASSED** |
| **Test 5 & 6** | Dynamic Agent B Creation with Distinct Scope | Dynamic minting of `deployment:execute deployment:read` | Agent B (`agent:deploy-08`) can execute `deployment:execute` | **PASSED** |
| **Test 7** | Cross-Agent Token / Scope Theft Isolation | Cryptographic task/workspace context binding | Agent A using Agent B's token rejected fail-closed (`Task binding mismatch`) | **PASSED** |
| **Test 8** | Dynamic Token Revocation & Expiry | IdP JTI Revocation Store + Gateway Check | Revoked token rejected fail-closed at Gateway boundary | **PASSED** |
| **Test 9** | Identity Durability across Compute Migrations | Logical OIDC Subject decoupled from worker IP/pod | Agent migrating from Worker 1 $\to$ Worker 2 retains identical logical identity | **PASSED** |
| **Test 10**| Coexistence with Underlying SPIFFE Workload Identity | Dual Identity Binding in Claims | OIDC carries logical agent identity while SPIFFE identifies physical worker actor | **PASSED** |

---

## 3. The 3 Identity Architecture Options Evaluated

### Option 1: In-House Agent Lab Identity
```text
Agent Lab Control Plane
  └── Agent Registry
       └── Internal JWT IdP
            ↓
         Agent Gateway
            ↓
      AX / SPIFFE Workload
```
- **Pros:** Zero external dependencies, ultra-low latency (<1ms), custom claims flexibility.
- **Cons:** Agent Lab owns the crypto key management; no out-of-the-box SSO federation with enterprise user directories.

### Option 2: Direct External OIDC (Auth0 / ZITADEL / Ory)
```text
External OIDC Provider (Auth0 / ZITADEL)
  └── Dynamic M2M Token
       └── Agent Gateway
            ↓
      AX / SPIFFE Workload
```
- **Pros:** Standard enterprise audit logs, automated key rotation (JWKS), compliance certifications (SOC2, ISO27001).
- **Cons:** High M2M token costs, API rate limits during mass multi-agent spin-up, token size limits.

### Option 3: The Hybrid Identity Architecture (Recommended)
```text
External Identity Provider (Auth0 / Okta)
  │ Human / Organizational Identity (SSO, OAuth2 user login)
  ▼
Agent Lab Control Plane
  │ Mints task-scoped, fine-grained Agentic Workload Tokens
  ▼
Agent Gateway
  │ Validates OIDC JWT + Evaluates Policy Engine Rules
  ▼
AX / Agent Substrate
  │ Physical SPIFFE Workload Identity (mTLS between workers)
```
- **Why Option 3 Wins:**
  1. **Federation without Rate Limits:** Humans authenticate via Auth0. Agent Lab orchestrates 1,000s of sub-agents without incurring Auth0 per-M2M-call rate limits.
  2. **Separation of Policy from Token Size:** Standard OIDC tokens carry high-level coarse scopes (`scope: "document:read web:search"`), while the Agent Lab Policy Engine evaluates fine-grained file patterns, quotas, and delegation depths.
  3. **Zero Conflict with SPIFFE:** AX continues handling worker-to-worker mTLS and actor isolation; Agent Lab handles high-level authorization.

---

## 4. Key Architectural Rule: Dynamic Authorization Context vs Immutable JWT

### The Dynamic Authorization Context Progression
Once an OIDC JWT is minted, its claims (including `scope = "document:read web:search"`) are cryptographically signed and immutable. What is dynamic is the **authorization context progression**:

$$\text{Agent Creation} \longrightarrow \text{Capabilities Determined} \longrightarrow \text{Scope Issued} \longrightarrow \text{Gateway Invocations} \longrightarrow \text{State / Quota / Delegation Changes} \longrightarrow \text{Effective Authorization Changes}$$

### Clear Separation of Concerns:
- **OIDC JWT:** *"This agent was issued these coarse capabilities."*
  - Provides signed identity (`sub`), task binding (`task_id`, `workspace_id`), and coarse scope (`scope: "document:read web:search"`).
  - Does **NOT** bloat the token with volatile ASTs (file lists, tool parameter whitelists, remaining call counters).
- **Agent Lab Policy Engine & Gateway:** *"Given the current context, state, and delegation depth, is this specific invocation actually allowed?"*
  - Enforces fine-grained path regexes, decrements quota counters, enforces delegation depth limits, and logs immutable audit trails.

---

## 5. Canonical Architectural Model

### The Definitive Architectural Statement
> **Agent Lab introduces a verifiable logical agent identity and dynamic authorization context above AX/Agent Substrate's existing workload identity layer. OIDC identifies the logical autonomous agent and establishes its coarse, task-scoped authorization context, while AX/Substrate and SPIFFE identify and secure the underlying execution workload. The Agent Gateway and Policy Engine combine these contexts to derive effective runtime authority.**

### The Complete Mental Model:
```text
                     WHO?
                      │
                OIDC / JWT
                      │
              Logical Agent
                      │
                     WHAT?
                      │
             Dynamic Scope
                      │
             Policy Evaluation
                      │
                  CAN DO?
                      │
                Delegation
                      │
                   BRANCH
                      │
                  COMPETE
                      │
                 PROMOTE
                      │
─────────────────────────────────
                 WHERE?
                      │
              AX / Substrate
                      │
                  SPIFFE
                      │
                  Actor
                      │
                  Worker
```

### The Unified Architecture Across Milestones:
- **M3 IDENTIFY:** External OIDC $\longrightarrow$ Logical agent identity
- **M4 AUTHORIZE:** Dynamic scope $\longrightarrow$ Effective authority (contextual evaluation)
- **M5 DELEGATE:** Child scope $\subseteq$ Parent scope (monotonic attenuation)
- **M6 BRANCH:** Branch authorization $\subseteq$ Source authorization (immutable state checkpoint)
- **M7 COMPETE:** Authorized branches execute independently (speculative evaluation & promotion)
- **AX / SUBSTRATE:** SPIFFE $\longrightarrow$ Workload identity underneath all of it

