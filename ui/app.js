/* ============================================================
   CCRE Rules Intelligence — onboarding workspace (v2)
   Talks only to /api/* on the same origin.
   ============================================================ */
'use strict';

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = 'ccre.token';

const S = {
  me: null,            // /api/auth/me
  meta: null,          // /api/lifecycle
  cases: [],
  caseId: null,
  overview: null,
  viewStage: null,     // stage key being viewed
  intakeTab: 'chat',
  devRole: 'ADMIN',
  busy: false,
};

const CCRE = ['CCRE_TEAM', 'CCRE_CONSULTANT', 'ADMIN'];
const NEEDS_COMMENT = new Set(['return_requirement', 'return_timeline', 'sanity_failed', 'ccre_return_test_cases',
  'business_return_test_cases', 'request_correction', 'business_reject_results', 'withdraw']);

// ── helpers ──────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
const role = () => (S.me ? S.me.role : null);
const isBusiness = () => role() === 'BUSINESS';
const hasRole = (...roles) => roles.includes(role());
const state = () => (S.overview ? S.overview.state : null);

function getToken() { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } }
function setToken(t) { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ } }

async function api(method, path, body) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (S.me && S.me.dev) headers['X-CCRE-Role'] = S.devRole;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const resp = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await resp.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
  if (resp.status === 401 && !path.startsWith('/api/auth/login')) {
    setToken(null);
    showLogin();
    throw new Error('Please sign in.');
  }
  if (!resp.ok) {
    const d = data && data.detail;
    const msg = typeof d === 'string' ? d
      : d && d.message ? `${d.message}${d.reasons && d.reasons.length ? ' — ' + d.reasons.join(' ') : ''}`
      : Array.isArray(d) ? d.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join('; ')
      : `HTTP ${resp.status}`;
    throw new Error(msg);
  }
  return data;
}

function toast(message, bad) {
  const el = document.createElement('div');
  el.textContent = message;
  el.style.cssText = `position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:70;padding:10px 16px;
    border-radius:8px;font-size:13px;box-shadow:0 6px 20px rgba(0,0,0,.18);max-width:80vw;
    background:${bad ? '#fee2e2' : '#ecfdf5'};color:${bad ? '#7f1d1d' : '#065f46'};border:1px solid ${bad ? '#fca5a5' : '#a7f3d0'}`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), bad ? 7000 : 3500);
}

async function run(label, fn) {
  if (S.busy) return;
  S.busy = true;
  document.body.style.cursor = 'progress';
  const errBox = $('error-box');
  if (errBox) errBox.classList.remove('dhl-error-box--show');
  try { await fn(); } catch (err) { toast(`${label}: ${err.message}`, true); } finally {
    S.busy = false;
    document.body.style.cursor = '';
  }
}

function kv(pairs) {
  return `<dl class="ccre-kv">${pairs.map(([k, v]) =>
    `<dt>${esc(k)}</dt><dd>${v === null || v === undefined || v === '' ? '—' : esc(v)}</dd>`).join('')}</dl>`;
}
function list(items, cls) {
  if (!items || !items.length) return '<p class="ccre-hint">None.</p>';
  return `<ul class="ccre-list">${items.map((i) => `<li class="${cls || ''}">${esc(i)}</li>`).join('')}</ul>`;
}
function table(headers, rows) {
  return `<div class="ccre-table-wrap"><table class="ccre-table"><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${rows.join('') || `<tr><td colspan="${headers.length}" class="ccre-hint">Nothing yet.</td></tr>`}</tbody></table></div>`;
}
const pre = (obj) => `<pre class="ccre-pre">${esc(typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2))}</pre>`;
const cond = (c) => `${c.field} ${c.operator}${c.value !== null && c.value !== undefined ? ' ' + c.value : ''}`;

// ── dialog ───────────────────────────────────────────────────
function dialog(title, bodyHtml, okLabel = 'OK') {
  return new Promise((resolve) => {
    $('dialog-title').textContent = title;
    $('dialog-body').innerHTML = bodyHtml;
    $('dialog-ok').textContent = okLabel;
    $('dialog').hidden = false;
    const first = $('dialog-body').querySelector('input,textarea,select');
    if (first) first.focus();
    const done = (value) => { $('dialog').hidden = true; $('dialog-form').onsubmit = null; resolve(value); };
    $('dialog-form').onsubmit = (e) => {
      e.preventDefault();
      const values = {};
      $('dialog-body').querySelectorAll('[name]').forEach((f) => { values[f.name] = f.value; });
      done(values);
    };
    $('dialog-cancel').onclick = () => done(null);
  });
}

// ── auth ─────────────────────────────────────────────────────
function showLogin() {
  $('app-view').hidden = true;
  $('login-view').hidden = false;
  $('login-email').focus();
}

$('login-form').onsubmit = async (e) => {
  e.preventDefault();
  $('login-error').hidden = true;
  try {
    const res = await api('POST', '/api/auth/login', { email: $('login-email').value, password: $('login-password').value });
    setToken(res.token);
    $('login-password').value = '';
    await enterApp();
  } catch (err) {
    $('login-error').textContent = err.message;
    $('login-error').hidden = false;
  }
};

$('btn-logout').onclick = () => { setToken(null); S.me = null; S.caseId = null; showLogin(); };

$('btn-password').onclick = () => run('Change password', async () => {
  if (S.me.dev) throw new Error('Development mode has no passwords.');
  const v = await dialog('Change password', `
    <label class="ccre-field-label">Current password</label><input class="dhl-input" type="password" name="current" required>
    <label class="ccre-field-label">New password (8+ characters)</label><input class="dhl-input" type="password" name="next" minlength="8" required>`, 'Change');
  if (!v) return;
  await api('POST', '/api/auth/change-password', { current_password: v.current, new_password: v.next });
  toast('Password changed.');
});

$('dev-role').onchange = async (e) => {
  S.devRole = e.target.value;
  await enterApp();
};

async function enterApp() {
  S.me = await api('GET', '/api/auth/me');
  $('login-view').hidden = true;
  $('app-view').hidden = false;
  $('user-name').textContent = S.me.dev ? 'Development mode' : S.me.name;
  $('user-role').textContent = S.me.role.replace('_', ' ');
  $('dev-role').hidden = !S.me.dev;
  $('btn-password').hidden = !!S.me.dev;
  $('btn-logout').hidden = !!S.me.dev;
  document.querySelectorAll('[data-internal]').forEach((el) => { el.hidden = isBusiness(); });
  document.querySelectorAll('[data-admin]').forEach((el) => { el.hidden = role() !== 'ADMIN'; });
  S.meta = S.meta || await api('GET', '/api/lifecycle');
  loadStatus();
  switchView('onboardings');
  await loadCases();
}

