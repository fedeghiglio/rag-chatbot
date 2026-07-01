/**
 * RAG Chatbot embeddable widget.
 *
 * Drop in with one script tag:
 *   <script src="https://<backend>/widget.js" data-api="https://<backend>"></script>
 *
 * Uses a Shadow DOM so the widget's styles are fully isolated from — and cannot
 * be broken by — any global CSS on the host page.
 */
(function () {
  'use strict';

  // Capture currentScript synchronously — it becomes null after the first tick.
  var script = document.currentScript;
  var API_URL = script && script.dataset.api
    ? script.dataset.api.replace(/\/+$/, '')
    : window.location.origin;

  // ── Shadow host ────────────────────────────────────────────────────────────
  var host = document.createElement('div');
  host.id = 'ragchat-widget';
  document.body.appendChild(host);
  var shadow = host.attachShadow({ mode: 'open' });

  // ── Styles (scoped inside shadow root; :host sets the fixed anchor) ────────
  var style = document.createElement('style');
  style.textContent = `
    :host {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 2147483647;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px;
      line-height: 1.5;
      color: #111827;
    }

    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    /* ── Toggle bubble ─────────────────────────────────────────────────── */
    .bubble {
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: #4f46e5;
      color: #fff;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
      font-size: 24px;
      transition: transform 0.15s, box-shadow 0.15s;
    }
    .bubble:hover {
      transform: scale(1.07);
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.34);
    }
    .bubble:focus-visible {
      outline: 3px solid #818cf8;
      outline-offset: 3px;
    }

    /* ── Chat panel ────────────────────────────────────────────────────── */
    .panel {
      position: absolute;
      bottom: 68px;
      right: 0;
      width: 360px;
      max-height: 520px;
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .panel[hidden] { display: none; }

    /* ── Header ────────────────────────────────────────────────────────── */
    .header {
      background: #4f46e5;
      color: #fff;
      padding: 13px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-weight: 600;
      font-size: 15px;
      flex-shrink: 0;
      letter-spacing: 0.01em;
    }
    .close-btn {
      background: none;
      border: none;
      color: #fff;
      cursor: pointer;
      font-size: 17px;
      line-height: 1;
      padding: 3px 7px;
      border-radius: 4px;
      opacity: 0.75;
      transition: opacity 0.1s, background 0.1s;
    }
    .close-btn:hover { opacity: 1; background: rgba(255, 255, 255, 0.15); }

    /* ── Messages area ─────────────────────────────────────────────────── */
    .messages {
      flex: 1;
      overflow-y: auto;
      padding: 14px 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      scroll-behavior: smooth;
    }
    /* Empty-state hint rendered entirely in CSS — no JS needed. */
    .messages:empty::after {
      content: 'Ask a question about your documents.';
      color: #9ca3af;
      font-style: italic;
      font-size: 13px;
      text-align: center;
      margin: auto;
    }

    .msg {
      display: flex;
      flex-direction: column;
      max-width: 88%;
    }
    .msg.user    { align-self: flex-end; }
    .msg.assistant { align-self: flex-start; }

    .bubble-text {
      border-radius: 10px;
      padding: 9px 12px;
      font-size: 13.5px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .msg.user .bubble-text {
      background: #4f46e5;
      color: #fff;
      border-bottom-right-radius: 3px;
    }
    .msg.assistant .bubble-text {
      background: #f3f4f6;
      border-bottom-left-radius: 3px;
    }
    .msg.error .bubble-text {
      background: #fee2e2;
      color: #991b1b;
    }

    /* ── Loading dots ──────────────────────────────────────────────────── */
    .loading {
      display: flex;
      gap: 5px;
      padding: 10px 12px;
      background: #f3f4f6;
      border-radius: 10px;
      border-bottom-left-radius: 3px;
      width: fit-content;
    }
    .dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #6b7280;
      animation: bounce 1.1s infinite ease-in-out;
    }
    .dot:nth-child(2) { animation-delay: 0.18s; }
    .dot:nth-child(3) { animation-delay: 0.36s; }
    @keyframes bounce {
      0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
      40%            { transform: translateY(-5px); opacity: 1; }
    }

    /* ── Sources (collapsible) ─────────────────────────────────────────── */
    .sources {
      margin-top: 7px;
      font-size: 12px;
    }
    .sources summary {
      cursor: pointer;
      color: #6b7280;
      user-select: none;
      list-style: none;
      display: flex;
      align-items: center;
      gap: 5px;
      padding: 2px 0;
    }
    .sources summary::before {
      content: '▶';
      font-size: 8px;
      display: inline-block;
      transition: transform 0.15s;
    }
    .sources[open] summary::before { transform: rotate(90deg); }
    /* Hide the default UA triangle in Chrome/Safari. */
    .sources summary::-webkit-details-marker { display: none; }

    .source-item {
      background: #f9fafb;
      border-left: 3px solid #4f46e5;
      border-radius: 0 5px 5px 0;
      padding: 7px 10px;
      margin-top: 5px;
    }
    .source-meta {
      font-weight: 600;
      color: #374151;
      margin-bottom: 4px;
      font-size: 11.5px;
    }
    .source-cited {
      color: #4b5563;
      font-style: italic;
      font-size: 11.5px;
      /* Clamp long passages to 4 lines. */
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    /* ── Input row ─────────────────────────────────────────────────────── */
    .input-row {
      display: flex;
      gap: 8px;
      padding: 10px 12px;
      border-top: 1px solid #e5e7eb;
      flex-shrink: 0;
      background: #fff;
    }
    .input {
      flex: 1;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      padding: 8px 10px;
      font-size: 13.5px;
      font-family: inherit;
      color: #111827;
      background: #fff;
      outline: none;
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    .input:focus {
      border-color: #4f46e5;
      box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12);
    }
    .input::placeholder { color: #9ca3af; }

    .send-btn {
      background: #4f46e5;
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 8px 14px;
      cursor: pointer;
      font-size: 13.5px;
      font-family: inherit;
      font-weight: 500;
      transition: background 0.15s;
      white-space: nowrap;
    }
    .send-btn:hover:not(:disabled) { background: #4338ca; }
    .send-btn:disabled { background: #9ca3af; cursor: not-allowed; }
  `;
  shadow.appendChild(style);

  // ── DOM structure ──────────────────────────────────────────────────────────
  var bubble = document.createElement('button');
  bubble.className = 'bubble';
  bubble.setAttribute('aria-label', 'Open chat');
  bubble.setAttribute('aria-expanded', 'false');
  bubble.textContent = '💬';
  shadow.appendChild(bubble);

  var panel = document.createElement('div');
  panel.className = 'panel';
  panel.setAttribute('hidden', '');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Document Q&A chat');
  shadow.appendChild(panel);

  var header = document.createElement('div');
  header.className = 'header';
  var headerTitle = document.createElement('span');
  headerTitle.textContent = 'Document Q&A';
  var closeBtn = document.createElement('button');
  closeBtn.className = 'close-btn';
  closeBtn.setAttribute('aria-label', 'Close');
  closeBtn.textContent = '✕';
  header.appendChild(headerTitle);
  header.appendChild(closeBtn);
  panel.appendChild(header);

  var messages = document.createElement('div');
  messages.className = 'messages';
  messages.setAttribute('role', 'log');
  messages.setAttribute('aria-live', 'polite');
  panel.appendChild(messages);

  var inputRow = document.createElement('div');
  inputRow.className = 'input-row';
  var input = document.createElement('input');
  input.type = 'text';
  input.className = 'input';
  input.placeholder = 'Ask a question…';
  input.setAttribute('aria-label', 'Your question');
  var sendBtn = document.createElement('button');
  sendBtn.className = 'send-btn';
  sendBtn.textContent = 'Send';
  inputRow.appendChild(input);
  inputRow.appendChild(sendBtn);
  panel.appendChild(inputRow);

  // ── Panel toggle ───────────────────────────────────────────────────────────
  function openPanel() {
    panel.removeAttribute('hidden');
    bubble.textContent = '✕';
    bubble.setAttribute('aria-label', 'Close chat');
    bubble.setAttribute('aria-expanded', 'true');
    input.focus();
  }

  function closePanel() {
    panel.setAttribute('hidden', '');
    bubble.textContent = '💬';
    bubble.setAttribute('aria-label', 'Open chat');
    bubble.setAttribute('aria-expanded', 'false');
  }

  bubble.addEventListener('click', function () {
    panel.hasAttribute('hidden') ? openPanel() : closePanel();
  });
  closeBtn.addEventListener('click', closePanel);

  // ── Message rendering ──────────────────────────────────────────────────────
  // All dynamic content uses textContent / createTextNode — never innerHTML —
  // so model output and PDF text can never inject script or markup.

  function addUserBubble(text) {
    var wrap = document.createElement('div');
    wrap.className = 'msg user';
    var bub = document.createElement('div');
    bub.className = 'bubble-text';
    bub.textContent = text;
    wrap.appendChild(bub);
    messages.appendChild(wrap);
    messages.scrollTop = messages.scrollHeight;
  }

  function addLoadingBubble() {
    var wrap = document.createElement('div');
    wrap.className = 'msg assistant';
    var inner = document.createElement('div');
    inner.className = 'loading';
    for (var i = 0; i < 3; i++) {
      var dot = document.createElement('span');
      dot.className = 'dot';
      inner.appendChild(dot);
    }
    wrap.appendChild(inner);
    messages.appendChild(wrap);
    messages.scrollTop = messages.scrollHeight;
    return wrap; // caller holds this to replace it later
  }

  function buildAnswerBubble(data) {
    var wrap = document.createElement('div');
    wrap.className = 'msg assistant';

    var bub = document.createElement('div');
    bub.className = 'bubble-text';
    bub.textContent = data.answer;
    wrap.appendChild(bub);

    var srcs = data.sources || [];
    var cited = data.chunks_used || 0;

    if (cited > 0 && srcs.length > 0) {
      var details = document.createElement('details');
      details.className = 'sources';

      var summary = document.createElement('summary');
      summary.textContent = 'Sources — ' + cited + ' chunk' + (cited !== 1 ? 's' : '') + ' cited';
      details.appendChild(summary);

      for (var i = 0; i < srcs.length; i++) {
        var src = srcs[i];
        var item = document.createElement('div');
        item.className = 'source-item';

        var meta = document.createElement('div');
        meta.className = 'source-meta';
        // src.source is the filename; never concatenated unsafely into markup
        meta.textContent = src.source
          + '  ·  chunk ' + src.chunk_index
          + '  (sim ' + Number(src.similarity).toFixed(3) + ')';
        item.appendChild(meta);

        if (src.cited_text) {
          var ct = document.createElement('div');
          ct.className = 'source-cited';
          // “ and ” are left/right curly double-quotes
          ct.textContent = '“' + src.cited_text + '”';
          item.appendChild(ct);
        }

        details.appendChild(item);
      }

      wrap.appendChild(details);
    }

    return wrap;
  }

  function buildErrorBubble(message) {
    var wrap = document.createElement('div');
    wrap.className = 'msg assistant error';
    var bub = document.createElement('div');
    bub.className = 'bubble-text';
    bub.textContent = message;
    wrap.appendChild(bub);
    return wrap;
  }

  // ── Submit ─────────────────────────────────────────────────────────────────
  var busy = false;

  async function submit() {
    var text = input.value.trim();
    if (!text || busy) return;

    busy = true;
    sendBtn.disabled = true;
    input.disabled = true;
    input.value = '';

    addUserBubble(text);
    var placeholder = addLoadingBubble();

    try {
      var res = await fetch(API_URL + '/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, top_k: 5 }),
      });

      if (!res.ok) {
        var detail = 'Error ' + res.status;
        try {
          var errBody = await res.json();
          if (errBody.detail) detail = String(errBody.detail);
        } catch (_) {}
        throw new Error(detail);
      }

      var data = await res.json();
      placeholder.replaceWith(buildAnswerBubble(data));
    } catch (err) {
      placeholder.replaceWith(buildErrorBubble('⚠ ' + (err.message || 'Request failed')));
    } finally {
      busy = false;
      sendBtn.disabled = false;
      input.disabled = false;
      messages.scrollTop = messages.scrollHeight;
      input.focus();
    }
  }

  sendBtn.addEventListener('click', submit);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  });
}());
