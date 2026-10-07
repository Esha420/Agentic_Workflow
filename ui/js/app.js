/**
 * ui/js/app.js — Agent Lab Interactive Web UI Controller
 *
 * Implements client-side routing, live state polling, session lifecycle actions,
 * interactive timeline, workspace artifact browsing, and policy simulation.
 */

(function () {
  'use strict';

  // API Base URL (same origin)
  const API_BASE = window.location.origin;

  // State
  let currentSessions = [];
  let activeSessionId = null;
  let activeSessionData = null;
  let pollInterval = null;

  // DOM Elements
  const el = {
    viewDashboard: document.getElementById('view-dashboard'),
    viewSessionDetail: document.getElementById('view-session-detail'),
    navDashboardBtn: document.getElementById('nav-dashboard-btn'),
    navSessionsBtn: document.getElementById('nav-sessions-btn'),
    navSimulatorBtn: document.getElementById('nav-simulator-btn'),
    brandHomeBtn: document.getElementById('brand-home-btn'),
    apiStatusBadge: document.getElementById('api-status-badge'),
    apiStatusDot: document.getElementById('api-status-dot'),
    apiStatusText: document.getElementById('api-status-text'),

    // Metric Values
    valTotalSessions: document.getElementById('val-total-sessions'),
    valRunningAgents: document.getElementById('val-running-agents'),
    valSuspendedAgents: document.getElementById('val-suspended-agents'),
    valTotalCheckpoints: document.getElementById('val-total-checkpoints'),

    // Lists
    dashboardSessionList: document.getElementById('dashboard-session-list'),
    dashboardActivityFeed: document.getElementById('dashboard-activity-feed'),

    // Session Detail Header
    btnBackToDashboard: document.getElementById('btn-back-to-dashboard'),
    detailSessionTitle: document.getElementById('detail-session-title'),
    detailStatusBadge: document.getElementById('detail-status-badge'),
    btnDetailSuspend: document.getElementById('btn-detail-suspend'),
    btnDetailResume: document.getElementById('btn-detail-resume'),
    btnDetailCheckpoint: document.getElementById('btn-detail-checkpoint'),
    btnDetailBranch: document.getElementById('btn-detail-branch'),

    metaTaskId: document.getElementById('meta-task-id'),
    metaWorkspaceId: document.getElementById('meta-workspace-id'),
    metaAgentPersona: document.getElementById('meta-agent-persona'),
    metaWorkerNode: document.getElementById('meta-worker-node'),
    metaCheckpointId: document.getElementById('meta-checkpoint-id'),
    metaStartedAt: document.getElementById('meta-started-at'),

    // Tabs
    tabBtns: document.querySelectorAll('.tab-btn'),
    tabContents: document.querySelectorAll('.tab-content'),
    sessionTimelineList: document.getElementById('session-timeline-list'),
    workspaceFileTree: document.getElementById('workspace-file-tree'),
    workspaceFileContent: document.getElementById('workspace-file-content'),

    // Policy Simulator
    simCallerRole: document.getElementById('sim-caller-role'),
    simCapability: document.getElementById('sim-capability'),
    simTargetAgent: document.getElementById('sim-target-agent'),
    simEnvironment: document.getElementById('sim-environment'),
    btnRunSimulation: document.getElementById('btn-run-simulation'),
    simResultBox: document.getElementById('sim-result-box'),

    // Agent Registry Elements
    navAgentsBtn: document.getElementById('nav-agents-btn'),
    viewAgents: document.getElementById('view-agents'),
    agentRegistryList: document.getElementById('agent-registry-list'),
    registryCountLabel: document.getElementById('registry-count-label'),
    sessionAgentsContainer: document.getElementById('session-agents-container'),
    modalRegisterAgent: document.getElementById('modal-register-agent'),
    btnOpenRegisterAgentModal: document.getElementById('btn-open-register-agent-modal'),
    btnCloseAgentModal: document.getElementById('btn-close-agent-modal'),
    btnCancelAgentModal: document.getElementById('btn-cancel-agent-modal'),
    btnSubmitRegisterAgent: document.getElementById('btn-submit-register-agent'),
    inpAgentId: document.getElementById('inp-agent-id'),
    inpAgentRole: document.getElementById('inp-agent-role'),
    inpAgentTenant: document.getElementById('inp-agent-tenant'),
    inpAgentEnv: document.getElementById('inp-agent-env'),
    inpAgentCaps: document.getElementById('inp-agent-caps'),

    // Modal
    modalCreateSession: document.getElementById('modal-create-session'),
    btnOpenCreateModal: document.getElementById('btn-open-create-modal'),
    btnCloseModal: document.getElementById('btn-close-modal'),
    btnCancelModal: document.getElementById('btn-cancel-modal'),
    btnSubmitCreateSession: document.getElementById('btn-submit-create-session'),
    inpSessionObjective: document.getElementById('inp-session-objective'),
    inpSessionId: document.getElementById('inp-session-id'),
    inpSessionTarget: document.getElementById('inp-session-target'),
  };

  // ===========================================================================
  // API Calls
  // ===========================================================================

  async function apiFetch(path, options = {}) {
    const url = `${API_BASE}${path}`;
    try {
      const response = await fetch(url, {
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          ...options.headers,
        },
        ...options,
      });

      setApiStatus(true);

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${response.status}: ${response.statusText}`);
      }

      return await response.json();
    } catch (err) {
      setApiStatus(false, err.message);
      throw err;
    }
  }

  function setApiStatus(connected, msg = '') {
    if (connected) {
      el.apiStatusBadge.className = 'api-indicator connected';
      el.apiStatusDot.style.color = 'var(--status-running)';
      el.apiStatusText.textContent = 'API Connected';
    } else {
      el.apiStatusBadge.className = 'api-indicator';
      el.apiStatusDot.style.color = 'var(--status-failed)';
      el.apiStatusText.textContent = 'API Disconnected';
    }
  }

  // ===========================================================================
  // Navigation & Routing
  // ===========================================================================

  function showDashboard() {
    activeSessionId = null;
    activeSessionData = null;
    el.viewDashboard.style.display = 'block';
    el.viewSessionDetail.style.display = 'none';
    if (el.viewAgents) el.viewAgents.style.display = 'none';
    el.navDashboardBtn.classList.add('active');
    el.navSessionsBtn.classList.remove('active');
    if (el.navAgentsBtn) el.navAgentsBtn.classList.remove('active');
    el.navSimulatorBtn.classList.remove('active');
    loadDashboardData();
  }

  async function showSessionDetail(sessionId) {
    activeSessionId = sessionId;
    el.viewDashboard.style.display = 'none';
    el.viewSessionDetail.style.display = 'block';
    if (el.viewAgents) el.viewAgents.style.display = 'none';
    el.navDashboardBtn.classList.remove('active');
    el.navSessionsBtn.classList.add('active');
    if (el.navAgentsBtn) el.navAgentsBtn.classList.remove('active');
    el.navSimulatorBtn.classList.remove('active');

    // Default to timeline tab
    switchTab('tab-timeline');
    await loadSessionDetailData(sessionId);
  }

  function showAgentsView() {
    activeSessionId = null;
    activeSessionData = null;
    el.viewDashboard.style.display = 'none';
    el.viewSessionDetail.style.display = 'none';
    if (el.viewAgents) el.viewAgents.style.display = 'block';
    el.navDashboardBtn.classList.remove('active');
    el.navSessionsBtn.classList.remove('active');
    if (el.navAgentsBtn) el.navAgentsBtn.classList.add('active');
    el.navSimulatorBtn.classList.remove('active');
    loadAgentRegistry();
  }

  function switchTab(tabId) {
    el.tabBtns.forEach(btn => {
      if (btn.getAttribute('data-tab') === tabId) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    el.tabContents.forEach(content => {
      if (content.id === tabId) {
        content.style.display = 'block';
      } else {
        content.style.display = 'none';
      }
    });

    if (tabId === 'tab-workspace' && activeSessionId) {
      loadWorkspaceFiles(activeSessionId);
    } else if (tabId === 'tab-agents' && activeSessionId) {
      loadSessionAgentIdentity(activeSessionId);
    }
  }

  // ===========================================================================
  // Dashboard Logic
  // ===========================================================================

  async function loadDashboardData() {
    try {
      const sessions = await apiFetch('/api/v1/research-sessions');
      currentSessions = sessions || [];

      // Update metrics
      const total = currentSessions.length;
      const running = currentSessions.filter(s => s.status === 'RUNNING' || s.status === 'STARTING').length;
      const suspended = currentSessions.filter(s => s.status === 'SUSPENDED').length;

      el.valTotalSessions.textContent = total;
      el.valRunningAgents.textContent = running;
      el.valSuspendedAgents.textContent = suspended;

      // Render Active Sessions
      renderSessionList(currentSessions);

      // Render Recent Activity Feed
      renderActivityFeed(currentSessions);

      // Total Checkpoints count
      let cpCount = 0;
      currentSessions.forEach(s => {
        if (s.audit_trail) {
          cpCount += s.audit_trail.filter(a => a.to_status === 'SUSPENDED').length;
        }
      });
      el.valTotalCheckpoints.textContent = cpCount;

    } catch (err) {
      console.error('Error loading dashboard:', err);
      el.dashboardSessionList.innerHTML = `
        <div style="padding: 2rem; text-align: center; color: var(--accent-rose);">
          Error connecting to Agent Lab API: ${err.message}
        </div>
      `;
    }
  }

  function renderSessionList(sessions) {
    if (!sessions || sessions.length === 0) {
      el.dashboardSessionList.innerHTML = `
        <div style="padding: 2rem; text-align: center; color: var(--text-dim);">
          No active research sessions found. Click "+ New Session" to launch one.
        </div>
      `;
      return;
    }

    el.dashboardSessionList.innerHTML = sessions.map(s => {
      const statusBadge = getStatusBadge(s.status);
      const createdStr = (s.created_at || '').substring(0, 19).replace('T', ' ');

      return `
        <div class="session-item" data-id="${s.id}">
          <div class="session-top">
            <div>
              <div class="session-title-text">${escapeHtml(s.objective || s.id)}</div>
              <div style="font-size: 0.8rem; color: var(--text-dim); margin-top: 0.2rem; font-family: var(--font-mono);">${s.id}</div>
            </div>
            ${statusBadge}
          </div>

          <div class="session-meta-row">
            <div class="meta-item"><strong>Task:</strong> ${s.active_task_id || '-'}</div>
            <div class="meta-item"><strong>Worker:</strong> ${s.active_worker_ip || '<none>'}</div>
            <div class="meta-item"><strong>Target:</strong> ${escapeHtml(s.target || '-')}</div>
            <div class="meta-item"><strong>Created:</strong> ${createdStr}</div>
          </div>

          <div class="session-bottom">
            <span style="font-size: 0.78rem; color: var(--text-dim); font-family: var(--font-mono);">
              Workspace: ${s.workspace_id || '-'}
            </span>
            <button class="btn btn-secondary btn-sm btn-open-session" data-id="${s.id}">Open Session →</button>
          </div>
        </div>
      `;
    }).join('');

    // Attach click handlers
    document.querySelectorAll('.btn-open-session').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const id = e.currentTarget.getAttribute('data-id');
        showSessionDetail(id);
      });
    });
  }

  function renderActivityFeed(sessions) {
    const allEvents = [];
    sessions.forEach(s => {
      (s.audit_trail || []).forEach(evt => {
        allEvents.push({ ...evt, session_id: s.id });
      });
    });

    allEvents.sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));

    if (allEvents.length === 0) {
      el.dashboardActivityFeed.innerHTML = `
        <div style="padding: 1.5rem; text-align: center; color: var(--text-dim);">
          No recent activity recorded yet.
        </div>
      `;
      return;
    }

    el.dashboardActivityFeed.innerHTML = allEvents.slice(0, 8).map(evt => {
      const timeStr = (evt.timestamp || '').substring(11, 19);
      return `
        <div class="activity-entry">
          <div class="activity-dot"></div>
          <div class="activity-content">
            <div class="activity-msg">
              <strong>${evt.session_id}:</strong> ${escapeHtml(evt.reason || `${evt.from_status} → ${evt.to_status}`)}
            </div>
            <div class="activity-time">${timeStr} by ${evt.actor || 'system'}</div>
          </div>
        </div>
      `;
    }).join('');
  }

  // ===========================================================================
  // Session Detail Logic
  // ===========================================================================

  async function loadSessionDetailData(sessionId) {
    try {
      const session = await apiFetch(`/api/v1/research-sessions/${sessionId}`);
      activeSessionData = session;

      el.detailSessionTitle.textContent = session.objective || session.id;
      el.detailStatusBadge.outerHTML = getStatusBadge(session.status);
      el.detailStatusBadge = document.querySelector('#view-session-detail .badge');

      el.metaTaskId.textContent = session.active_task_id || '-';
      el.metaWorkspaceId.textContent = session.workspace_id || '-';
      el.metaWorkerNode.textContent = session.active_worker_ip || '<reclaimed / none>';
      el.metaCheckpointId.textContent = `cp-${session.version || 1}`;
      el.metaStartedAt.textContent = (session.created_at || '').substring(0, 19).replace('T', ' ');

      // Render timeline
      renderTimeline(session.audit_trail || []);

      // Toggle action buttons based on status
      const isRunning = session.status === 'RUNNING' || session.status === 'STARTING';
      const isSuspended = session.status === 'SUSPENDED';

      el.btnDetailSuspend.disabled = !isRunning;
      el.btnDetailResume.disabled = !isSuspended;

    } catch (err) {
      console.error('Error loading session detail:', err);
      alert(`Error loading session details: ${err.message}`);
    }
  }

  function renderTimeline(events) {
    if (!events || events.length === 0) {
      el.sessionTimelineList.innerHTML = `
        <div style="padding: 2rem; text-align: center; color: var(--text-dim);">
          No timeline events recorded.
        </div>
      `;
      return;
    }

    el.sessionTimelineList.innerHTML = events.map(evt => {
      const timeStr = (evt.timestamp || '').substring(11, 19);
      const dateStr = (evt.timestamp || '').substring(0, 10);

      return `
        <div class="timeline-event">
          <div class="timeline-node"></div>
          <div class="timeline-card">
            <div class="timeline-header">
              <span class="timeline-action">${evt.from_status || 'INIT'} ➔ ${evt.to_status}</span>
              <span class="timeline-time">${dateStr} ${timeStr}</span>
            </div>
            <div class="timeline-reason">${escapeHtml(evt.reason || 'State transition executed')}</div>
            <div style="font-size: 0.75rem; color: var(--text-dim); margin-top: 0.35rem; font-family: var(--font-mono);">
              Actor: ${evt.actor || 'system'}
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  async function loadWorkspaceFiles(sessionId) {
    try {
      const data = await apiFetch(`/api/v1/research-sessions/${sessionId}/workspace`);
      const artifacts = data.artifacts || [];

      if (artifacts.length === 0) {
        el.workspaceFileTree.innerHTML = `
          <div style="padding: 1rem; color: var(--text-dim); font-size: 0.85rem;">
            No artifacts written to workspace yet.
          </div>
        `;
        return;
      }

      el.workspaceFileTree.innerHTML = artifacts.map(art => `
        <div class="file-item" data-path="${escapeHtml(art)}">
          <span>📄</span>
          <span>${escapeHtml(art)}</span>
        </div>
      `).join('');

      document.querySelectorAll('.file-item').forEach(item => {
        item.addEventListener('click', async (e) => {
          document.querySelectorAll('.file-item').forEach(i => i.classList.remove('active'));
          e.currentTarget.classList.add('active');
          const path = e.currentTarget.getAttribute('data-path');
          loadArtifactContent(sessionId, path);
        });
      });

      // Automatically select first file
      if (artifacts.length > 0) {
        const first = document.querySelector('.file-item');
        if (first) {
          first.click();
        }
      }

    } catch (err) {
      el.workspaceFileTree.innerHTML = `
        <div style="padding: 1rem; color: var(--accent-rose); font-size: 0.85rem;">
          Error loading workspace: ${err.message}
        </div>
      `;
    }
  }

  async function loadArtifactContent(sessionId, path) {
    el.workspaceFileContent.textContent = 'Loading artifact content...';
    try {
      const data = await apiFetch(`/api/v1/research-sessions/${sessionId}/artifacts/${path}`);
      el.workspaceFileContent.textContent = data.content || '(Empty file)';
    } catch (err) {
      el.workspaceFileContent.textContent = `Error reading file '${path}': ${err.message}`;
    }
  }

  // ===========================================================================
  // Session Actions (Suspend, Resume, Checkpoint, Branch)
  // ===========================================================================

  async function handleSuspend() {
    if (!activeSessionId) return;
    try {
      el.btnDetailSuspend.disabled = true;
      el.btnDetailSuspend.textContent = 'Suspending...';
      await apiFetch(`/api/v1/research-sessions/${activeSessionId}/suspend`, {
        method: 'POST',
        body: JSON.stringify({ reason: 'Operator requested suspension via Web UI' }),
      });
      await loadSessionDetailData(activeSessionId);
    } catch (err) {
      alert(`Suspend failed: ${err.message}`);
    } finally {
      el.btnDetailSuspend.textContent = '⏸ Suspend';
    }
  }

  async function handleResume() {
    if (!activeSessionId) return;
    try {
      el.btnDetailResume.disabled = true;
      el.btnDetailResume.textContent = 'Resuming...';
      await apiFetch(`/api/v1/research-sessions/${activeSessionId}/resume`, {
        method: 'POST',
        body: JSON.stringify({ reason: 'Operator requested resumption via Web UI' }),
      });
      await loadSessionDetailData(activeSessionId);
    } catch (err) {
      alert(`Resume failed: ${err.message}`);
    } finally {
      el.btnDetailResume.textContent = '▶ Resume';
    }
  }

  async function handleCheckpoint() {
    if (!activeSessionId) return;
    try {
      el.btnDetailCheckpoint.textContent = 'Saving...';
      await apiFetch(`/api/v1/research-sessions/${activeSessionId}/checkpoints`, {
        method: 'POST',
        body: JSON.stringify({ reason: 'Operator manual checkpoint via Web UI' }),
      });
      await loadSessionDetailData(activeSessionId);
      alert('Checkpoint successfully created and recorded!');
    } catch (err) {
      alert(`Checkpoint failed: ${err.message}`);
    } finally {
      el.btnDetailCheckpoint.textContent = '💾 Checkpoint';
    }
  }

  function handleBranch() {
    if (!activeSessionId) return;
    alert(`Speculative Branching: Ready to fork session '${activeSessionId}' into competing hypothesis branches (Approach A vs Approach B). Scheduled for Milestone 6!`);
  }

  // ===========================================================================
  // Policy Simulator
  // ===========================================================================

  async function runPolicySimulation() {
    el.simResultBox.textContent = 'Evaluating policy rules...';
    try {
      const payload = {
        caller_role: el.simCallerRole.value.trim(),
        requested_capability: el.simCapability.value,
        target_agent: el.simTargetAgent.value.trim(),
        environment: el.simEnvironment.value,
        task_id: activeSessionId ? activeSessionData?.active_task_id || 'T-482' : 'T-482',
        workspace_id: activeSessionId ? activeSessionData?.workspace_id || 'WS-security' : 'WS-security',
      };

      const res = await apiFetch('/api/v1/scope/evaluate', {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      const isAllowed = res.verdict === 'ALLOWED';
      const color = isAllowed ? 'var(--status-running)' : 'var(--status-failed)';
      const icon = isAllowed ? '✓' : '✕';

      el.simResultBox.innerHTML = `
        <div style="color: ${color}; font-size: 1.1rem; font-weight: 700; margin-bottom: 0.75rem;">
          ${icon} ${res.verdict}
        </div>
        <div style="color: var(--text-main); margin-bottom: 0.5rem;">
          <strong>Reason:</strong> ${escapeHtml(res.reason)}
        </div>
        <div style="color: var(--text-dim); margin-bottom: 0.75rem;">
          <strong>Policy Rule:</strong> ${escapeHtml(res.policy_rule || 'default')}
        </div>
        ${res.effective_scope ? `
          <div style="background: rgba(0,0,0,0.4); padding: 0.75rem; border-radius: 6px; border: 1px solid var(--border-color);">
            <div style="color: var(--accent-cyan); font-weight: 600; margin-bottom: 0.25rem;">Effective Scope Issued:</div>
            <pre style="margin: 0; color: #cbd5e1; font-size: 0.8rem;">${JSON.stringify(res.effective_scope, null, 2)}</pre>
          </div>
        ` : ''}
      `;
    } catch (err) {
      el.simResultBox.innerHTML = `<span style="color: var(--accent-rose);">Simulation failed: ${err.message}</span>`;
    }
  }

  // ===========================================================================
  // Create Session Modal
  // ===========================================================================

  function openCreateModal() {
    el.inpSessionObjective.value = '';
    el.inpSessionId.value = '';
    el.modalCreateSession.classList.add('open');
  }

  function closeCreateModal() {
    el.modalCreateSession.classList.remove('open');
  }

  async function submitCreateSession() {
    const objective = el.inpSessionObjective.value.trim();
    if (!objective) {
      alert('Please enter a research objective.');
      return;
    }

    const sessionId = el.inpSessionId.value.trim() || undefined;
    const target = el.inpSessionTarget.value.trim();

    try {
      el.btnSubmitCreateSession.disabled = true;
      el.btnSubmitCreateSession.textContent = 'Creating...';

      const session = await apiFetch('/api/v1/research-sessions', {
        method: 'POST',
        body: JSON.stringify({ objective, id: sessionId, target }),
      });

      closeCreateModal();
      showSessionDetail(session.id);
    } catch (err) {
      alert(`Failed to create session: ${err.message}`);
    } finally {
      el.btnSubmitCreateSession.disabled = false;
      el.btnSubmitCreateSession.textContent = 'Create Session';
    }
  }

  // ===========================================================================
  // Helper Functions
  // ===========================================================================

  function getStatusBadge(status) {
    const s = (status || 'UNKNOWN').toUpperCase();
    if (s === 'RUNNING' || s === 'STARTING') {
      return `<span class="badge badge-running">● ${s}</span>`;
    } else if (s === 'WAITING') {
      return `<span class="badge badge-waiting">⏸ ${s}</span>`;
    } else if (s === 'SUSPENDED' || s === 'SUSPENDING') {
      return `<span class="badge badge-suspended">💤 ${s}</span>`;
    } else if (s === 'COMPLETED') {
      return `<span class="badge badge-completed">✓ ${s}</span>`;
    } else {
      return `<span class="badge badge-failed">✕ ${s}</span>`;
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // ===========================================================================
  // Agent Registry & Workload Identity Logic
  // ===========================================================================

  async function loadAgentRegistry() {
    if (!el.agentRegistryList) return;
    el.agentRegistryList.innerHTML = '<div style="text-align: center; color: var(--text-dim); padding: 2rem;">Loading agents from directory...</div>';

    try {
      const agents = await apiFetch('/api/v1/agents');
      if (el.registryCountLabel) {
        el.registryCountLabel.textContent = `${agents.length} logical agent(s) registered`;
      }

      if (!agents || agents.length === 0) {
        el.agentRegistryList.innerHTML = `
          <div style="padding: 2rem; text-align: center; color: var(--text-dim);">
            No agents registered in registry. Click "+ Register Agent" to register a logical agent.
          </div>
        `;
        return;
      }

      el.agentRegistryList.innerHTML = `
        <div style="display: grid; gap: 1.25rem;">
          ${agents.map(ag => `
            <div class="session-item" style="cursor: default;">
              <div class="session-top">
                <div>
                  <div style="font-weight: 700; font-size: 1.05rem; color: #fff;">${escapeHtml(ag.agent_id)}</div>
                  <div style="font-size: 0.8rem; color: var(--accent-cyan); font-family: var(--font-mono); margin-top: 0.2rem;">${escapeHtml(ag.identity_subject)}</div>
                </div>
                <div>
                  <span class="badge ${ag.lifecycle_state === 'ACTIVE' ? 'badge-running' : ag.lifecycle_state === 'TERMINATED' ? 'badge-failed' : 'badge-waiting'}">
                    ${ag.lifecycle_state}
                  </span>
                </div>
              </div>
              <div class="session-meta-row" style="margin-top: 0.75rem;">
                <div class="meta-item"><strong>Role:</strong> ${escapeHtml(ag.role)}</div>
                <div class="meta-item"><strong>Tenant / Env:</strong> ${escapeHtml(ag.tenant)} / ${escapeHtml(ag.environment)}</div>
                <div class="meta-item"><strong>Bound Task:</strong> ${escapeHtml(ag.task_id || '<none>')}</div>
                <div class="meta-item"><strong>Workspace:</strong> ${escapeHtml(ag.workspace_id || '<none>')}</div>
              </div>
              <div style="margin-top: 0.75rem; font-size: 0.8rem; color: var(--text-dim);">
                <strong>Capabilities:</strong> ${(ag.capabilities || []).map(c => `<span style="background: rgba(255,255,255,0.08); padding: 2px 8px; border-radius: 4px; margin-right: 4px; font-family: var(--font-mono);">${escapeHtml(c)}</span>`).join('')}
              </div>
            </div>
          `).join('')}
        </div>
      `;
    } catch (err) {
      el.agentRegistryList.innerHTML = `<div style="color: var(--accent-rose); padding: 1.5rem;">Error loading agent registry: ${err.message}</div>`;
    }
  }

  async function loadSessionAgentIdentity(sessionId) {
    if (!el.sessionAgentsContainer) return;
    el.sessionAgentsContainer.innerHTML = '<div style="text-align: center; color: var(--text-dim); padding: 2rem;">Loading active workload identity token...</div>';

    try {
      const agentId = activeSessionData?.metadata?.agent_id || `agent-${sessionId}`;
      let idInfo = null;
      let agentData = null;

      try {
        agentData = await apiFetch(`/api/v1/agents/${agentId}`);
        idInfo = await apiFetch(`/api/v1/agents/${agentId}/identity`);
      } catch (e) {
        // Fallback
      }

      if (!agentData) {
        el.sessionAgentsContainer.innerHTML = `
          <div style="padding: 2rem; text-align: center; color: var(--text-dim);">
            No logical agent mapped to session '${sessionId}'.
          </div>
        `;
        return;
      }

      const idStatus = idInfo?.identity || {};
      const isValid = idStatus.is_valid;
      const isRevoked = idStatus.is_revoked;

      el.sessionAgentsContainer.innerHTML = `
        <div class="identity-grid">
          <!-- Primary Agent Card -->
          <div class="identity-card">
            <div class="identity-card-title">${escapeHtml(agentData.agent_id)} (Logical Agent)</div>
            <div class="claim-list">
              <div class="claim-row">
                <span class="claim-key">Subject:</span>
                <span class="claim-val">${escapeHtml(agentData.identity_subject)}</span>
              </div>
              <div class="claim-row">
                <span class="claim-key">Role:</span>
                <span class="claim-val">${escapeHtml(agentData.role)}</span>
              </div>
              <div class="claim-row">
                <span class="claim-key">Tenant / Env:</span>
                <span class="claim-val">${escapeHtml(agentData.tenant)} / ${escapeHtml(agentData.environment)}</span>
              </div>
              <div class="claim-row">
                <span class="claim-key">Lifecycle State:</span>
                <span class="badge ${agentData.lifecycle_state === 'ACTIVE' ? 'badge-running' : 'badge-waiting'}">${agentData.lifecycle_state}</span>
              </div>
              <div class="claim-row">
                <span class="claim-key">Bound Task:</span>
                <span class="claim-val" style="font-family: var(--font-mono);">${escapeHtml(agentData.task_id || '-')}</span>
              </div>
              <div class="claim-row">
                <span class="claim-key">Capabilities:</span>
                <span class="claim-val">${(agentData.capabilities || []).join(', ')}</span>
              </div>
            </div>
          </div>

          <!-- Cryptographic Token Card -->
          <div class="identity-card">
            <div class="identity-card-title">OIDC Workload Identity Token</div>
            <div class="claim-list">
              <div class="claim-row">
                <span class="claim-key">Cryptographic Status:</span>
                <span class="badge ${isValid ? 'badge-running' : 'badge-failed'}">
                  ${isValid ? '✓ CRYPTOGRAPHICALLY VALID' : isRevoked ? '✕ REVOKED' : '✕ EXPIRED / INVALID'}
                </span>
              </div>
              <div class="claim-row">
                <span class="claim-key">Token JTI:</span>
                <span class="claim-val" style="font-family: var(--font-mono);">${escapeHtml(idStatus.jti || '-')}</span>
              </div>
              <div class="claim-row">
                <span class="claim-key">Issuer:</span>
                <span class="claim-val">${escapeHtml(idStatus.issuer || '-')}</span>
              </div>
              <div class="claim-row">
                <span class="claim-key">Audience:</span>
                <span class="claim-val">${escapeHtml(idStatus.audience || '-')}</span>
              </div>
              <div class="claim-row">
                <span class="claim-key">Token Preview:</span>
                <span class="claim-val" style="font-family: var(--font-mono); font-size: 0.75rem;">${escapeHtml(idStatus.token_preview || '-')}</span>
              </div>
            </div>

            <div style="margin-top: 1.25rem; display: flex; gap: 0.75rem;">
              ${isValid ? `
                <button class="btn btn-secondary btn-sm" id="btn-ui-revoke-token" style="color: var(--accent-rose); border-color: rgba(244,63,94,0.3);">
                  ✕ Revoke Token
                </button>
              ` : `
                <div style="font-size: 0.8rem; color: var(--text-dim);">Identity token revoked or expired.</div>
              `}
            </div>
          </div>
        </div>
      `;

      const btnRevoke = document.getElementById('btn-ui-revoke-token');
      if (btnRevoke) {
        btnRevoke.addEventListener('click', async () => {
          if (!confirm(`Revoke workload identity token for agent '${agentData.agent_id}'?`)) return;
          try {
            await apiFetch(`/api/v1/agents/${agentData.agent_id}/revoke-identity`, {
              method: 'POST',
              body: JSON.stringify({ reason: 'Operator manual revocation via Web UI' }),
            });
            alert('Workload identity revoked fail-closed.');
            loadSessionAgentIdentity(sessionId);
          } catch (e) {
            alert(`Revocation failed: ${e.message}`);
          }
        });
      }

    } catch (err) {
      el.sessionAgentsContainer.innerHTML = `<div style="color: var(--accent-rose); padding: 1.5rem;">Error loading agent identity: ${err.message}</div>`;
    }
  }

  function openRegisterAgentModal() {
    el.inpAgentId.value = '';
    el.modalRegisterAgent.classList.add('open');
  }

  function closeRegisterAgentModal() {
    el.modalRegisterAgent.classList.remove('open');
  }

  async function submitRegisterAgent() {
    const agentId = el.inpAgentId.value.trim();
    const role = el.inpAgentRole.value.trim();
    if (!agentId || !role) {
      alert('Please enter Agent ID and Role.');
      return;
    }

    const tenant = el.inpAgentTenant.value.trim() || 'default';
    const environment = el.inpAgentEnv.value.trim() || 'staging';
    const caps = el.inpAgentCaps.value.split(',').map(c => c.trim()).filter(Boolean);

    try {
      el.btnSubmitRegisterAgent.disabled = true;
      el.btnSubmitRegisterAgent.textContent = 'Registering...';

      await apiFetch('/api/v1/agents', {
        method: 'POST',
        body: JSON.stringify({
          agent_id: agentId,
          role,
          tenant,
          environment,
          capabilities: caps,
        }),
      });

      closeRegisterAgentModal();
      loadAgentRegistry();
    } catch (err) {
      alert(`Registration failed: ${err.message}`);
    } finally {
      el.btnSubmitRegisterAgent.disabled = false;
      el.btnSubmitRegisterAgent.textContent = 'Register Agent';
    }
  }

  // ===========================================================================
  // Initialization & Event Listeners
  // ===========================================================================

  function init() {
    // Nav buttons
    el.brandHomeBtn.addEventListener('click', showDashboard);
    el.navDashboardBtn.addEventListener('click', showDashboard);
    el.navSessionsBtn.addEventListener('click', showDashboard);
    if (el.navAgentsBtn) el.navAgentsBtn.addEventListener('click', showAgentsView);
    el.btnBackToDashboard.addEventListener('click', showDashboard);

    el.navSimulatorBtn.addEventListener('click', () => {
      if (!activeSessionId && currentSessions.length > 0) {
        showSessionDetail(currentSessions[0].id);
      }
      switchTab('tab-simulator');
    });

    // Tab buttons
    el.tabBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.currentTarget.getAttribute('data-tab');
        switchTab(tab);
      });
    });

    // Action buttons
    el.btnDetailSuspend.addEventListener('click', handleSuspend);
    el.btnDetailResume.addEventListener('click', handleResume);
    el.btnDetailCheckpoint.addEventListener('click', handleCheckpoint);
    el.btnDetailBranch.addEventListener('click', handleBranch);
    el.btnRunSimulation.addEventListener('click', runPolicySimulation);

    // Modal buttons (Create Session)
    el.btnOpenCreateModal.addEventListener('click', openCreateModal);
    el.btnCloseModal.addEventListener('click', closeCreateModal);
    el.btnCancelModal.addEventListener('click', closeCreateModal);
    el.btnSubmitCreateSession.addEventListener('click', submitCreateSession);

    // Modal buttons (Register Agent)
    if (el.btnOpenRegisterAgentModal) el.btnOpenRegisterAgentModal.addEventListener('click', openRegisterAgentModal);
    if (el.btnCloseAgentModal) el.btnCloseAgentModal.addEventListener('click', closeRegisterAgentModal);
    if (el.btnCancelAgentModal) el.btnCancelAgentModal.addEventListener('click', closeRegisterAgentModal);
    if (el.btnSubmitRegisterAgent) el.btnSubmitRegisterAgent.addEventListener('click', submitRegisterAgent);

    // Initial load
    showDashboard();

    // Auto-refresh interval (every 3 seconds)
    pollInterval = setInterval(() => {
      if (activeSessionId) {
        loadSessionDetailData(activeSessionId);
      } else if (el.viewAgents && el.viewAgents.style.display !== 'none') {
        // do not disturb agents view
      } else {
        loadDashboardData();
      }
    }, 3000);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