async function loadStatus() {
  try {
    const [health, agents] = await Promise.all([api('GET', '/api/health'), api('GET', '/api/agents')]);
    $('status-badge').className = 'dhl-badge dhl-badge--online';
    $('status-label').textContent = `Online · LLM ${agents.llm_mode}${agents.available ? '' : ' (off)'}`
      + (isBusiness() ? '' : ` · ${health.packages.length} package(s)`);
  } catch {
    $('status-badge').className = 'dhl-badge dhl-badge--error';
    $('status-label').textContent = 'Offline';
  }
}

// ── views ────────────────────────────────────────────────────
function switchView(view) {
  ['onboardings', 'kpis', 'admin'].forEach((v) => { $(`view-${v}`).hidden = v !== view; });
  document.querySelectorAll('.ccre-nav__item').forEach((b) =>
    b.classList.toggle('ccre-nav__item--active', b.dataset.view === view));
  if (view === 'kpis') run('KPIs', renderKpis);
  if (view === 'admin') run('Admin', renderAdmin);
}
document.querySelectorAll('.ccre-nav__item').forEach((b) => { b.onclick = () => switchView(b.dataset.view); });

// ── onboarding list ──────────────────────────────────────────
async function loadCases(selectId) {
  S.cases = await api('GET', '/api/onboardings');
  $('case-list').innerHTML = S.cases.length ? S.cases.map((c) => `
    <button class="ccre-case-item${c.id === S.caseId ? ' ccre-case-item--active' : ''}" data-id="${esc(c.id)}">
      <div class="ccre-case-item__top"><span>${esc(c.country)} · ${esc(c.title)}</span></div>
      <div class="ccre-case-item__state">${esc(c.code)} — ${esc(c.state_label)}</div>
    </button>`).join('')
    : `<p class="ccre-hint">No onboardings yet${hasRole('PM') ? '' : ' — click “+ New”'}.</p>`;
  $('case-list').querySelectorAll('.ccre-case-item').forEach((b) => { b.onclick = () => openCase(b.dataset.id); });
  $('btn-new').hidden = hasRole('PM');
  const target = selectId || S.caseId;
  if (target && S.cases.some((c) => c.id === target)) await openCase(target, true);
  else { S.caseId = null; $('case-view').hidden = true; $('case-empty').hidden = false; }
}

$('btn-new').onclick = () => { $('new-form').hidden = !$('new-form').hidden; };
$('new-form').onsubmit = (e) => {
  e.preventDefault();
  run('Create onboarding', async () => {
    const created = await api('POST', '/api/onboardings', {
      ctry_cd: $('new-country').value.trim().toUpperCase(), title: $('new-title').value.trim() });
    $('new-form').hidden = true;
    $('new-country').value = ''; $('new-title').value = '';
    S.intakeTab = 'chat';
    await loadCases(created.id);
  });
};

// ── case workspace ───────────────────────────────────────────
async function openCase(id, keepStage) {
  const changed = id !== S.caseId;
  S.caseId = id;
  S.overview = await api('GET', `/api/onboardings/${id}`);
  if (changed || !keepStage) S.viewStage = S.overview.stage;
  document.querySelectorAll('.ccre-case-item').forEach((b) =>
    b.classList.toggle('ccre-case-item--active', b.dataset.id === id));
  $('case-empty').hidden = true;
  $('case-view').hidden = false;
  renderCaseHead();
  renderStepper();
  renderActions();
  await renderStage();
}

async function refreshCase() {
  await loadCases(S.caseId);
}

function renderCaseHead() {
  const o = S.overview;
  $('case-code').textContent = o.code;
  $('case-title').textContent = o.title;
  $('case-country').textContent = o.country;
  $('case-cycle').textContent = o.cycle;
  $('case-rtp').textContent = o.planned_rtp || '—';
  const st = $('case-state');
  st.textContent = o.state_label;
  st.className = 'dhl-val-chip ' + (o.state === 'COMPLETED' ? 'dhl-val-chip--pass'
    : o.state === 'WITHDRAWN' ? 'dhl-val-chip--fail' : 'dhl-val-chip--warn');
}

function visibleStages() {
  if (!isBusiness()) return S.meta.stages.map((s) => ({ key: s.key, label: s.label, keys: [s.key] }));
  const merged = [];
  S.meta.stages.forEach((s) => {
    const last = merged[merged.length - 1];
    if (last && last.label === s.business_label) last.keys.push(s.key);
    else merged.push({ key: s.key, label: s.business_label, keys: [s.key] });
  });
  return merged;
}

function renderStepper() {
  const stages = visibleStages();
  const order = S.meta.stages.map((s) => s.key);
  const current = order.indexOf(S.overview.stage);
  $('stepper').innerHTML = stages.map((s, i) => {
    const idx = Math.max(...s.keys.map((k) => order.indexOf(k)));
    const first = Math.min(...s.keys.map((k) => order.indexOf(k)));
    let cls = 'ccre-step';
    if (S.overview.state === 'COMPLETED' || idx < current) cls += ' ccre-step--done';
    else if (current >= first && current <= idx) cls += ' ccre-step--current';
    if (s.keys.includes(S.viewStage)) cls += ' ccre-step--viewing';
    return `<button class="${cls}" data-stage="${esc(s.keys.includes(S.overview.stage) ? S.overview.stage : s.key)}">${i + 1}. ${esc(s.label)}</button>`;
  }).join('');
  $('stepper').querySelectorAll('.ccre-step').forEach((b) => {
    b.onclick = () => { S.viewStage = b.dataset.stage; renderStepper(); renderStage(); };
  });
}

function renderActions() {
  const acts = S.overview.actions || [];
  $('actions').innerHTML = acts.map((a) => `
    <div class="ccre-action">
      <button class="dhl-btn ${/return|reject|failed|correction|withdraw/.test(a.name) ? 'dhl-btn--ghost' : 'dhl-btn--primary'} dhl-btn--sm"
        data-act="${esc(a.name)}" ${a.allowed ? '' : 'disabled'}>${esc(a.label)}</button>
      ${a.allowed ? '' : `<div class="ccre-action__why">${esc(a.blocked_by.join(' '))}</div>`}
    </div>`).join('');
  $('actions').querySelectorAll('[data-act]').forEach((b) => {
    b.onclick = () => run('Action', async () => {
      const name = b.dataset.act;
      let comment = null;
      if (NEEDS_COMMENT.has(name)) {
        const v = await dialog(b.textContent, `<label class="ccre-field-label">Reason (recorded on the audit trail)</label>
          <textarea class="dhl-textarea ccre-small" name="comment" required></textarea>`, 'Confirm');
        if (!v) return;
        comment = v.comment;
      }
      await api('POST', `/api/onboardings/${S.caseId}/transition`, { name, comment });
      toast(`Done: ${b.textContent}`);
      S.viewStage = null;
      await refreshCase();
    });
  });
}

