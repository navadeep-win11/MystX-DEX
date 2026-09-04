/**
 * MystX DEX — Web Terminal & Workspace Engine
 * Part of MystX DEX Android Application
 */

(function() {
  'use strict';

  // State
  let currentSessionId = 'main';
  let activeSessions = [];
  let socket = null;
  let reconnectTimer = null;
  let reconnectAttempts = 0;
  const maxReconnectAttempts = 10;

  // Terminal Buffer
  const maxLines = 5000;
  let terminalLines = [];
  let currentLine = '';
  let cmdHistory = [];
  let historyIdx = -1;

  // DOM Elements
  const statusBadge = document.getElementById('status-badge');
  const statusText = document.getElementById('status-text');
  const terminalScreen = document.getElementById('terminal-screen');
  const cmdInput = document.getElementById('cmd-input');
  const sessionTabsList = document.getElementById('session-tabs-list');
  const navSessionCount = document.getElementById('nav-session-count');
  const currentFilePath = document.getElementById('current-file-path');
  const fileList = document.getElementById('file-list');
  const fileModal = document.getElementById('file-modal');
  const fileModalTitle = document.getElementById('file-modal-title');
  const fileModalContent = document.getElementById('file-modal-content');
  const aiMessages = document.getElementById('ai-messages');
  const aiInput = document.getElementById('ai-input');
  const sidebar = document.getElementById('mystx-sidebar');

  // ANSI color map
  const ansiColors = {
    30: '#000000', 31: '#ef4444', 32: '#10b981', 33: '#f59e0b',
    34: '#3b82f6', 35: '#a855f7', 36: '#06b6d4', 37: '#f8fafc',
    90: '#64748b', 91: '#f87171', 92: '#34d399', 93: '#fbbf24',
    94: '#60a5fa', 95: '#c084fc', 96: '#22d3ee', 97: '#ffffff'
  };

  // Initialize
  function init() {
    setupNavigation();
    setupVirtualKeys();
    setupCommandInput();
    setupWebSocket();
    setupSessions();
    setupFiles();
    setupAI();
    setupSettings();

    // Focus input or screen on load
    if (window.innerWidth > 768) {
      cmdInput.focus();
    }
  }

  // --- NAVIGATION ---
  function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const viewPanels = document.querySelectorAll('.view-panel');

    navItems.forEach(item => {
      item.addEventListener('click', () => {
        const targetView = item.getAttribute('data-view');
        navItems.forEach(n => n.classList.remove('active'));
        viewPanels.forEach(p => p.classList.remove('active'));

        item.classList.add('active');
        const targetPanel = document.getElementById(`view-${targetView}`);
        if (targetPanel) {
          targetPanel.classList.add('active');
        }

        // Close mobile sidebar
        if (window.innerWidth <= 768) {
          sidebar.classList.remove('open');
        }

        // Trigger view-specific loads
        if (targetView === 'sessions') refreshSessionsList();
        if (targetView === 'files') loadFiles(currentFilePath.textContent);
      });
    });

    const btnToggleSidebar = document.getElementById('btn-toggle-sidebar');
    if (btnToggleSidebar) {
      btnToggleSidebar.addEventListener('click', () => {
        sidebar.classList.toggle('open');
      });
    }

    const btnRefresh = document.getElementById('btn-refresh');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => {
        connectWebSocket();
      });
    }
  }

  // --- WEBSOCKET & TERMINAL ---
  function updateStatus(status) {
    statusBadge.className = 'badge';
    if (status === 'connected') {
      statusBadge.classList.add('badge-connected');
      statusText.textContent = 'Connected';
    } else if (status === 'connecting') {
      statusBadge.classList.add('badge-connecting');
      statusText.textContent = 'Connecting...';
    } else {
      statusBadge.classList.add('badge-disconnected');
      statusText.textContent = 'Disconnected';
    }
  }

  function setupWebSocket() {
    connectWebSocket();
  }

  function connectWebSocket() {
    if (socket) {
      try { socket.close(); } catch (e) {}
    }

    updateStatus('connecting');

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const cols = Math.floor(terminalScreen.clientWidth / 9) || 80;
    const rows = Math.floor(terminalScreen.clientHeight / 18) || 24;
    const wsUrl = `${protocol}//${window.location.host}/ws?session=${encodeURIComponent(currentSessionId)}&cols=${cols}&rows=${rows}`;

    socket = new WebSocket(wsUrl);
    socket.binaryType = 'arraybuffer';

    socket.onopen = function() {
      updateStatus('connected');
      reconnectAttempts = 0;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    socket.onmessage = function(event) {
      if (event.data instanceof ArrayBuffer) {
        const text = new TextDecoder('utf-8').decode(event.data);
        appendTerminalOutput(text);
      } else if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'session_init') {
            currentSessionId = msg.session_id;
            updateSessionTabs();
          } else if (msg.type === 'exit') {
            appendTerminalOutput('\r\n[Process completed]\r\n');
          } else {
            appendTerminalOutput(event.data);
          }
        } catch (e) {
          appendTerminalOutput(event.data);
        }
      }
    };

    socket.onclose = function() {
      updateStatus('disconnected');
      attemptReconnect();
    };

    socket.onerror = function() {
      updateStatus('disconnected');
    };
  }

  function attemptReconnect() {
    if (reconnectAttempts < maxReconnectAttempts) {
      const delay = Math.min(1000 * Math.pow(1.5, reconnectAttempts), 10000);
      reconnectAttempts++;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => {
        connectWebSocket();
      }, delay);
    }
  }

  function sendTerminalData(data) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(data);
    }
  }

  // --- TERMINAL ANSI PARSING & RENDERING ---
  function appendTerminalOutput(text) {
    // Process ANSI text and append to lines
    let i = 0;
    let len = text.length;

    while (i < len) {
      let ch = text[i];
      if (ch === '\r') {
        // Carriage return: reset current line or start new
        if (i + 1 < len && text[i + 1] === '\n') {
          terminalLines.push(currentLine);
          currentLine = '';
          i += 2;
          continue;
        } else {
          currentLine = '';
          i++;
          continue;
        }
      } else if (ch === '\n') {
        terminalLines.push(currentLine);
        currentLine = '';
        i++;
        continue;
      } else if (ch === '\x1b' && text[i + 1] === '[') {
        // ANSI escape sequence
        let endIdx = text.indexOf('m', i + 2);
        let cmdIdx = -1;
        // Check for other termination characters: H, J, K, etc.
        for (let j = i + 2; j < Math.min(i + 15, len); j++) {
          let code = text.charCodeAt(j);
          if ((code >= 65 && code <= 90) || (code >= 97 && code <= 122)) {
            cmdIdx = j;
            break;
          }
        }
        if (cmdIdx !== -1) {
          let codeStr = text.substring(i + 2, cmdIdx);
          let cmd = text[cmdIdx];
          if (cmd === 'm') {
            // SGR styling
            let color = ansiColors[parseInt(codeStr, 10)];
            if (color) {
              currentLine += `<span style="color:${color}">`;
            } else if (codeStr === '0' || codeStr === '') {
              currentLine += '</span>';
            }
          } else if (cmd === 'J' && codeStr === '2') {
            // Clear screen
            terminalLines = [];
            currentLine = '';
          }
          i = cmdIdx + 1;
          continue;
        }
      }

      // Escape HTML chars
      if (ch === '<') currentLine += '&lt;';
      else if (ch === '>') currentLine += '&gt;';
      else if (ch === '&') currentLine += '&amp;';
      else currentLine += ch;

      i++;
    }

    // Trim lines to scrollback buffer
    if (terminalLines.length > maxLines) {
      terminalLines = terminalLines.slice(terminalLines.length - maxLines);
    }

    renderTerminal();
  }

  let renderPending = false;
  function renderTerminal() {
    if (renderPending) return;
    renderPending = true;
    requestAnimationFrame(() => {
      terminalScreen.innerHTML = terminalLines.join('<br>') + (currentLine ? '<br>' + currentLine : '');
      terminalScreen.scrollTop = terminalScreen.scrollHeight;
      renderPending = false;
    });
  }

  // --- COMMAND INPUT & HISTORY ---
  function setupCommandInput() {
    cmdInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitCommand();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (cmdHistory.length > 0) {
          if (historyIdx === -1) historyIdx = cmdHistory.length - 1;
          else if (historyIdx > 0) historyIdx--;
          cmdInput.value = cmdHistory[historyIdx];
        }
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (historyIdx !== -1) {
          if (historyIdx < cmdHistory.length - 1) {
            historyIdx++;
            cmdInput.value = cmdHistory[historyIdx];
          } else {
            historyIdx = -1;
            cmdInput.value = '';
          }
        }
      }
    });

    const btnSendCmd = document.getElementById('btn-send-cmd');
    if (btnSendCmd) {
      btnSendCmd.addEventListener('click', submitCommand);
    }
  }

  function submitCommand() {
    const val = cmdInput.value;
    if (val.trim()) {
      cmdHistory.push(val);
      historyIdx = -1;
    }
    sendTerminalData(val + '\n');
    cmdInput.value = '';
    cmdInput.focus();
  }

  // --- VIRTUAL MOBILE KEYBOARD ---
  function setupVirtualKeys() {
    const keyButtons = document.querySelectorAll('.key-btn');
    keyButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        // Haptic feedback if enabled
        if (navigator.vibrate && document.getElementById('setting-vibrate').checked) {
          navigator.vibrate(15);
        }

        const key = btn.getAttribute('data-key');
        const action = btn.getAttribute('data-action');

        if (key === 'ESC') sendTerminalData('\x1b');
        else if (key === 'TAB') sendTerminalData('\t');
        else if (key === 'CTRL_C') sendTerminalData('\x03');
        else if (key === 'CTRL_Z') sendTerminalData('\x1a');
        else if (key === 'UP') sendTerminalData('\x1b[A');
        else if (key === 'DOWN') sendTerminalData('\x1b[B');
        else if (action === 'clear') {
          terminalLines = [];
          currentLine = '';
          renderTerminal();
          sendTerminalData('clear\n');
        } else if (action === 'copy') {
          const rawText = terminalScreen.innerText;
          navigator.clipboard.writeText(rawText).then(() => {
            alert('Terminal output copied to clipboard.');
          });
        } else if (action === 'paste') {
          navigator.clipboard.readText().then(text => {
            if (text) sendTerminalData(text);
          });
        }
      });
    });
  }

  // --- SESSIONS MANAGEMENT ---
  function setupSessions() {
    const btnNewSession = document.getElementById('btn-new-session');
    const btnCreateSessionAlt = document.getElementById('btn-create-session-alt');

    const handleCreate = () => {
      fetch('/api/sessions/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: `sess-${Date.now().toString().slice(-4)}` })
      })
      .then(res => res.json())
      .then(data => {
        currentSessionId = data.session_id;
        connectWebSocket();
        refreshSessionsList();
      });
    };

    if (btnNewSession) btnNewSession.addEventListener('click', handleCreate);
    if (btnCreateSessionAlt) btnCreateSessionAlt.addEventListener('click', handleCreate);

    updateSessionTabs();
  }

  function updateSessionTabs() {
    sessionTabsList.innerHTML = '';
    const tab = document.createElement('div');
    tab.className = 'session-tab active';
    tab.innerHTML = `<span>Session: ${currentSessionId}</span>`;
    sessionTabsList.appendChild(tab);
  }

  function refreshSessionsList() {
    fetch('/api/sessions')
      .then(res => res.json())
      .then(data => {
        const grid = document.getElementById('sessions-grid');
        grid.innerHTML = '';
        const list = data.sessions || [];
        navSessionCount.textContent = list.length;

        list.forEach(s => {
          const card = document.createElement('div');
          card.className = 'session-card';
          card.innerHTML = `
            <div class="session-card-header">
              <span class="session-card-title">${s.id}</span>
              <span class="pill-count">PID: ${s.pid}</span>
            </div>
            <div class="session-card-desc">
              Started: ${new Date(s.created_at * 1000).toLocaleTimeString()}
            </div>
            <div class="session-card-actions">
              <button class="btn-secondary btn-switch-session" data-id="${s.id}">Switch</button>
              <button class="btn-secondary btn-kill-session" data-id="${s.id}" style="color:#ef4444;">Kill</button>
            </div>
          `;
          grid.appendChild(card);
        });

        // Add events
        grid.querySelectorAll('.btn-switch-session').forEach(btn => {
          btn.addEventListener('click', () => {
            currentSessionId = btn.getAttribute('data-id');
            connectWebSocket();
            document.querySelector('.nav-item[data-view="terminal"]').click();
          });
        });

        grid.querySelectorAll('.btn-kill-session').forEach(btn => {
          btn.addEventListener('click', () => {
            const sid = btn.getAttribute('data-id');
            fetch('/api/sessions/kill', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ session_id: sid })
            }).then(() => refreshSessionsList());
          });
        });
      });
  }

  // --- FILES EXPLORER ---
  function setupFiles() {
    const btnUp = document.getElementById('btn-file-up');
    const btnRefresh = document.getElementById('btn-file-refresh');
    const btnCloseModal = document.getElementById('btn-close-file-modal');

    if (btnUp) {
      btnUp.addEventListener('click', () => {
        let cur = currentFilePath.textContent;
        let parts = cur.split('/').filter(Boolean);
        if (parts.length > 1) {
          parts.pop();
          loadFiles('/' + parts.join('/'));
        }
      });
    }

    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => {
        loadFiles(currentFilePath.textContent);
      });
    }

    if (btnCloseModal) {
      btnCloseModal.addEventListener('click', () => {
        fileModal.style.display = 'none';
      });
    }
  }

  function loadFiles(path) {
    fetch(`/api/files/list?path=${encodeURIComponent(path)}`)
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          alert('Cannot access path: ' + data.error);
          return;
        }
        currentFilePath.textContent = data.current_path;
        fileList.innerHTML = '';

        data.files.forEach(f => {
          const row = document.createElement('div');
          row.className = 'file-row';
          row.innerHTML = `
            <div class="file-info-left">
              <span>${f.is_dir ? '📁' : '📄'}</span>
              <span>${f.name}</span>
            </div>
            <div class="file-size">${f.is_dir ? 'DIR' : formatFileSize(f.size)}</div>
          `;
          row.addEventListener('click', () => {
            if (f.is_dir) {
              loadFiles(f.path);
            } else {
              viewFile(f.path);
            }
          });
          fileList.appendChild(row);
        });
      });
  }

  function viewFile(path) {
    fetch(`/api/files/read?path=${encodeURIComponent(path)}`)
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          alert(data.error);
          return;
        }
        fileModalTitle.textContent = data.path.split('/').pop();
        fileModalContent.textContent = data.content;
        fileModal.style.display = 'flex';
      });
  }

  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    let kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    return (kb / 1024).toFixed(1) + ' MB';
  }

  // --- AI AGENT WORKSPACE ---
  function setupAI() {
    const btnSend = document.getElementById('btn-ai-send');
    const modelSelect = document.getElementById('ai-model-select');

    const handleAISend = () => {
      const text = aiInput.value.trim();
      if (!text) return;

      // Add user message
      const uMsg = document.createElement('div');
      uMsg.className = 'ai-message user';
      uMsg.innerHTML = `
        <div class="msg-header">
          <span class="msg-author">You</span>
        </div>
        <div class="msg-body">${escapeHTML(text)}</div>
      `;
      aiMessages.appendChild(uMsg);
      aiInput.value = '';

      // Post to backend
      fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text, model: modelSelect.value })
      })
      .then(res => res.json())
      .then(data => {
        const aMsg = document.createElement('div');
        aMsg.className = 'ai-message assistant';
        aMsg.innerHTML = `
          <div class="msg-header">
            <span class="msg-author">MystX Agent</span>
            <span class="msg-badge">${data.model}</span>
          </div>
          <div class="msg-body">${escapeHTML(data.content)}</div>
        `;
        aiMessages.appendChild(aMsg);
        aiMessages.scrollTop = aiMessages.scrollHeight;
      });
    };

    if (btnSend) btnSend.addEventListener('click', handleAISend);
    if (aiInput) {
      aiInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          handleAISend();
        }
      });
    }
  }

  function escapeHTML(str) {
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }

  // --- SETTINGS ---
  function setupSettings() {
    const themeSelect = document.getElementById('setting-theme');
    const fontSizeSlider = document.getElementById('setting-font-size');
    const fontSizeVal = document.getElementById('font-size-val');

    if (themeSelect) {
      themeSelect.addEventListener('change', () => {
        document.body.className = themeSelect.value;
      });
    }

    if (fontSizeSlider) {
      fontSizeSlider.addEventListener('input', () => {
        fontSizeVal.textContent = fontSizeSlider.value + 'px';
        document.documentElement.style.setProperty('--terminal-font-size', fontSizeSlider.value + 'px');
      });
    }
  }

  // Start on DOM ready
  document.addEventListener('DOMContentLoaded', init);
})();
