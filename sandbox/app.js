/**
 * PEMA Sandbox — Chat Client Logic
 *
 * Manages session lifecycle, message flow, emergency handling,
 * and dynamic UI updates for the triage chat interface.
 */

(() => {
    'use strict';

    // ── Config ───────────────────────────────────────────────────────
    const API_BASE = '';  // Same origin
    const MAX_TEXTAREA_HEIGHT = 120;

    // ── DOM References ───────────────────────────────────────────────
    const $messages = document.getElementById('messages-container');
    const $input = document.getElementById('message-input');
    const $btnSend = document.getElementById('btn-send');
    const $btnNew = document.getElementById('btn-new-session');
    const $btnSidebarNew = document.getElementById('btn-sidebar-new-session');
    const $btnSidebarToggle = document.getElementById('btn-sidebar-toggle');
    const $sidebarBackdrop = document.getElementById('sidebar-backdrop');
    const $sidebar = document.getElementById('sidebar');
    const $sessionId = document.getElementById('session-id');
    const $sessionStatus = document.getElementById('session-status');
    const $turnCount = document.getElementById('turn-count');
    const $emergencyAlert = document.getElementById('emergency-alert');
    const $completionBanner = document.getElementById('completion-banner');
    const $completionSummary = document.getElementById('completion-summary');
    const $inputArea = document.getElementById('input-area');
    const $versionBadge = document.getElementById('version-badge');
    const $chatArea = document.getElementById('chat-area');
    const $sidebarList = document.getElementById('sidebar-list');

    // ── State ────────────────────────────────────────────────────────
    let currentSessionId = null;
    let currentLanguage = 'en';
    let currentMode = 'patient';
    let isProcessing = false;
    let turnNumber = 0;

    // ── API Helpers ──────────────────────────────────────────────────

    async function apiRequest(method, path, body = null) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);

        const resp = await fetch(`${API_BASE}${path}`, opts);
        if (!resp.ok) {
            const errText = await resp.text();
            throw new Error(`API ${resp.status}: ${errText}`);
        }
        
        // 204 No Content shouldn't be parsed as JSON
        if (resp.status === 204) return null;
        
        return resp.json();
    }

    // ── Session Management ───────────────────────────────────────────

    async function createSession() {
        try {
            clearChat();
            setStatus('Creating session…');
            disableInput();

            const data = await apiRequest('POST', '/sessions', {
                language: currentLanguage,
                mode: currentMode,
            });

            currentSessionId = data.id;
            turnNumber = 0;
            $sessionId.textContent = data.id.slice(0, 8) + '…';
            $sessionId.title = data.id;
            setStatus(formatStatus(data.status));
            updateTurnCount();

            // Show framing message
            if (data.framing_message) {
                appendMessage('system', data.framing_message, 'framing');
            }

            enableInput();
            $input.focus();

            // Fetch engine version for badge
            fetchVersion();
            loadSidebarHistory();
        } catch (err) {
            appendError(`Failed to create session: ${err.message}`);
            setStatus('Error');
        }
    }

    async function updateSession() {
        if (!currentSessionId) {
            return createSession();
        }
        try {
            setStatus('Updating session…');
            disableInput();

            const data = await apiRequest('PATCH', `/sessions/${currentSessionId}`, {
                language: currentLanguage,
                mode: currentMode,
            });

            // Show new framing message if it changed
            if (data.framing_message) {
                appendMessage('system', data.framing_message, 'framing');
            }

            enableInput();
            $input.focus();
            setStatus(formatStatus(data.status));
        } catch (err) {
            appendError(`Failed to update session: ${err.message}`);
            setStatus('Error');
            enableInput();
        }
    }

    async function loadSession(sessionId) {
        try {
            clearChat();
            setStatus('Loading session…');
            disableInput();

            const data = await apiRequest('GET', `/admin/sessions/${sessionId}`);

            currentSessionId = data.id;
            $sessionId.textContent = data.id.slice(0, 8) + '…';
            $sessionId.title = data.id;
            setStatus(formatStatus(data.status));
            
            // Set language from session
            if (data.language) {
                currentLanguage = data.language;
                document.querySelectorAll('.lang-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.lang === currentLanguage);
                });
                $input.placeholder = currentLanguage === 'ur'
                    ? 'Apni alamaat batayen…'
                    : 'Describe your symptoms…';
            }

            // Set mode from session
            if (data.mode) {
                currentMode = data.mode;
                document.querySelectorAll('.mode-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.mode === currentMode);
                });
            }

            // Restore messages
            const messages = data.messages || [];
            for (const m of messages) {
                let msgType = '';
                if (m.role === 'system') {
                    if (m.turn_number === 0) msgType = 'framing';
                    else if (data.status === 'escalated' && m === messages[messages.length - 1]) msgType = 'emergency';
                    else if (data.status === 'completed' && m === messages[messages.length - 1]) msgType = 'completion';
                }
                appendMessage(m.role, m.message_text, msgType);
                if (m.role === 'user') turnNumber = m.turn_number;
            }
            
            updateTurnCount();

            // Handle terminal states
            if (data.status === 'escalated') {
                showEmergencyAlert();
                disableInput();
            } else if (data.status === 'completed') {
                showCompletionBanner(data.specialty || 'general_practitioner', data.urgency || 'routine');
                disableInput();
            } else {
                enableInput();
                $input.focus();
            }

            fetchVersion();
            loadSidebarHistory();
        } catch (err) {
            appendError(`Failed to load session: ${err.message}`);
            setStatus('Error');
        }
    }

    async function sendMessage() {
        const text = $input.value.trim();
        if (!text || !currentSessionId || isProcessing) return;

        try {
            isProcessing = true;
            disableInput();
            $input.value = '';
            autoResizeTextarea();

            // Show user message
            appendMessage('user', text);
            turnNumber++;
            updateTurnCount();

            // Show typing indicator
            const typingEl = showTypingIndicator();

            // Send to API
            const data = await apiRequest('POST', `/sessions/${currentSessionId}/messages`, {
                text,
            });

            // Remove typing indicator
            typingEl.remove();

            // Determine message type
            let msgType = '';
            const status = data.session_status;
            if (status === 'escalated') {
                msgType = 'emergency';
            } else if (status === 'completed') {
                msgType = 'completion';
            }

            // Show system response
            appendMessage('system', data.system_message, msgType);
            setStatus(formatStatus(status));

            // Handle terminal states
            if (status === 'escalated') {
                showEmergencyAlert();
                disableInput();
            } else if (status === 'completed') {
                const specialty = data.specialty || 'general_practitioner';
                const urgency = data.urgency || 'routine';
                showCompletionBanner(specialty, urgency);
                disableInput();
            } else {
                enableInput();
                $input.focus();
            }
            loadSidebarHistory();
        } catch (err) {
            appendError(`Failed to send message: ${err.message}`);
            enableInput();
        } finally {
            isProcessing = false;
        }
    }

    async function fetchVersion() {
        try {
            const data = await apiRequest('GET', '/health');
            if (data.version) {
                $versionBadge.textContent = `v${data.version}`;
            }
        } catch { /* ignore */ }
    }

    async function loadSidebarHistory() {
        try {
            const sessions = await apiRequest('GET', '/admin/sessions?limit=25');
            
            $sidebarList.innerHTML = '';
            if (!sessions || sessions.length === 0) {
                $sidebarList.innerHTML = '<div style="padding: 12px; font-size: 0.8rem; color: var(--text-muted); text-align: center;">No history found</div>';
                return;
            }

            for (const s of sessions) {
                const el = document.createElement('div');
                el.className = 'sidebar-item' + (s.id === currentSessionId ? ' active' : '');
                el.dataset.id = s.id;
                
                let title = s.specialty ? formatSpecialty(s.specialty) : formatStatus(s.status).replace(/[^\w\s].*/, '').trim();
                if (!title || title.includes('Framing') || title.includes('Complaint')) {
                    title = 'New Session';
                }

                el.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; width: 100%;">
                        <div style="flex-grow: 1; overflow: hidden; margin-right: 8px;">
                            <div class="sidebar-item-title">${escapeHtml(title)}</div>
                            <div class="sidebar-item-meta">
                                <span>${s.turn_count || 0} msgs</span>
                                <span>${formatDate(s.created_at)}</span>
                            </div>
                        </div>
                        <button class="btn-delete-session" data-id="${s.id}" title="Delete Session" style="background: none; border: none; cursor: pointer; padding: 4px; color: var(--text-muted); display: flex; align-items: center; justify-content: center; border-radius: 4px;" onmouseover="this.style.color='var(--color-emergency)'" onmouseout="this.style.color='var(--text-muted)'">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                        </button>
                    </div>
                `;
                
                el.addEventListener('click', (e) => {
                    if (e.target.closest('.btn-delete-session')) {
                        return;
                    }
                    if (currentSessionId !== s.id) {
                        loadSession(s.id);
                    }
                    closeSidebar();
                });

                const deleteBtn = el.querySelector('.btn-delete-session');
                if (deleteBtn) {
                    deleteBtn.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        if (confirm('Are you sure you want to delete this session?')) {
                            try {
                                await apiRequest('DELETE', `/sessions/${s.id}`);
                                if (currentSessionId === s.id) {
                                    createSession();
                                } else {
                                    loadSidebarHistory();
                                }
                            } catch (err) {
                                alert(`Failed to delete session: ${err.message}`);
                            }
                        }
                    });
                }
                
                $sidebarList.appendChild(el);
            }
        } catch (err) {
            $sidebarList.innerHTML = `<div style="padding: 12px; font-size: 0.8rem; color: var(--color-emergency); text-align: center;">Failed to load history</div>`;
        }
    }

    // ── UI Helpers ───────────────────────────────────────────────────

    function appendMessage(role, text, type = '') {
        const msgEl = document.createElement('div');
        msgEl.className = `message ${role} ${type}`.trim();

        const roleLabel = role === 'user' ? 'You' : 'PEMA';
        msgEl.innerHTML = `
            <div class="message-role">${roleLabel}</div>
            <div class="message-bubble">${escapeHtml(text)}</div>
        `;

        $messages.appendChild(msgEl);
        scrollToBottom();
    }

    function appendError(text) {
        const el = document.createElement('div');
        el.className = 'message system';
        el.innerHTML = `
            <div class="message-role" style="color: var(--color-emergency)">Error</div>
            <div class="message-bubble" style="border-color: var(--color-emergency-border); color: #fca5a5;">${escapeHtml(text)}</div>
        `;
        $messages.appendChild(el);
        scrollToBottom();
    }

    function showTypingIndicator() {
        const el = document.createElement('div');
        el.className = 'message system';
        el.innerHTML = `
            <div class="message-role">PEMA</div>
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `;
        $messages.appendChild(el);
        scrollToBottom();
        return el;
    }

    function showEmergencyAlert() {
        $emergencyAlert.classList.remove('hidden');
        $inputArea.classList.add('disabled');
    }

    function showCompletionBanner(specialty, urgency) {
        const specialtyName = specialty.replace(/_/g, ' ');
        $completionSummary.textContent = `Recommended: ${capitalize(specialtyName)} · Urgency: ${capitalize(urgency)}`;
        $completionBanner.classList.remove('hidden');
        $inputArea.classList.add('disabled');
    }

    function clearChat() {
        $messages.innerHTML = '';
        $emergencyAlert.classList.add('hidden');
        $completionBanner.classList.add('hidden');
        $inputArea.classList.remove('disabled');
        turnNumber = 0;
        updateTurnCount();
    }

    function setStatus(text) {
        $sessionStatus.textContent = text;
    }

    function updateTurnCount() {
        $turnCount.textContent = `Turn ${turnNumber}`;
    }

    function enableInput() {
        $input.disabled = false;
        $btnSend.disabled = false;
        $inputArea.classList.remove('disabled');
    }

    function disableInput() {
        $btnSend.disabled = true;
    }

    function scrollToBottom() {
        requestAnimationFrame(() => {
            $chatArea.scrollTop = $chatArea.scrollHeight;
        });
    }

    function formatStatus(status) {
        const labels = {
            consent_framing: '📋 Consent & Framing',
            chief_complaint: '💬 Chief Complaint',
            fact_gathering: '🔍 Gathering Facts',
            specialty_routing: '🏥 Routing…',
            completed: '✅ Completed',
            escalated: '🚨 ESCALATED',
            abandoned: '⛔ Abandoned',
        };
        return labels[status] || status;
    }

    function formatSpecialty(s) {
        if (!s) return '';
        return s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    function formatDate(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        } catch {
            return '';
        }
    }

    function capitalize(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ── Textarea auto-resize ─────────────────────────────────────────

    function autoResizeTextarea() {
        $input.style.height = 'auto';
        $input.style.height = Math.min($input.scrollHeight, MAX_TEXTAREA_HEIGHT) + 'px';
    }

    // ── Event Listeners ──────────────────────────────────────────────

    // Send button
    $btnSend.addEventListener('click', sendMessage);

    // Enter to send, Shift+Enter for newline
    $input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Enable/disable send button based on input content
    $input.addEventListener('input', () => {
        autoResizeTextarea();
        $btnSend.disabled = !$input.value.trim() || isProcessing;
    });

    // Sidebar drawer toggling
    if ($btnSidebarToggle) {
        $btnSidebarToggle.addEventListener('click', openSidebar);
    }
    if ($sidebarBackdrop) {
        $sidebarBackdrop.addEventListener('click', closeSidebar);
    }

    function openSidebar() {
        if ($sidebar) $sidebar.classList.add('open');
        if ($sidebarBackdrop) $sidebarBackdrop.classList.add('visible');
    }

    function closeSidebar() {
        if ($sidebar) $sidebar.classList.remove('open');
        if ($sidebarBackdrop) $sidebarBackdrop.classList.remove('visible');
    }

    // New session button (both header and sidebar)
    if ($btnNew) {
        $btnNew.addEventListener('click', () => {
            createSession();
            closeSidebar();
        });
    }
    if ($btnSidebarNew) {
        $btnSidebarNew.addEventListener('click', () => {
            createSession();
            closeSidebar();
        });
    }

    // Language toggle click handlers (both header and sidebar)
    const $$langToggles = document.querySelectorAll('#lang-toggle, .sidebar-lang-toggle');
    $$langToggles.forEach(toggle => {
        toggle.addEventListener('click', (e) => {
            const btn = e.target.closest('.lang-btn');
            if (!btn) return;

            currentLanguage = btn.dataset.lang;

            // Sync active state on all language buttons
            document.querySelectorAll('.lang-btn[data-lang]').forEach(b => {
                b.classList.toggle('active', b.dataset.lang === currentLanguage);
            });

            // Update placeholder
            $input.placeholder = currentLanguage === 'ur'
                ? 'Apni alamaat batayen…'
                : 'Describe your symptoms…';

            // Update session
            updateSession();
        });
    });

    // Mode toggle click handlers (both header and sidebar)
    const $$modeToggles = document.querySelectorAll('#mode-toggle, .sidebar-mode-toggle');
    $$modeToggles.forEach(toggle => {
        toggle.addEventListener('click', (e) => {
            const btn = e.target.closest('.mode-btn');
            if (!btn) return;

            currentMode = btn.dataset.mode;

            // Sync active state on all mode buttons
            document.querySelectorAll('.mode-btn[data-mode]').forEach(b => {
                b.classList.toggle('active', b.dataset.mode === currentMode);
            });

            // Update session
            updateSession();
        });
    });

    // ── Init ─────────────────────────────────────────────────────────
    createSession();
})();