async function renderStage() {
  const el = $('stage-body');
  el.innerHTML = '<p class="ccre-hint">Loading…</p>';
  const renderers = {
    intake: renderIntake, timeline: renderTimeline, rule_config: renderRuleConfig, sanity: renderSanity,
    uat_prep: renderTestCases, uat_review: renderTestCases, uat_execution: renderExecution,
    uat_signoff: renderResults, rtp: renderRtp,
  };
  try {
    await (renderers[S.viewStage] || renderIntake)(el);
  } catch (err) {
    el.innerHTML = `<div class="dhl-error-box dhl-error-box--show">${esc(err.message)}</div>`;
  }
}

function businessWaiting(el, text) {
  el.innerHTML = `<div class="ccre-card"><p>${esc(text)}</p>
    <p class="ccre-hint">Current status: <strong>${esc(S.overview.state_label)}</strong>.</p></div>`;
}

// ── 1. Intake ────────────────────────────────────────────────
function requirementCard(req) {
  if (!req) return '<p class="ccre-hint">No requirement captured yet.</p>';
  const r = req.structured || {};
  return `<div class="ccre-card">
    <div class="ccre-row ccre-space"><strong>Requirement v${req.version}</strong>
      <span class="dhl-val-chip">${esc(req.mode === 'CHAT' ? 'from chat' : 'from form + NLP')}</span></div>
    ${r.summary ? `<p>${esc(r.summary)}</p>` : ''}
    ${kv([['Country', r.country_code], ['Shipment type', r.shipment_type], ['Direction', r.direction],
      ['Requirement groups', (r.requirement_groups || []).join(', ')], ['Requested go-live', r.requested_rtp],
      ['Business owner', r.business_owner], ['Confidence', r.confidence]])}
    <h4>Conditions</h4>${list((r.conditions || []).map(cond))}
    ${(r.ambiguities || []).length ? `<h4>Ambiguities</h4>${list(r.ambiguities, 'ccre-warn')}` : ''}
    ${(r.missing_information || []).length ? `<h4>Missing information</h4>${list(r.missing_information, 'ccre-warn')}` : ''}
    <p class="ccre-hint">Captured by ${esc(req.created_by)}</p></div>`;
}

async function renderIntake(el) {
  const data = await api('GET', `/api/onboardings/${S.caseId}/intake`);
  const editable = state() === 'INTAKE' && hasRole('BUSINESS', 'CCRE_TEAM', 'CCRE_CONSULTANT', 'ADMIN');
  const reviewNote = state() === 'REQUIREMENT_REVIEW'
    ? '<div class="dhl-gate__notice">The requirement is with the CCRE consultant for approval.</div>' : '';
  let input = '';
  if (editable) {
    input = `<div class="ccre-subtabs">
        <button class="dhl-tab ${S.intakeTab === 'chat' ? 'dhl-tab--active' : ''}" data-tab="chat">&#128172; Chat</button>
        <button class="dhl-tab ${S.intakeTab === 'form' ? 'dhl-tab--active' : ''}" data-tab="form">&#128221; Form + NLP</button>
      </div>`;
    if (S.intakeTab === 'chat') {
      input += `<div class="ccre-intake-chat" id="intake-chat">${data.messages.length ? data.messages.map((m) =>
        `<div class="ccre-bubble ccre-bubble--${m.role}">${esc(m.text)}</div>`).join('')
        : '<div class="ccre-bubble ccre-bubble--assistant">Hi! Tell me about the customs requirement you need — which country and what should be requested. I will ask a few questions.</div>'}</div>
        <div class="ccre-row ccre-gap"><textarea id="intake-msg" class="dhl-textarea ccre-small" placeholder="Type your answer…"></textarea>
        <button id="intake-send" class="dhl-btn dhl-btn--primary">Send</button></div>`;
    } else {
      input += `<form id="intake-form" class="ccre-card">
        <label class="ccre-field-label">Describe the requirement in your own words</label>
        <textarea name="description" class="dhl-textarea ccre-req" required placeholder="e.g. Consumer parcels must provide the IOSS number when SDT is present and the shipment is not duty-paid (DD)."></textarea>
        <div class="ccre-grid2 ccre-gap">
          <div><label class="ccre-field-label">Shipment type</label><select name="shipment_type" class="dhl-input">
            <option value="">— not sure —</option><option>B2C</option><option>B2B</option><option>B2B/B2C</option></select></div>
          <div><label class="ccre-field-label">Requirement / document codes</label><input name="groups" class="dhl-input" placeholder="IOSS, POAB"></div>
          <div><label class="ccre-field-label">Requested go-live</label><input name="requested_rtp" type="date" class="dhl-input"></div>
          <div><label class="ccre-field-label">Business owner</label><input name="business_owner" class="dhl-input"></div>
          <div><label class="ccre-field-label">Value threshold</label><input name="value_threshold" type="number" step="0.01" class="dhl-input"></div>
          <div><label class="ccre-field-label">Currency</label><input name="currency" class="dhl-input" maxlength="3" placeholder="EUR"></div>
        </div>
        <button class="dhl-btn dhl-btn--primary ccre-gap" type="submit">Convert with NLP</button></form>`;
    }
  }
  el.innerHTML = `<h3>Requirement intake</h3>${reviewNote}${input}<h4>Captured requirement</h4>${requirementCard(data.requirement)}`;
  const chatBox = $('intake-chat');
  if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;
  el.querySelectorAll('.ccre-subtabs .dhl-tab').forEach((b) => {
    b.onclick = () => { S.intakeTab = b.dataset.tab; renderStage(); };
  });
  const send = () => run('Intake chat', async () => {
    const msg = $('intake-msg').value.trim();
    if (!msg) return;
    $('intake-send').disabled = true;
    const res = await api('POST', `/api/onboardings/${S.caseId}/intake/chat`, { message: msg });
    if (res.complete) { toast('Requirement captured — review it and submit.'); await refreshCase(); } else await renderStage();
  });
  if ($('intake-send')) {
    $('intake-send').onclick = send;
    $('intake-msg').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
    $('intake-msg').focus();
  }
  if ($('intake-form')) {
    $('intake-form').onsubmit = (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      run('Form intake', async () => {
        await api('POST', `/api/onboardings/${S.caseId}/intake/form`, {
          description: f.get('description'), shipment_type: f.get('shipment_type') || null,
          requirement_groups: String(f.get('groups') || '').split(/[,\s]+/).filter(Boolean),
          requested_rtp: f.get('requested_rtp') || null, business_owner: f.get('business_owner') || null,
          value_threshold: f.get('value_threshold') ? Number(f.get('value_threshold')) : null,
          currency: f.get('currency') || null,
        });
        toast('Requirement captured — review it and submit.');
        await refreshCase();
      });
    };
  }
}

