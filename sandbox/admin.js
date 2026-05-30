/**
 * PEMA Admin Dashboard — Client Logic
 *
 * Fetches and displays session data from the admin API endpoints.
 * Supports filtering by status and viewing detailed session information.
 */

(() => {
    'use strict';

    // ── Config ───────────────────────────────────────────────────────
    const API_BASE = '';

    // ── DOM References ───────────────────────────────────────────────
    const $tbody = document.getElementById('sessions-tbody');
    const $filterStatus = document.getElementById('filter-status');
    const $btnRefresh = document.getElementById('btn-refresh');
    const $refreshSpinner = document.getElementById('refresh-spinner');
    const $sessionCount = document.getElementById('session-count');
    const $detailPanel = document.getElementById('detail-panel');
    const $detailTitle = document.getElementById('detail-title');
    const $detailBody = document.getElementById('detail-body');
    const $btnCloseDetail = document.getElementById('btn-close-detail');

    // ── API ──────────────────────────────────────────────────────────

    async function apiRequest(method, path) {
        const resp = await fetch(`${API_BASE}${path}`, { method });
        if (!resp.ok) throw new Error(`API ${resp.status}`);
        return resp.json();
    }

    // ── Sessions List ────────────────────────────────────────────────

    async function loadSessions() {
        try {
            $refreshSpinner.classList.remove('hidden');
            $btnRefresh.disabled = true;

            const status = $filterStatus.value;
            let path = '/admin/sessions?limit=50';
            if (status) path += `&status=${status}`;

            const sessions = await apiRequest('GET', path);

            if (!sessions.length) {
                $tbody.innerHTML = `
                    <tr><td colspan="7" class="empty-state">
                        <div class="icon">📋</div>
                        <p>No sessions found</p>
                    </td></tr>
                `;
                $sessionCount.textContent = '0 sessions';
                return;
            }

            $sessionCount.textContent = `${sessions.length} session${sessions.length !== 1 ? 's' : ''}`;

            $tbody.innerHTML = sessions.map(s => `
                <tr data-id="${s.id}" class="session-row">
                    <td class="mono">${s.id.slice(0, 8)}…</td>
                    <td><span class="status-badge ${s.status}">${formatStatus(s.status)}</span></td>
                    <td>${(s.language || 'en').toUpperCase()}</td>
                    <td>${s.specialty ? formatSpecialty(s.specialty) : '—'}</td>
                    <td>${s.urgency ? formatUrgency(s.urgency) : '—'}</td>
                    <td>${s.turn_count ?? '—'}</td>
                    <td class="mono">${formatDate(s.created_at)}</td>
                </tr>
            `).join('');

        } catch (err) {
            $tbody.innerHTML = `
                <tr><td colspan="7" class="empty-state">
                    <div class="icon">⚠️</div>
                    <p>Failed to load sessions: ${escapeHtml(err.message)}</p>
                </td></tr>
            `;
        } finally {
            $refreshSpinner.classList.add('hidden');
            $btnRefresh.disabled = false;
        }
    }

    // ── Session Detail ───────────────────────────────────────────────

    async function loadSessionDetail(sessionId) {
        try {
            $detailTitle.textContent = `Session ${sessionId.slice(0, 8)}…`;
            $detailBody.innerHTML = '<div class="spinner" style="margin: 24px auto; display: block;"></div>';
            $detailPanel.classList.remove('hidden');

            const detail = await apiRequest('GET', `/admin/sessions/${sessionId}`);
            renderDetail(detail);

            // Scroll to detail panel
            $detailPanel.scrollIntoView({ behavior: 'smooth' });
        } catch (err) {
            $detailBody.innerHTML = `<p style="color: var(--color-emergency);">Failed to load: ${escapeHtml(err.message)}</p>`;
        }
    }

    function renderDetail(detail) {
        const facts = detail.extracted_facts || {};
        const messages = detail.messages || [];
        const rules = detail.rule_events || [];
        const audits = detail.model_audits || [];

        let html = '';

        // ── Overview section
        html += `
            <div class="detail-section">
                <h3>Overview</h3>
                <div class="facts-grid">
                    <div class="fact-card">
                        <div class="fact-label">Status</div>
                        <div class="fact-value"><span class="status-badge ${detail.status}">${formatStatus(detail.status)}</span></div>
                    </div>
                    <div class="fact-card">
                        <div class="fact-label">Specialty</div>
                        <div class="fact-value ${!detail.specialty ? 'empty' : ''}">${detail.specialty ? formatSpecialty(detail.specialty) : 'Not determined'}</div>
                    </div>
                    <div class="fact-card">
                        <div class="fact-label">Urgency</div>
                        <div class="fact-value ${!detail.urgency ? 'empty' : ''}">${detail.urgency ? formatUrgency(detail.urgency) : 'Not determined'}</div>
                    </div>
                    <div class="fact-card">
                        <div class="fact-label">Engine Version</div>
                        <div class="fact-value">${detail.engine_version || '—'}</div>
                    </div>
                    <div class="fact-card">
                        <div class="fact-label">Language</div>
                        <div class="fact-value">${(detail.language || 'en').toUpperCase()}</div>
                    </div>
                    <div class="fact-card">
                        <div class="fact-label">Session ID</div>
                        <div class="fact-value mono" style="font-size: 0.72rem;">${detail.id}</div>
                    </div>
                </div>
            </div>
        `;

        // ── Extracted Facts
        const formatList = arr => Array.isArray(arr) && arr.length ? arr.join(', ') : null;
        html += `
            <div class="detail-section">
                <h3>Extracted Facts</h3>
                <div class="facts-grid">
                    ${renderFact('Chief Complaint', facts.chief_complaint)}
                    ${renderFact('Body Region', facts.body_region)}
                    ${renderFact('Age', facts.age)}
                    ${renderFact('Sex', facts.sex)}
                    ${renderFact('Duration', facts.duration)}
                    ${renderFact('Severity', facts.severity)}
                    ${renderFact('Symptoms', formatList(facts.associated_symptoms))}
                    ${renderFact('Denied Symptoms', formatList(facts.denied_symptoms))}
                    ${renderFact('Pregnant', facts.is_pregnant != null ? (facts.is_pregnant ? 'Yes' : 'No') : null)}
                    ${renderFact('Medications', formatList(facts.medications))}
                    ${renderFact('Medical History', formatList(facts.medical_history))}
                    ${renderFact('Allergies', formatList(facts.allergies))}
                    ${renderFact('Lifestyle Factors', formatList(facts.lifestyle_factors))}
                    ${renderFact('Additional Context', facts.additional_context)}
                </div>
            </div>
        `;

        // ── Messages
        html += `
            <div class="detail-section">
                <h3>Conversation (${messages.length} messages)</h3>
                <div class="detail-messages">
                    ${messages.map(m => `
                        <div class="detail-msg ${m.role}">
                            <div class="detail-msg-role">${m.role} · Turn ${m.turn_number}</div>
                            ${escapeHtml(m.message_text)}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        // ── Rule Events
        if (rules.length) {
            html += `
                <div class="detail-section">
                    <h3>Safety Rule Events (${rules.length})</h3>
                    <table class="detail-table">
                        <thead>
                            <tr><th>Rule</th><th>Severity</th><th>Evidence</th></tr>
                        </thead>
                        <tbody>
                            ${rules.map(r => `
                                <tr>
                                    <td>${escapeHtml(r.rule_name)}</td>
                                    <td><span class="status-badge ${r.severity === 'emergency' ? 'escalated' : ''}">${r.severity}</span></td>
                                    <td style="font-size: 0.78rem; color: var(--text-secondary);">${escapeHtml(r.evidence_snippet || '—')}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        }

        // ── Model Audits — with clinical_reasoning prominently shown
        if (audits.length) {
            const conversationAudits = audits.filter(a => a.prompt_version && a.prompt_version.startsWith('conversation'));
            const otherAudits = audits.filter(a => !a.prompt_version || !a.prompt_version.startsWith('conversation'));

            // Show clinical reasoning for each conversation turn
            if (conversationAudits.length) {
                html += `
                    <div class="detail-section">
                        <h3>🧠 AI Clinical Reasoning (${conversationAudits.length} turns)</h3>
                        ${conversationAudits.map((a, i) => `
                            <div style="
                                background: rgba(99,102,241,0.08);
                                border: 1px solid rgba(99,102,241,0.25);
                                border-radius: 10px;
                                padding: 14px 16px;
                                margin-bottom: 10px;
                            ">
                                <div style="font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 6px;">
                                    Turn ${i + 1} · ${escapeHtml(a.model_name)} · ${a.latency_ms != null ? a.latency_ms + 'ms' : '—'}
                                </div>
                                <div style="font-size: 0.87rem; color: var(--text-primary); line-height: 1.55; white-space: pre-wrap;">${a.clinical_reasoning ? escapeHtml(a.clinical_reasoning) : '<em style="color:var(--text-secondary)">No reasoning captured</em>'}</div>
                            </div>
                        `).join('')}
                    </div>
                `;
            }

            // Show other audit records (normalization etc.)
            if (otherAudits.length) {
                html += `
                    <div class="detail-section">
                        <h3>LLM Audit Trail — Other (${otherAudits.length})</h3>
                        <table class="detail-table">
                            <thead>
                                <tr><th>Prompt Version</th><th>Model</th><th>Latency</th><th>Trace ID</th></tr>
                            </thead>
                            <tbody>
                                ${otherAudits.map(a => `
                                    <tr>
                                        <td>${escapeHtml(a.prompt_version)}</td>
                                        <td>${escapeHtml(a.model_name)}</td>
                                        <td>${a.latency_ms != null ? a.latency_ms + 'ms' : '—'}</td>
                                        <td class="mono" style="font-size: 0.7rem;">${a.trace_id ? a.trace_id.slice(0, 12) + '…' : '—'}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            }
        }

        $detailBody.innerHTML = html;
    }

    // ── Format Helpers ───────────────────────────────────────────────

    function renderFact(label, value) {
        const display = value != null && value !== '' ? String(value) : null;
        return `
            <div class="fact-card">
                <div class="fact-label">${label}</div>
                <div class="fact-value ${!display ? 'empty' : ''}">${display ? escapeHtml(display) : '—'}</div>
            </div>
        `;
    }

    function formatStatus(status) {
        const labels = {
            consent_framing: 'Framing',
            chief_complaint: 'Complaint',
            fact_gathering: 'Gathering',
            specialty_routing: 'Routing',
            completed: 'Completed',
            escalated: 'Escalated',
            abandoned: 'Abandoned',
        };
        return labels[status] || status;
    }

    function formatSpecialty(s) {
        return s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    function formatUrgency(u) {
        const icons = { emergency: '🚨', urgent: '⚠️', routine: '✅' };
        return `${icons[u] || ''} ${u.charAt(0).toUpperCase() + u.slice(1)}`;
    }

    function formatDate(iso) {
        if (!iso) return '—';
        try {
            const d = new Date(iso);
            return d.toLocaleDateString('en-PK', {
                month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });
        } catch {
            return iso;
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ── Event Listeners ──────────────────────────────────────────────

    $btnRefresh.addEventListener('click', loadSessions);
    $filterStatus.addEventListener('change', loadSessions);
    $btnCloseDetail.addEventListener('click', () => {
        $detailPanel.classList.add('hidden');
    });

    // Click on a session row → load detail
    $tbody.addEventListener('click', (e) => {
        const row = e.target.closest('.session-row');
        if (!row) return;
        loadSessionDetail(row.dataset.id);
    });

    // ── Init ─────────────────────────────────────────────────────────
    loadSessions();
})();