// ── 2. Timeline ──────────────────────────────────────────────
async function renderTimeline(el) {
  const tl = S.overview.timeline;
  if (isBusiness() && !tl) return businessWaiting(el, 'The delivery timeline will appear here once the PM approves it.');
  const planning = state() === 'TIMELINE_PLANNING';
  const editable = !isBusiness() && ['TIMELINE_PLANNING', 'TIMELINE_REVIEW'].includes(state())
    && hasRole('PM', 'CCRE_TEAM', 'ADMIN');
  let html = '<h3>Delivery timeline</h3>';
  if (planning && hasRole('PM', 'CCRE_TEAM', 'ADMIN')) {
    const prev = (tl && tl.answers) || {};
    html += `<form id="tl-form" class="ccre-card"><strong>PM questionnaire</strong>
      <p class="ccre-hint">The AI plans the seven milestones from these answers; the PM approves the plan before it is shown to the business team.</p>
      <div class="ccre-grid2 ccre-gap">${S.meta.questions.map((q) => {
        const val = prev[q.id] ?? q.default ?? '';
        const label = `<label class="ccre-field-label">${esc(q.question)}${q.required ? ' *' : ''}</label>`;
        if (q.type === 'choice') {
          return `<div>${label}<select class="dhl-input" name="${q.id}">${q.options.map((o) =>
            `<option ${String(val) === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select></div>`;
        }
        const type = q.type === 'date' ? 'date' : q.type === 'number' ? 'number' : 'text';
        return `<div>${label}<input class="dhl-input" type="${type}" name="${q.id}" value="${esc(val)}" ${q.required ? 'required' : ''}></div>`;
      }).join('')}</div>
      <button class="dhl-btn dhl-btn--primary ccre-gap" type="submit">${tl ? 'Regenerate timeline' : 'Generate timeline'}</button></form>`;
  }
  if (tl) {
    const rows = tl.milestones.map((m, i) => `<tr>
      <td>${i + 1}. ${esc(m.name)}</td><td>${esc(m.owner)}</td>
      <td>${editable ? `<input type="date" class="dhl-input ccre-date" data-ms="${esc(m.stage)}" data-f="start" value="${esc(m.start)}">` : esc(m.start)}</td>
      <td>${editable ? `<input type="date" class="dhl-input ccre-date" data-ms="${esc(m.stage)}" data-f="end" value="${esc(m.end)}">` : esc(m.end)}</td>
      <td>${esc(m.actual_start || '')}${m.actual_end ? ' → ' + esc(m.actual_end) : ''}</td>
      <td>${esc(m.notes || '')}</td></tr>`);
    html += `<div class="ccre-row ccre-space"><span>Version ${tl.version} · <strong>${esc(tl.status)}</strong>
        ${tl.approved_by ? ` · approved by ${esc(tl.approved_by)}` : ''}</span>
        ${tl.at_risk ? '<span class="ccre-badge-risk">&#9888; Requested go-live at risk</span>' : '<span class="dhl-val-chip dhl-val-chip--pass">On track for requested go-live</span>'}</div>
      ${table(['Milestone', 'Owner', 'Planned start', 'Planned end', 'Actual', 'Notes'], rows)}
      ${editable ? '<button id="tl-save" class="dhl-btn dhl-btn--ghost ccre-gap">Save date changes</button>' : ''}
      ${tl.risks.length ? `<h4>Risks</h4>${list(tl.risks, 'ccre-warn')}` : ''}
      ${!isBusiness() ? `<h4>Assumptions</h4>${list(tl.assumptions)}` : ''}
      ${!isBusiness() && tl.open_questions.length ? `<h4>Open questions</h4>${list(tl.open_questions, 'ccre-warn')}` : ''}`;
  } else if (!planning) {
    html += '<p class="ccre-hint">The timeline is planned after the CCRE consultant approves the requirement.</p>';
  }
  el.innerHTML = html;
  if ($('tl-form')) {
    $('tl-form').onsubmit = (e) => {
      e.preventDefault();
      const answers = Object.fromEntries(new FormData(e.target).entries());
      run('Generate timeline', async () => {
        await api('POST', `/api/onboardings/${S.caseId}/timeline/generate`, { answers });
        toast('Timeline generated — review it, then submit for PM approval.');
        await refreshCase();
      });
    };
  }
  if ($('tl-save')) {
    $('tl-save').onclick = () => run('Save timeline', async () => {
      const ms = tl.milestones.map((m) => ({
        stage: m.stage, notes: m.notes,
        start: el.querySelector(`[data-ms="${m.stage}"][data-f="start"]`).value,
        end: el.querySelector(`[data-ms="${m.stage}"][data-f="end"]`).value,
      }));
      await api('PATCH', `/api/onboardings/${S.caseId}/timeline`, { milestones: ms });
      toast('Timeline updated.');
      await refreshCase();
    });
  }
}

// ── 3. Rule config + DMG (M2C) ───────────────────────────────
function findingsHtml(rep) {
  const sev = { blocker: 'ccre-bad', caution: 'ccre-warn', info: 'ccre-info' };
  return `<p>${rep.clean ? '<span class="dhl-val-chip dhl-val-chip--pass">No blockers</span>'
    : `<span class="dhl-val-chip dhl-val-chip--fail">${rep.blocker_count} blocker(s)</span>`}
    · ${rep.caution_count} to confirm · ${rep.info_count} info</p>
    <ul class="ccre-list">${(rep.findings || []).map((f) => `<li class="${sev[f.severity] || ''}">
      <div class="ccre-finding__head"><span class="ccre-finding__code">${esc(f.code)}</span>
      <span class="ccre-finding__where">${esc(f.where)}</span></div><div>${esc(f.message)}</div>
      ${f.evidence ? `<div class="ccre-finding__evidence">${esc(f.evidence)}</div>` : ''}</li>`).join('')}</ul>`;
}

async function renderRuleConfig(el) {
  if (isBusiness()) return businessWaiting(el, 'The CCRE team is configuring the rules and DMG changes for your requirement.');
  const m = await api('GET', `/api/onboardings/${S.caseId}/m2c`);
  const canEdit = state() === 'RULE_CONFIG' && hasRole(...CCRE);
  let html = '<h3>Rule config + DMG changes (M2C draft)</h3>';
  if (!m.rule_set) {
    html += canEdit
      ? '<p>Start the M2C draft. It is seeded with this country\'s existing workbook rows.</p><button id="m2c-start" class="dhl-btn dhl-btn--primary">Start M2C draft</button>'
      : '<p class="ccre-hint">The M2C draft starts when the onboarding reaches rule configuration.</p>';
    el.innerHTML = html;
    if ($('m2c-start')) {
      $('m2c-start').onclick = () => run('Start M2C', async () => {
        const r = await api('POST', `/api/onboardings/${S.caseId}/m2c/start`);
        toast(`M2C draft started — ${r.rules_copied} existing row(s) copied.`);
        await refreshCase();
      });
    }
    return;
  }
  const proposals = m.proposals.filter((p) => p.status === 'PROPOSED');
  html += `<p class="ccre-hint">${esc(m.note)}</p>
    <div class="ccre-row ccre-wrap ccre-gap">
      ${canEdit ? '<input id="m2c-notes" class="dhl-input" placeholder="Notes for the AI drafter (optional)"><button id="m2c-draft" class="dhl-btn dhl-btn--primary">&#9998; Convert requirement to M2C (AI)</button>' : ''}
      <button id="m2c-validate" class="dhl-btn dhl-btn--ghost">&#9989; Validate</button>
    </div>
    ${proposals.map((p) => `<div class="dhl-gate dhl-gate--show ccre-gap">
      <div class="dhl-gate__head"><span class="dhl-gate__title">AI proposal — ${esc(p.rationale || '')}</span>
      <span class="dhl-val-chip dhl-val-chip--warn">not applied</span></div>
      ${table(['Country', 'Group', 'Shipment', 'Value band', 'Other Logic', 'Rationale'], (p.payload.rules || []).map((r) =>
        `<tr><td>${esc(r.ctry_cd)}</td><td>${esc(r.sirg_cd || '—')}</td><td>${esc(r.shipment_type || '—')}</td>
         <td>${esc(r.min_value ?? '—')}–${esc(r.max_value ?? '—')}</td><td class="ccre-mono">${esc(r.other_logic || '—')}</td><td>${esc(r.rationale || '')}</td></tr>`))}
      ${(p.payload.open_questions || []).length ? `<h4>Open questions</h4>${list(p.payload.open_questions, 'ccre-warn')}` : ''}
      ${canEdit ? `<div class="dhl-gate__actions"><button class="dhl-btn dhl-btn--primary" data-accept="${esc(p.id)}">&#10003; Accept into M2C</button>
        <button class="dhl-btn dhl-btn--ghost" data-reject="${esc(p.id)}">&#10006; Reject</button></div>` : ''}
    </div>`).join('')}
    <h4>M2C rows — ${esc(m.rule_set.label || m.rule_set.version)}</h4>
    ${table(['Row', 'Group', 'Shipment', 'Currency', 'Value band', 'Other Logic', 'Definitions'], m.rules.map((r) => `<tr>
      <td>${esc(r.row_no ?? '')}</td><td>${esc(r.sirg_cd || '—')}</td><td>${esc(r.shipment_type || '—')}</td><td>${esc(r.currency || '—')}</td>
      <td>${esc(r.min_value ?? '—')}–${esc(r.max_value ?? '—')}</td><td class="ccre-mono">${esc(r.other_logic || '—')}</td>
      <td>${esc(r.bindings.map((b) => b.cmpt_nm || b.sir_id || '').filter(Boolean).join(', ') || '—')}</td></tr>`))}
    <div id="m2c-report"></div>`;
  el.innerHTML = html;
  if ($('m2c-draft')) {
    $('m2c-draft').onclick = () => run('AI draft', async () => {
      await api('POST', `/api/onboardings/${S.caseId}/m2c/draft`, { notes: $('m2c-notes').value });
      toast('AI proposal staged — review it below.');
      await renderStage();
    });
  }
  $('m2c-validate').onclick = () => run('Validate', async () => {
    const rep = await api('POST', `/api/onboardings/${S.caseId}/m2c/validate`);
    $('m2c-report').innerHTML = `<h4>Validation</h4>${findingsHtml(rep)}`;
  });
  const decide = (id, accept) => run(accept ? 'Accept' : 'Reject', async () => {
    const res = await api('POST', `/api/proposals/${id}/decide`, { accept, actor: S.me.name, rule_set_id: m.rule_set.id });
    toast(accept ? `${res.rules_created.length} row(s) written; validation ran.` : 'Proposal rejected.');
    await refreshCase();
  });
  el.querySelectorAll('[data-accept]').forEach((b) => { b.onclick = () => decide(b.dataset.accept, true); });
  el.querySelectorAll('[data-reject]').forEach((b) => { b.onclick = () => decide(b.dataset.reject, false); });
}

// ── 4. Sanity check ──────────────────────────────────────────
async function renderSanity(el) {
  if (isBusiness()) return businessWaiting(el, 'The CCRE team is checking the configuration before testing starts.');
  const g = S.overview.gates || {};
  el.innerHTML = `<h3>Sanity check</h3>
    <p>The deterministic validator and the config package must both be clean before UAT preparation. Blockers cannot be waived.</p>
    ${kv([['Validation', g.validation_clean ? 'clean' : 'blockers present'],
      ['Config package', g.package_complete ? 'covers every referenced requirement' : 'incomplete — Support rebuild needed']])}
    <button id="sanity-run" class="dhl-btn dhl-btn--primary ccre-gap">Run validation</button><div id="sanity-report"></div>`;
  $('sanity-run').onclick = () => run('Validate', async () => {
    const rep = await api('POST', `/api/onboardings/${S.caseId}/m2c/validate`);
    $('sanity-report').innerHTML = findingsHtml(rep);
  });
}

// ── 5/6. UAT test cases ──────────────────────────────────────
async function renderTestCases(el) {
  const cases = await api('GET', `/api/onboardings/${S.caseId}/uat/test-cases`);
  const st = state();
  if (isBusiness()) {
    if (!cases.length) return businessWaiting(el, 'Test cases will be shared with you for review once the CCRE team has prepared and reviewed them.');
    const canReview = st === 'UAT_TC_REVIEW_BUSINESS';
    el.innerHTML = `<h3>UAT test cases for your review</h3>
      <p>${canReview ? 'Approve the set with the button above, or reject individual cases with a comment and return them.' : 'Read-only.'}</p>
      ${table(['Test', 'What is tested', 'Expected outcome', 'Status', ''], cases.map((c) => `<tr>
        <td class="ccre-mono">${esc(c.test_id)}</td><td>${esc(c.business_summary)}</td>
        <td>${c.expected_case_created ? `${esc(c.expected_requirement || '')} is requested` : `${esc(c.expected_requirement || 'Nothing')} is not requested`}</td>
        <td>${esc(c.status)}${c.review_comment ? `<div class="ccre-hint">${esc(c.review_comment)}</div>` : ''}</td>
        <td>${canReview && c.status !== 'REJECTED' ? `<button class="dhl-btn dhl-btn--ghost dhl-btn--sm" data-rej="${esc(c.id)}">Reject</button>` : ''}</td></tr>`))}`;
  } else {
    const canGenerate = ['RULE_CONFIG', 'SANITY_CHECK', 'UAT_TC_PREP'].includes(st) && hasRole(...CCRE);
    const canReview = ['UAT_TC_PREP', 'UAT_TC_REVIEW_CCRE'].includes(st) && hasRole(...CCRE);
    el.innerHTML = `<h3>UAT test cases</h3>
      <p class="ccre-hint">Written from the M2C draft. Preparation may start while the M2C is being finalised; the CCRE team reviews first, then the business team.</p>
      ${canGenerate ? '<div class="ccre-row ccre-gap"><input id="tc-notes" class="dhl-input" placeholder="Notes for the AI test designer (optional)"><button id="tc-gen" class="dhl-btn dhl-btn--primary">&#129514; Generate test cases (AI)</button></div>' : ''}
      ${table(['Test', 'Kind', 'Business summary', 'Inputs', 'Expected', 'Status', ''], cases.map((c) => `<tr>
        <td class="ccre-mono">${esc(c.test_id)}</td><td>${esc(c.kind)}</td><td>${esc(c.business_summary)}</td>
        <td>${esc((c.input_conditions || []).map(cond).join('; '))}</td>
        <td>${esc(c.expected_requirement || 'none')} · ${c.expected_case_created ? 'raised' : 'not raised'}</td>
        <td>${esc(c.status)}${c.review_comment ? `<div class="ccre-hint">${esc(c.review_comment)}</div>` : ''}</td>
        <td>${canReview ? (c.status === 'REJECTED'
          ? `<button class="dhl-btn dhl-btn--ghost dhl-btn--sm" data-restore="${esc(c.id)}">Restore</button>`
          : `<button class="dhl-btn dhl-btn--ghost dhl-btn--sm" data-rej="${esc(c.id)}">Reject</button>`) : ''}</td></tr>`))}`;
  }
  if ($('tc-gen')) {
    $('tc-gen').onclick = () => run('Generate test cases', async () => {
      const res = await api('POST', `/api/onboardings/${S.caseId}/uat/test-cases/generate`, { notes: $('tc-notes').value });
      toast(`${res.length} test case(s) generated.`);
      await refreshCase();
    });
  }
  el.querySelectorAll('[data-rej]').forEach((b) => {
    b.onclick = () => run('Reject test case', async () => {
      const v = await dialog('Reject test case', `<label class="ccre-field-label">Why? (required)</label>
        <textarea class="dhl-textarea ccre-small" name="comment" required></textarea>`, 'Reject');
      if (!v) return;
      await api('PATCH', `/api/uat/test-cases/${b.dataset.rej}`, { status: 'REJECTED', comment: v.comment });
      await renderStage();
    });
  });
  el.querySelectorAll('[data-restore]').forEach((b) => {
    b.onclick = () => run('Restore', async () => {
      await api('PATCH', `/api/uat/test-cases/${b.dataset.restore}`, { status: 'DRAFT' });
      await renderStage();
    });
  });
}

// ── 7. UAT execution ─────────────────────────────────────────
function resultRows(results, analyse) {
  return results.map((r) => `<tr>
    <td class="ccre-mono">${esc(r.test_id)}</td>
    <td><span class="ccre-verdict ccre-verdict--${esc(r.verdict)}">${esc(r.verdict)}</span>
      <div class="ccre-hint">${esc(r.verdict_source === 'ai' ? 'decided by AI reviewer' : 'decided by code')}</div></td>
    <td>${esc((r.check && r.check.reasons || []).join(' '))}<div class="ccre-hint">${esc(r.business_explanation || '')}</div>
      ${r.error ? `<div class="ccre-inline-error">${esc(r.error)}</div>` : ''}
      ${r.analysis ? `<div class="ccre-card ccre-gap"><strong>Failure analysis</strong> — ${esc(r.analysis.category)} (${esc(r.analysis.confidence)})
        <p>${esc(r.analysis.likely_cause)}</p><p><strong>Next:</strong> ${esc(r.analysis.recommended_action)}</p>
        <p class="ccre-hint">Rule change suggested: ${r.analysis.change_rules ? 'yes' : 'no'}</p></div>` : ''}</td>
    <td><details class="ccre-details"><summary>payload &amp; response</summary>
      <h4>Changes from the sample</h4>${list((r.changes || []).map((c) => `${c.path} = ${JSON.stringify(c.value)} (${c.reason || ''})`))}
      <h4>Payload</h4>${pre(r.payload)}<h4>Response (HTTP ${esc(r.response_status ?? '—')}, ${esc(r.latency_ms ?? '—')} ms)</h4>${pre(r.response_body)}
      <h4>AI review</h4>${list((r.review && r.review.reasons) || [])}</details>
      ${analyse && r.verdict !== 'PASS' && !r.analysis ? `<button class="dhl-btn dhl-btn--ghost dhl-btn--sm ccre-gap" data-analyse="${esc(r.id)}">Analyse failure (AI)</button>` : ''}</td>
  </tr>`);
}

function runsHtml(runs, analyse) {
  if (!runs.length) return '<p class="ccre-hint">No UAT run yet.</p>';
  return runs.map((r) => `<div class="ccre-card"><div class="ccre-row ccre-space">
      <strong>Cycle ${r.cycle} · ${esc(r.executor)} executor</strong>
      <span><span class="ccre-verdict ccre-verdict--PASS">${r.passed} passed</span> ·
        <span class="ccre-verdict ccre-verdict--FAIL">${r.failed} failed</span> · ${r.errors} errors</span></div>
      ${table(['Test', 'Verdict', 'Why', 'Evidence'], resultRows(r.results, analyse))}</div>`).join('');
}

function wireAnalyse(el) {
  el.querySelectorAll('[data-analyse]').forEach((b) => {
    b.onclick = () => run('Failure analysis', async () => {
      await api('POST', `/api/uat/results/${b.dataset.analyse}/analyse`);
      await renderStage();
    });
  });
}

async function renderExecution(el) {
  if (isBusiness()) return businessWaiting(el, 'The CCRE team is executing the approved test cases.');
  const [templates, runs] = await Promise.all([api('GET', '/api/uat/templates'),
    api('GET', `/api/onboardings/${S.caseId}/uat/runs`)]);
  const canRun = state() === 'UAT_EXECUTION' && hasRole(...CCRE);
  el.innerHTML = `<h3>UAT execution</h3>
    <p class="ccre-hint">For each approved test case the AI adapts the sample payload, the executor calls the endpoint, the response is checked by code and reviewed by AI.</p>
    <div class="ccre-card"><strong>Sample payloads</strong>
      <div class="ccre-row ccre-gap"><select id="tpl" class="dhl-input">${templates.map((t) =>
        `<option value="${esc(t.id)}" ${t.country === S.overview.country ? 'selected' : ''}>${esc(t.name)}${t.country ? ' · ' + esc(t.country) : ''}</option>`).join('')}</select>
        ${canRun ? '<button id="run-uat" class="dhl-btn dhl-btn--primary">&#9654; Run UAT</button>' : ''}</div>
      ${hasRole(...CCRE) ? `<details class="ccre-details ccre-gap"><summary>Add your sample payload</summary>
        <form id="tpl-form"><div class="ccre-row ccre-gap"><input name="name" class="dhl-input" placeholder="Name" required>
          <input name="country" class="dhl-input ccre-narrow" maxlength="2" placeholder="CC"></div>
          <textarea name="body" class="dhl-textarea ccre-req ccre-gap" placeholder='{"shipmentId": "...", ...}' required></textarea>
          <button class="dhl-btn dhl-btn--ghost ccre-gap" type="submit">Save sample payload</button></form></details>` : ''}
      <details class="ccre-details ccre-gap"><summary>View selected payload</summary><div id="tpl-view"></div></details>
    </div>
    <h4>Runs</h4>${runsHtml(runs, hasRole(...CCRE))}`;
  const showTpl = () => {
    const t = templates.find((x) => x.id === $('tpl').value);
    $('tpl-view').innerHTML = t ? pre(t.body) + (t.notes ? `<p class="ccre-hint">${esc(t.notes)}</p>` : '') : '';
  };
  if ($('tpl')) { $('tpl').onchange = showTpl; showTpl(); }
  if ($('run-uat')) {
    $('run-uat').onclick = () => run('UAT run', async () => {
      $('run-uat').disabled = true;
      $('run-uat').textContent = 'Running…';
      const res = await api('POST', `/api/onboardings/${S.caseId}/uat/runs`, { template_id: $('tpl').value });
      toast(`UAT finished: ${res.run.passed} passed, ${res.run.failed} failed, ${res.run.errors} errors.`);
      await refreshCase();
    });
  }
  if ($('tpl-form')) {
    $('tpl-form').onsubmit = (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      run('Save sample payload', async () => {
        await api('POST', '/api/uat/templates', { name: f.get('name'), country: f.get('country') || null, body: f.get('body') });
        toast('Sample payload saved.');
        await renderStage();
      });
    };
  }
  wireAnalyse(el);
}

// ── 8. UAT review + sign-off ─────────────────────────────────
async function renderResults(el) {
  const runs = await api('GET', `/api/onboardings/${S.caseId}/uat/runs`);
  if (isBusiness()) {
    if (!runs.length) return businessWaiting(el, 'The results will be shared with you after the CCRE team has reviewed them.');
    const r = runs[0];
    el.innerHTML = `<h3>UAT results for your sign-off</h3>
      <p>${r.passed} of ${r.results.length} test cases behaved as expected. Sign off with the button above, or reject with a reason.</p>
      ${table(['Test', 'What was tested', 'Result', 'Explanation'], r.results.map((x) => `<tr><td class="ccre-mono">${esc(x.test_id)}</td>
        <td>${esc(x.business_summary || '')}</td><td><span class="ccre-verdict ccre-verdict--${esc(x.verdict)}">${esc(x.verdict)}</span></td>
        <td>${esc(x.business_explanation || '')}</td></tr>`))}`;
    return;
  }
  el.innerHTML = `<h3>UAT review and sign-off</h3>
    <p class="ccre-hint">The CCRE team reviews first. Failures → analyse → “Failures found — correct the M2C” restarts the cycle at rule config. All passed → CCRE accepts → business signs off.</p>
    ${runsHtml(runs.slice(0, 1), hasRole(...CCRE))}
    ${runs.length > 1 ? `<details class="ccre-details"><summary>Earlier cycles (${runs.length - 1})</summary>${runsHtml(runs.slice(1), false)}</details>` : ''}`;
  wireAnalyse(el);
}

// ── 9. RTP ───────────────────────────────────────────────────
async function renderRtp(el) {
  const o = S.overview;
  if (isBusiness()) {
    el.innerHTML = `<h3>Go-live</h3>${kv([['Status', o.state_label], ['Planned go-live', o.planned_rtp]])}
      <p class="ccre-hint">${o.state === 'COMPLETED' ? 'The requirement is live in production.' : 'The CCRE team and Support are releasing the configuration.'}</p>`;
    return;
  }
  el.innerHTML = `<h3>RTP — ready to production</h3>
    <p>Support uploads the export bundle to CCRE; the platform never uploads itself. Confirm the upload with the action above.</p>
    ${o.m2c ? '<button id="rtp-export" class="dhl-btn dhl-btn--primary">&#128230; Build export bundle</button>' : '<p class="ccre-hint">No M2C draft.</p>'}
    <div id="rtp-files"></div>`;
  if ($('rtp-export')) {
    $('rtp-export').onclick = () => run('Export', async () => {
      const res = await api('GET', `/api/rule-sets/${o.m2c.rule_set_id}/export`);
      $('rtp-files').innerHTML = `<p>${esc(res.handover_note)}</p>` + Object.entries(res.files).map(([n, b]) =>
        `<div class="ccre-card"><div class="ccre-file__name">${esc(n)}</div>${pre(b)}</div>`).join('');
    });
  }
}

// ── KPIs ─────────────────────────────────────────────────────
async function renderKpis() {
  const k = await api('GET', '/api/kpis');
  const fmt = (v, unit) => (v === null || v === undefined ? '—' : `${v}${unit || ''}`);
  const labels = {
    onboardings: ['Onboardings', ''], completed: ['Completed', ''], avg_lead_time_days: ['Avg lead time', ' d'],
    schedule_on_time_pct: ['Milestones on time', '%'], avg_milestone_slip_working_days: ['Avg milestone slip', ' wd'],
    m2c_first_time_right_pct: ['M2C first-time-right', '%'], avg_correction_cycles: ['Avg UAT cycles', ''],
    first_run_pass_rate_pct: ['First-run pass rate', '%'], rule_coverage_pct: ['Rule coverage', '%'],
    defects_found_by_ccre: ['Defects found by CCRE', ''], defects_found_by_business: ['Defects found by business', ''],
    avg_review_wait_days: ['Avg review wait', ' d'],
  };
  $('kpi-cards').innerHTML = Object.entries(labels).map(([key, [label, unit]]) => `<div class="ccre-kpi">
    <div class="ccre-kpi__value">${esc(fmt(k.summary[key], unit))}</div><div class="ccre-kpi__label">${esc(label)}</div>
    <div class="ccre-kpi__def">${esc(k.definitions[key] || '')}</div></div>`).join('');
  $('kpi-detail').innerHTML = `
    <h4>Onboardings</h4>${table(['Code', 'Country', 'Status', 'UAT cycles', 'First-run pass', 'Rule coverage', 'Last milestone slip', 'Planned RTP'],
      k.cases.map((c) => `<tr><td>${esc(c.code)}</td><td>${esc(c.country)}</td><td>${esc(c.state_label)}</td><td>${esc(c.cycles)}</td>
      <td>${esc(fmt(c.first_run_pass_rate, '%'))}</td><td>${esc(fmt(c.rule_coverage_pct, '%'))}</td>
      <td>${esc(fmt(c.latest_milestone_slip_days, ' wd'))}</td><td>${esc(c.planned_rtp || '—')}</td></tr>`))}
    <div class="ccre-grid2 ccre-gap">
      <div><h4>By stage</h4>${table(['Stage', 'Onboardings'], Object.entries(k.by_stage).map(([s, n]) => `<tr><td>${esc(s)}</td><td>${n}</td></tr>`))}</div>
      <div><h4>Average days in each state</h4>${table(['State', 'Days'], Object.entries(k.avg_days_in_state).map(([s, n]) => `<tr><td>${esc(s)}</td><td>${esc(fmt(n))}</td></tr>`))}</div>
    </div>`;
}

// ── Admin ────────────────────────────────────────────────────
async function renderAdmin() {
  const [roles, users] = await Promise.all([api('GET', '/api/admin/roles'), api('GET', '/api/admin/users')]);
  $('role-help').innerHTML = Object.entries(roles).map(([r, d]) => `<div><strong>${esc(r.replace('_', ' '))}</strong><br>${esc(d)}</div>`).join('');
  const roleOptions = (sel) => Object.keys(roles).map((r) => `<option ${r === sel ? 'selected' : ''}>${r}</option>`).join('');
  $('user-table').innerHTML = table(['Name', 'Email', 'Role', 'Countries', 'Active', 'Last sign-in', ''], users.map((u) => `<tr data-user="${esc(u.id)}">
    <td>${esc(u.name)}</td><td>${esc(u.email)}</td>
    <td><select class="dhl-input" data-f="role">${roleOptions(u.role)}</select></td>
    <td><input class="dhl-input" data-f="countries" value="${esc(u.countries.join(', '))}" placeholder="—"></td>
    <td><input type="checkbox" data-f="active" ${u.active ? 'checked' : ''}></td>
    <td>${esc(u.last_login_at ? u.last_login_at.slice(0, 16).replace('T', ' ') : '—')}</td>
    <td><button class="dhl-btn dhl-btn--primary dhl-btn--sm" data-save>Save</button>
        <button class="dhl-btn dhl-btn--ghost dhl-btn--sm" data-reset>Reset password</button></td></tr>`));
  $('user-table').querySelectorAll('tr[data-user]').forEach((tr) => {
    const id = tr.dataset.user;
    tr.querySelector('[data-save]').onclick = () => run('Save user', async () => {
      await api('PATCH', `/api/admin/users/${id}`, {
        role: tr.querySelector('[data-f="role"]').value,
        countries: tr.querySelector('[data-f="countries"]').value.split(/[,\s]+/).filter(Boolean),
        active: tr.querySelector('[data-f="active"]').checked,
      });
      toast('User updated.');
      await renderAdmin();
    });
    tr.querySelector('[data-reset]').onclick = () => run('Reset password', async () => {
      const v = await dialog('Reset password', `<label class="ccre-field-label">New password (8+ characters)</label>
        <input class="dhl-input" type="password" name="pw" minlength="8" required>`, 'Reset');
      if (!v) return;
      await api('POST', `/api/admin/users/${id}/reset-password`, { new_password: v.pw });
      toast('Password reset.');
    });
  });
}

$('user-form').onsubmit = (e) => {
  e.preventDefault();
  run('Add user', async () => {
    await api('POST', '/api/admin/users', {
      name: $('u-name').value, email: $('u-email').value, role: $('u-role').value, password: $('u-password').value,
      countries: $('u-countries').value.split(/[,\s]+/).filter(Boolean),
    });
    ['u-name', 'u-email', 'u-password', 'u-countries'].forEach((id) => { $(id).value = ''; });
    toast('User added.');
    await renderAdmin();
  });
};

// ── Ask Expert (internal) ────────────────────────────────────
function chatMarkup(text) {
  const parts = String(text).split(/```(?:\w+)?\n?([\s\S]*?)```/g);
  return parts.map((p, i) => (i % 2 === 1 ? `<pre class="ccre-chat-pre">${esc(p)}</pre>`
    : esc(p).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>'))).join('');
}
function addChat(who, text, thinking) {
  const box = $('chat-popup-msgs');
  const welcome = box.querySelector('.dhl-chat-welcome');
  if (welcome) welcome.remove();
  const div = document.createElement('div');
  div.className = `dhl-chat-msg dhl-chat-msg--${who}${thinking ? ' dhl-chat-msg--thinking' : ''}`;
  div.innerHTML = `<div class="dhl-chat-msg__label">${who === 'user' ? 'You' : 'CCRE Expert'}</div>
    <div class="dhl-chat-msg__bubble">${who === 'user' ? esc(text) : chatMarkup(text)}</div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}
async function sendChat(message) {
  if (!message) return;
  $('chat-input').value = '';
  addChat('user', message);
  const pending = addChat('agent', 'Thinking…', true);
  try {
    const res = await api('POST', '/api/run', { message });
    pending.remove();
    addChat('agent', res.response || '(no reply)');
  } catch (err) {
    pending.remove();
    addChat('agent', `⚠️ ${err.message}`);
  }
}
$('btn-chat-toggle').onclick = () => $('chat-popup').classList.toggle('dhl-chat-popup--open');
$('btn-chat-close').onclick = () => $('chat-popup').classList.remove('dhl-chat-popup--open');
$('btn-chat-send').onclick = () => sendChat($('chat-input').value.trim());
$('chat-input').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat($('chat-input').value.trim()); } };
document.querySelectorAll('.dhl-suggestion').forEach((b) => { b.onclick = () => sendChat(b.dataset.query); });

// ── boot ─────────────────────────────────────────────────────
(async function boot() {
  try {
    await enterApp();
  } catch {
    showLogin();
  }
})();
