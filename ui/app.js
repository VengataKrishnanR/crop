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
  intakeTab: 'form',
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
      $('dialog-body').querySelectorAll('[name]').forEach((f) => {
        if (f.type !== 'checkbox') { values[f.name] = f.value; return; }
        // A tick box without a value is yes/no; a group of boxes with values gives the ticked values.
        if (f.hasAttribute('value')) { (values[f.name] = values[f.name] || []); if (f.checked) values[f.name].push(f.value); }
        else values[f.name] = f.checked;
      });
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
  ['onboardings', 'kpis', 'reference', 'admin'].forEach((v) => { $(`view-${v}`).hidden = v !== view; });
  document.querySelectorAll('.ccre-nav__item').forEach((b) =>
    b.classList.toggle('ccre-nav__item--active', b.dataset.view === view));
  if (view === 'kpis') run('KPIs', renderKpis);
  if (view === 'reference') run('Reference', renderReference);
  if (view === 'admin') run('Admin', async () => { await renderPackages(); await renderAdmin(); await renderEndpoints(); await renderMail(); });
}
document.querySelectorAll('.ccre-nav__item').forEach((b) => { b.onclick = () => switchView(b.dataset.view); });

// ── onboarding list ──────────────────────────────────────────
async function loadCases(selectId) {
  S.cases = await api('GET', '/api/onboardings');
  const sel = $('case-select');
  sel.innerHTML = (S.cases.length ? '<option value="">— choose an onboarding —</option>' : '<option value="">No onboardings yet</option>')
    + S.cases.map((c) => `<option value="${esc(c.id)}">${esc(c.country)} · ${esc(c.title)} — ${esc(c.code)} — ${esc(c.state_label)}</option>`).join('');
  sel.onchange = () => { if (sel.value) openCase(sel.value); else { S.caseId = null; $('case-view').hidden = true; $('case-empty').hidden = false; } };
  $('btn-new').hidden = hasRole('PM');
  let target = selectId || S.caseId;
  if (!target && S.cases.length === 1) target = S.cases[0].id;
  if (target && S.cases.some((c) => c.id === target)) { sel.value = target; await openCase(target, true); }
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
    S.intakeTab = 'form';
    await loadCases(created.id);
  });
};

// ── case workspace ───────────────────────────────────────────
async function openCase(id, keepStage) {
  const changed = id !== S.caseId;
  if (S.caseId !== id) { S.rcOpen = null; S.rcTab = null; }
  S.caseId = id;
  S.overview = await api('GET', `/api/onboardings/${id}`);
  if (changed || !keepStage) S.viewStage = S.overview.stage;
  $('case-select').value = id;
  $('case-empty').hidden = true;
  $('case-view').hidden = false;
  renderCaseHead();
  renderStepper();
  renderWaiting();
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

// Horizontal flow: every stage with its status — Completed / In progress / Not yet started.
function renderStepper() {
  const stages = visibleStages();
  const order = S.meta.stages.map((s) => s.key);
  const current = order.indexOf(S.overview.stage);
  const finished = S.overview.state === 'COMPLETED';
  const withdrawn = S.overview.state === 'WITHDRAWN';
  $('stepper').innerHTML = stages.map((s, i) => {
    const last = Math.max(...s.keys.map((k) => order.indexOf(k)));
    const first = Math.min(...s.keys.map((k) => order.indexOf(k)));
    let status = 'todo'; let text = 'Not yet started';
    if (finished || last < current) { status = 'done'; text = 'Completed'; }
    else if (!withdrawn && current >= first && current <= last) { status = 'active'; text = 'In progress'; }
    else if (withdrawn && current >= first && current <= last) { text = 'Withdrawn'; }
    const viewing = s.keys.includes(S.viewStage) ? ' ccre-flow__step--viewing' : '';
    const target = s.keys.includes(S.overview.stage) ? S.overview.stage : s.key;
    return `${i ? '<div class="ccre-flow__arrow">&#10140;</div>' : ''}
      <button class="ccre-flow__step ccre-flow__step--${status}${viewing}" data-stage="${esc(target)}">
        <span class="ccre-flow__num">STEP ${i + 1}</span>
        <span class="ccre-flow__label">${esc(s.label)}</span>
        <span class="ccre-flow__status"><span class="ccre-flow__dot"></span>${esc(text)}</span>
      </button>`;
  }).join('');
  $('stepper').querySelectorAll('.ccre-flow__step').forEach((b) => {
    b.onclick = () => { S.viewStage = b.dataset.stage; renderStepper(); renderStage(); };
  });
}

// Banner for users who cannot act at this step, with a reminder email button.
function renderWaiting() {
  const w = S.overview.waiting;
  const el = $('waiting-banner');
  if (!w || w.can_act) { el.hidden = true; el.innerHTML = ''; return; }
  el.hidden = false;
  el.innerHTML = `<div><strong>&#9203; ${esc(w.message)}</strong>
      ${w.last_reminder_at ? `<div class="ccre-hint">Last reminder sent ${esc(w.last_reminder_at.slice(0, 16).replace('T', ' '))}</div>` : ''}</div>
    <button id="btn-remind" class="dhl-btn dhl-btn--primary dhl-btn--sm">&#9993; Send reminder email</button>`;
  $('btn-remind').onclick = () => run('Reminder', async () => {
    const v = await dialog('Send a reminder email', `<p class="ccre-hint">The people who must approve receive it; every other user involved in this onboarding is in CC.</p>
      <label class="ccre-field-label">Message (optional)</label><textarea class="dhl-textarea ccre-small" name="message"></textarea>`, 'Send');
    if (!v) return;
    const res = await api('POST', `/api/onboardings/${S.caseId}/remind`, { message: v.message || null });
    toast(`Reminder ${res.status === 'SENT' ? 'sent' : res.status === 'OUTBOX' ? 'written to the outbox' : 'failed'} — to ${res.to.join(', ')}${res.cc.length ? `, cc ${res.cc.length} user(s)` : ''}.`, res.status === 'FAILED');
    await refreshCase();
  });
}

// Approve / Reject at every stage. Reject always asks for the reason.
function renderActions() {
  const acts = (S.overview.actions || []).filter((a) => a.mine);
  const order = { submit: 0, approve: 1, reject: 2 };
  acts.sort((a, b) => (order[a.kind] ?? 3) - (order[b.kind] ?? 3));
  $('actions').innerHTML = acts.map((a) => {
    const cls = a.kind === 'approve' ? 'dhl-btn--primary ccre-act--approve' : a.kind === 'reject' ? 'dhl-btn--ghost ccre-act--reject' : 'dhl-btn--primary';
    const icon = a.kind === 'approve' ? '&#10003; ' : a.kind === 'reject' ? '&#10005; ' : '';
    return `<div class="ccre-action">
      <button class="dhl-btn ${cls} dhl-btn--sm" data-act="${esc(a.name)}" data-kind="${esc(a.kind)}" ${a.allowed ? '' : 'disabled'}>${icon}${esc(a.label)}</button>
      ${a.allowed ? '' : `<div class="ccre-action__why">${esc(a.blocked_by.join(' '))}</div>`}
    </div>`;
  }).join('');
  $('actions').querySelectorAll('[data-act]').forEach((b) => {
    b.onclick = () => doTransition(b.dataset.act, b.dataset.kind, b.textContent.trim());
  });
}

function doTransition(name, kind, label) {
  return run('Action', async () => {
    let comment = null;
    if (kind === 'reject') {
      const v = await dialog(label, `<label class="ccre-field-label">Reason for rejecting (required — shared with the team and kept on the audit trail)</label>
        <textarea class="dhl-textarea ccre-small" name="comment" required></textarea>`, 'Reject');
      if (!v) return;
      comment = v.comment;
    } else if (kind === 'approve') {
      const v = await dialog(label, `<label class="ccre-field-label">Comment (optional)</label>
        <textarea class="dhl-textarea ccre-small" name="comment"></textarea>`, 'Approve');
      if (!v) return;
      comment = v.comment || null;
    }
    await api('POST', `/api/onboardings/${S.caseId}/transition`, { name, comment });
    toast(`Done: ${label}`);
    S.viewStage = null;
    await refreshCase();
  });
}

// A "next step" call-out inside a stage panel, for the person who owns that step.
function nextStep(name, text) {
  const a = (S.overview.actions || []).find((x) => x.name === name && x.mine);
  if (!a) return '';
  return `<div class="ccre-next"><div><strong>Next step:</strong> ${esc(text)}
      ${a.allowed ? '' : `<div class="ccre-hint">${esc(a.blocked_by.join(' '))}</div>`}</div>
    <button class="dhl-btn dhl-btn--primary" data-next="${esc(a.name)}" data-kind="${esc(a.kind)}" ${a.allowed ? '' : 'disabled'}>${esc(a.label)}</button></div>`;
}

function wireNextStep(el) {
  el.querySelectorAll('[data-next]').forEach((b) => {
    b.onclick = () => doTransition(b.dataset.next, b.dataset.kind, b.textContent.trim());
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
// The M2C criteria of a requirement, as a table (used wherever the requirement is shown).
function m2cTable(r) {
  const view = r.m2c_view || [];
  if (!view.length) return '<p class="ccre-hint">No M2C criteria captured (requirement from before the M2C intake).</p>';
  const chk = r.m2c_check || {};
  const missing = new Set((chk.missing || []).map((m) => m.field));
  const errors = chk.errors || {};
  const warnings = chk.warnings || {};
  const row = r.m2c_row || {};
  const m2cVal = { min_value: row.min_value, max_value: row.max_value, min_weight: row.min_weight, max_weight: row.max_weight };
  return `<div class="ccre-table-wrap"><table class="dhl-table ccre-m2c-table"><thead><tr><th>M2C column</th><th>Requirement</th><th>Written in M2C as</th><th></th></tr></thead><tbody>
    ${view.map((v) => {
      const st = errors[v.key] ? ['ccre-st--err', errors[v.key]] : missing.has(v.key) ? ['ccre-st--err', 'Missing'] : warnings[v.key] ? ['ccre-st--warn', warnings[v.key]] : ['ccre-st--ok', '✓'];
      const asM2c = v.key in m2cVal ? (m2cVal[v.key] ?? '—') : '';
      return `<tr><td><b>${esc(v.label)}</b></td><td class="${v.key === 'other_logic' ? 'ccre-mono' : ''}">${esc(v.value)}</td>
        <td>${esc(asM2c)}</td><td><span class="ccre-st ${st[0]}">${esc(st[1])}</span></td></tr>`;
    }).join('')}</tbody></table></div>`;
}

function requirementCard(req) {
  if (!req) return '<p class="ccre-hint">No requirement captured yet.</p>';
  const r = req.structured || {};
  const chk = r.m2c_check || {};
  const status = !r.m2c_view ? '' : chk.complete
    ? '<span class="ccre-st ccre-st--ok">&#10003; Complete — ready to submit</span>'
    : `<span class="ccre-st ccre-st--err">${(chk.missing || []).length} missing · ${Object.keys(chk.errors || {}).length} not accepted</span>`;
  return `<div class="ccre-card">
    <div class="ccre-row ccre-space"><strong>Requirement v${req.version}</strong>
      <span>${status} <span class="dhl-val-chip">${esc(req.mode === 'CHAT' ? 'from chat' : 'from form + NLP')}</span></span></div>
    ${r.summary ? `<p>${esc(r.summary)}</p>` : ''}
    <h4>M2C criteria</h4>${m2cTable(r)}
    ${kv([['Requested go-live', r.requested_rtp], ['Business owner', r.business_owner]])}
    ${(r.ambiguities || []).length ? `<h4>Ambiguities</h4>${list(r.ambiguities, 'ccre-warn')}` : ''}
    <p class="ccre-hint">Captured by ${esc(req.created_by)}${req.text ? ` · <details class="ccre-details ccre-inline"><summary>original text</summary><pre class="ccre-pre">${esc(req.text)}</pre></details>` : ''}</p></div>`;
}

// ── Pick-lists: choose from the list; "Other…" only when the value is not there ──
const OTHER = '__other';

function pickHtml(key, options, value, { blank = '— choose —', allowOther = true, cls = '', labels = null, otherLabel = 'Other… (type it)' } = {}) {
  const opts = options || [];
  const isOther = value && !opts.includes(value);
  return `<span class="ccre-pick ${cls}" data-pick="${esc(key)}">
    <select class="dhl-select">${blank !== null ? `<option value="">${esc(blank)}</option>` : ''}${opts.map((o) =>
      `<option value="${esc(o)}" ${o === value ? 'selected' : ''}>${esc(labels && labels[o] ? labels[o] : o)}</option>`).join('')}${allowOther ? `<option value="${OTHER}" ${isOther ? 'selected' : ''}>${esc(otherLabel)}</option>` : ''}</select>
    <input class="dhl-input ccre-pick-other" placeholder="Type the value" value="${esc(isOther ? value : '')}" ${isOther ? '' : 'hidden'}></span>`;
}

function pickValue(wrap) {
  if (!wrap) return '';
  const sel = wrap.querySelector('select');
  if (sel.value === OTHER) return wrap.querySelector('.ccre-pick-other').value.trim().toUpperCase();
  return sel.value;
}

function wirePicks(root) {
  root.querySelectorAll('.ccre-pick').forEach((w) => {
    const sel = w.querySelector('select');
    const other = w.querySelector('.ccre-pick-other');
    sel.addEventListener('change', () => { other.hidden = sel.value !== OTHER; if (!other.hidden) other.focus(); });
  });
}

// Several values: chips + a pick-list to add more.
function multiHtml(key, options, values, pickOpts = {}) {
  return `<div class="ccre-multi" data-multi="${esc(key)}" data-values='${esc(JSON.stringify(values || []))}'>
    <div class="ccre-chips"></div>
    <div class="ccre-row ccre-multi-add">${pickHtml(`${key}__add`, options, '', { blank: '+ add…', ...pickOpts })}
      <button type="button" class="dhl-btn dhl-btn--ghost ccre-small-btn" data-multi-add>Add</button></div></div>`;
}

function multiValues(wrap) {
  try { return JSON.parse(wrap.dataset.values || '[]'); } catch { return []; }
}

function wireMulti(root, onChange) {
  root.querySelectorAll('.ccre-multi').forEach((w) => {
    const draw = () => {
      const vals = multiValues(w);
      w.querySelector('.ccre-chips').innerHTML = vals.length ? vals.map((v, i) =>
        `<span class="ccre-chip">${esc(v)}<button type="button" data-rm="${i}" title="Remove">&times;</button></span>`).join('')
        : '<span class="ccre-hint">Nothing chosen yet</span>';
      w.querySelectorAll('[data-rm]').forEach((b) => {
        b.onclick = () => { const v = multiValues(w); v.splice(+b.dataset.rm, 1); w.dataset.values = JSON.stringify(v); draw(); if (onChange) onChange(w, v); };
      });
    };
    const add = () => {
      const pick = w.querySelector('.ccre-pick');
      const raw = pickValue(pick);
      if (!raw) return;
      const v = multiValues(w);
      raw.split(/[,;\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean).forEach((x) => { if (!v.includes(x)) v.push(x); });
      w.dataset.values = JSON.stringify(v);
      pick.querySelector('select').value = '';
      pick.querySelector('.ccre-pick-other').value = '';
      pick.querySelector('.ccre-pick-other').hidden = true;
      draw();
      if (onChange) onChange(w, v);
    };
    w.querySelector('[data-multi-add]').onclick = add;
    // Choosing from the list adds straight away; "Other…" waits for the typed value + Add.
    if (!w.dataset.wired) {
      w.dataset.wired = '1';
      w.querySelector('.ccre-pick select').addEventListener('change', (e) => { if (e.target.value && e.target.value !== OTHER) add(); });
    }
    w.querySelector('.ccre-pick-other').onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } };
    draw();
  });
}

// ── The condition builder (value, weight, Other Logic) ───────
function condRowHtml(row, gi, ri, spec) {
  const f = spec.fields.find((x) => x.key === row.field) || spec.fields[0];
  const ops = f.ops.map(([k, l]) => `<option value="${k}" ${k === row.op ? 'selected' : ''}>${esc(l)}</option>`).join('');
  const id = `c${gi}_${ri}`;
  let value = '';
  if (f.kind === 'number') {
    const cur = f.unit === 'currency' ? pickHtml(`${id}_cur`, spec.currencies, row.currency || spec.defaultCurrency || '', { blank: 'currency', cls: 'ccre-pick--cur' }) : '<span class="ccre-unit">kg</span>';
    value = `<input type="number" step="any" min="0" class="dhl-input ccre-num" data-v="value" value="${row.value ?? ''}" placeholder="0.00">
      ${row.op === 'between' ? `<span class="ccre-and">and</span><input type="number" step="any" min="0" class="dhl-input ccre-num" data-v="value2" value="${row.value2 ?? ''}" placeholder="0.00">` : ''}${cur}`;
  } else if (f.kind === 'list') {
    value = multiHtml(id, spec.options[f.source] || [], row.values || []);
  } else if (f.kind === 'one') {
    value = pickHtml(`${id}_one`, spec.options[f.source] || [], (row.values || [])[0] || '');
  } else if (!(f.key === 'hs_code' && row.op === 'blank')) {
    value = `<input class="dhl-input ccre-grow ${f.key === 'custom' ? 'ccre-mono' : ''}" data-v="text" value="${esc((row.values || [])[0] || '')}" placeholder="${f.key === 'custom' ? 'expression, e.g. !serviceCodeList.contains(&quot;DD&quot;)' : 'HS code'}">`;
  }
  return `<div class="ccre-cond-row" data-g="${gi}" data-r="${ri}">
    <span class="ccre-cond-join">${ri > 0 ? 'or' : ''}</span>
    <select class="dhl-select ccre-cond-field" data-k="field">${spec.fields.map((x) => `<option value="${x.key}" ${x.key === f.key ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select>
    <select class="dhl-select ccre-cond-op" data-k="op">${ops}</select>
    <span class="ccre-cond-value">${value}</span>
    <span class="ccre-cond-btns"><button type="button" class="dhl-btn dhl-btn--ghost ccre-small-btn" data-k="and">AND</button>
    <button type="button" class="dhl-btn dhl-btn--ghost ccre-small-btn" data-k="or">OR</button>
    <button type="button" class="ccre-x" data-k="del" title="Remove">&#10005;</button></span></div>`;
}

function newCondRow(spec, field) {
  const f = spec.fields.find((x) => x.key === field) || spec.fields[0];
  return { field: f.key, op: f.ops[0][0], values: [], currency: f.unit === 'currency' ? spec.defaultCurrency || '' : undefined };
}

function renderBuilder(box, spec, onChange) {
  const groups = S.cond || [];
  box.innerHTML = `<div class="ccre-cond-head">${groups.length ? 'All of these conditions must be met' : 'No conditions yet'}</div>
    ${groups.map((g, gi) => `<div class="ccre-cond-group">${g.map((r, ri) => condRowHtml(r, gi, ri, spec)).join('')}</div>`).join('')}
    <div class="ccre-row ccre-wrap ccre-gap">
      <button type="button" class="dhl-btn dhl-btn--ghost" data-add-cond>+ Add condition</button>
      ${groups.length ? '' : `<label class="ccre-tick"><input type="checkbox" id="cond-none" ${S.condNone ? 'checked' : ''}> No conditions — it applies to every ${esc('shipment')} of this type, at any value and weight</label>`}
    </div>
    <div class="ccre-hint" id="cond-preview"></div><div class="ccre-field-msg" id="fm-conditions"></div>`;
  wirePicks(box);
  const rowOf = (el) => { const r = el.closest('.ccre-cond-row'); return [+r.dataset.g, +r.dataset.r]; };
  const redraw = () => { renderBuilder(box, spec, onChange); onChange(); };
  box.querySelector('[data-add-cond]').onclick = () => { S.cond = [...groups, [newCondRow(spec)]]; S.condNone = false; redraw(); };
  if ($('cond-none')) $('cond-none').onchange = (e) => { S.condNone = e.target.checked; onChange(); };
  box.querySelectorAll('.ccre-cond-row').forEach((rowEl) => {
    const [gi, ri] = rowOf(rowEl);
    const row = groups[gi][ri];
    rowEl.querySelector('[data-k=field]').onchange = (e) => { groups[gi][ri] = newCondRow(spec, e.target.value); redraw(); };
    rowEl.querySelector('[data-k=op]').onchange = (e) => { row.op = e.target.value; redraw(); };
    rowEl.querySelector('[data-k=and]').onclick = () => { groups.splice(gi + 1, 0, [newCondRow(spec)]); redraw(); };
    rowEl.querySelector('[data-k=or]').onclick = () => { groups[gi].splice(ri + 1, 0, newCondRow(spec, row.field)); redraw(); };
    rowEl.querySelector('[data-k=del]').onclick = () => {
      groups[gi].splice(ri, 1);
      if (!groups[gi].length) groups.splice(gi, 1);
      redraw();
    };
    rowEl.querySelectorAll('[data-v]').forEach((inp) => {
      inp.oninput = () => {
        if (inp.dataset.v === 'text') row.values = inp.value.trim() ? [inp.value.trim()] : [];
        else row[inp.dataset.v] = inp.value === '' ? null : Number(inp.value);
        onChange();
      };
    });
    const cur = rowEl.querySelector('.ccre-pick--cur');
    if (cur) {
      const upd = () => { row.currency = pickValue(cur); onChange(); };
      cur.querySelector('select').addEventListener('change', upd);
      cur.querySelector('.ccre-pick-other').oninput = upd;
    }
    const one = rowEl.querySelector('.ccre-cond-value > .ccre-pick');
    if (one && !cur) {
      const upd = () => { const v = pickValue(one); row.values = v ? [v] : []; onChange(); };
      one.querySelector('select').addEventListener('change', upd);
      one.querySelector('.ccre-pick-other').oninput = upd;
    }
  });
  wireMulti(box, (w, vals) => {
    const [gi, ri] = rowOf(w);
    groups[gi][ri].values = vals;
    onChange();
  });
}

// ── Requirement intake ───────────────────────────────────────
function collectIntake(form) {
  const m = {};
  const pick = (k) => pickValue(form.querySelector(`[data-pick="${k}"]`));
  if (pick('region')) m.region = pick('region');
  if (form.shipment_type.value) m.shipment_type = form.shipment_type.value;
  if (form.effective_date.value) m.effective_date = form.effective_date.value;
  if (form.no_expiry.checked) m.expiry_date = 'N/A'; else if (form.expiry_date.value) m.expiry_date = form.expiry_date.value;
  const npc = multiValues(form.querySelector('[data-multi="network_product_codes"]'));
  if (form.all_products.checked) m.network_product_codes = 'N/A'; else if (npc.length) m.network_product_codes = npc;
  const groups = multiValues(form.querySelector('[data-multi="requirement_groups"]'));
  if (groups.length) m.requirement_groups = groups;
  const rows = (S.cond || []).map((g) => g.filter((r) => r.field)).filter((g) => g.length);
  if (rows.length || S.condNone) m.conditions = rows;
  return m;
}

function showIntakeCheck(form, res, showMissing = true) {
  form.querySelectorAll('.ccre-field-msg').forEach((x) => { x.innerHTML = ''; });
  form.querySelectorAll('.ccre-m2c-field').forEach((x) => x.classList.remove('is-err', 'is-missing'));
  const condKeys = new Set(['min_value', 'max_value', 'min_weight', 'max_weight', 'value_basis', 'currency', 'other_logic']);
  const put = (k, html, cls) => {
    const key = condKeys.has(k) ? 'conditions' : k;
    const box = $(`fm-${key}`);
    if (!box) return;
    if (!box.innerHTML.includes(html)) box.innerHTML += `<div>${html}</div>`;
    if (cls && $(`mf-${key}`)) $(`mf-${key}`).classList.add(cls);
  };
  Object.entries(res.errors || {}).forEach(([k, msg]) => put(k, `<span class="ccre-err">&#10005; ${esc(msg)}</span>`, 'is-err'));
  Object.entries(res.warnings || {}).forEach(([k, msg]) => put(k, `<span class="ccre-warn-text">! ${esc(msg)}</span>`));
  // A fresh form is not shouted at: "needed" marks appear once the user starts.
  if (!showMissing) res = { ...res, missing: [] };
  const missingCond = (res.missing || []).filter((m) => condKeys.has(m.field));
  (res.missing || []).filter((m) => !condKeys.has(m.field)).forEach((m) => put(m.field, `<span class="ccre-err">Needed — ${esc(m.question)}</span>`, 'is-missing'));
  if (missingCond.length) put('conditions', '<span class="ccre-err">Needed — add the conditions (value, weight, other logic), or tick “No conditions”.</span>', 'is-missing');
  const row = res.m2c_row || {};
  const bits = [];
  if (row.min_value != null) bits.push(`Min value ${row.min_value}`);
  if (row.max_value != null) bits.push(`Max value ${row.max_value}`);
  if (row.value_basis) bits.push(row.value_basis);
  if (row.currency) bits.push(row.currency);
  if (row.min_weight != null) bits.push(`Min weight ${row.min_weight} kg`);
  if (row.max_weight != null) bits.push(`Max weight ${row.max_weight} kg`);
  if (row.other_logic) bits.push(`Other Logic: ${row.other_logic}`);
  if ($('cond-preview')) $('cond-preview').innerHTML = bits.length ? `<b>Written in the M2C as:</b> <span class="ccre-mono">${esc(bits.join(' · '))}</span>` : '';
  const n = (res.missing || []).length + Object.keys(res.errors || {}).length;
  $('m2c-status').innerHTML = n ? `<span class="ccre-st ccre-st--err">${(res.missing || []).length} to answer · ${Object.keys(res.errors || {}).length} not accepted</span>`
    : '<span class="ccre-st ccre-st--ok">&#10003; Complete</span>';
}

// What each requirement group asks for in this country — straight from the active config package.
function groupCatalogHtml(opts) {
  const det = opts.requirement_group_details || [];
  if (!opts.package_version) return '';
  if (!det.length) {
    return `<div class="ccre-inline-error">The active config package ${esc(opts.package_version)} has no requirement groups for ${esc(opts.country)} yet.
      A package change is needed before CCRE can raise anything here — the CCRE team requests it from Support.</div>`;
  }
  return `<details class="ccre-accept"><summary>&#128203; What each group asks for in ${esc(opts.country)} (config package ${esc(opts.package_version)})</summary>
    <div>${table(['Group', 'Definition (what is asked for)', 'Fields'], det.map((g) => `<tr><td><b>${esc(g.code)}</b><br>${esc(g.name)}</td>
      <td>${g.definitions.map((d) => `${esc(d.cmpt_nm || '')} — ${esc(d.name || d.sir_id)}`).join('<br>')}</td>
      <td>${g.definitions.map((d) => d.fields).join('<br>')}</td></tr>`))}</div></details>`;
}

function intakeFieldCard(key, label, required, accepted, control, wide) {
  return `<div class="ccre-m2c-field${wide ? ' ccre-span2' : ''}" id="mf-${key}">
    <label class="ccre-field-label">${esc(label)}${required ? ' *' : ''}</label>${control}
    <details class="ccre-accept"><summary>&#9432; Accepted values</summary><div>${esc(accepted)}</div></details>
    <div class="ccre-field-msg" id="fm-${key}"></div></div>`;
}

async function renderIntake(el) {
  const editable = state() === 'INTAKE' && hasRole('BUSINESS', 'CCRE_TEAM', 'CCRE_CONSULTANT', 'ADMIN');
  const [data, spec] = await Promise.all([api('GET', `/api/onboardings/${S.caseId}/intake`),
    editable ? api('GET', `/api/onboardings/${S.caseId}/intake/fields`) : Promise.resolve(null)]);
  const reviewNote = state() === 'REQUIREMENT_REVIEW'
    ? '<div class="dhl-gate__notice">The requirement is with the CCRE consultant for approval.</div>' : '';
  S.intakeTab = S.intakeTab || 'form';
  let input = '';
  let condSpec = null;
  if (editable) {
    input = `<div class="ccre-subtabs">
        <button class="dhl-tab ${S.intakeTab === 'form' ? 'dhl-tab--active' : ''}" data-tab="form">&#128221; Requirement form</button>
        <button class="dhl-tab ${S.intakeTab === 'chat' ? 'dhl-tab--active' : ''}" data-tab="chat">&#128172; Chat</button>
      </div>`;
    if (S.intakeTab === 'chat') {
      input += `<div class="ccre-intake-chat" id="intake-chat">${data.messages.length ? data.messages.map((m) =>
        `<div class="ccre-bubble ccre-bubble--${m.role}">${esc(m.text)}</div>`).join('')
        : '<div class="ccre-bubble ccre-bubble--assistant">Hi! Describe the customs requirement in your own words — who it applies to, what must be provided, from when, and any value, weight or other condition. I will ask for anything the M2C still needs, one question at a time.</div>'}</div>
        <div class="ccre-row ccre-gap"><textarea id="intake-msg" class="dhl-textarea ccre-small" placeholder="Type your answer…"></textarea>
        <button id="intake-send" class="dhl-btn dhl-btn--primary">Send</button></div>`;
    } else {
      const cur = spec.current || {};
      const opts = spec.options;
      const fs = Object.fromEntries(spec.fields.map((f) => [f.key, f]));
      const prev = (data.requirement || {}).structured || {};
      condSpec = { fields: spec.conditions.fields, options: spec.conditions.options,
        currencies: opts.currency_all, defaultCurrency: (opts.currency || []).includes('EUR') ? 'EUR' : '' };
      if (S.condCase !== S.caseId) { S.cond = JSON.parse(JSON.stringify(cur.conditions || [])); S.condNone = Array.isArray(cur.conditions) && !cur.conditions.length && !!data.requirement; S.condCase = S.caseId; }
      const npcNa = cur.network_product_codes === 'N/A';
      input += `<form id="intake-form" class="ccre-card" novalidate>
        <details class="ccre-details" ${data.requirement ? '' : 'open'}><summary>&#10024; Optional: describe it in your own words and let NLP fill the form</summary>
          <textarea name="description" class="dhl-textarea ccre-req" placeholder="e.g. BG consumer shipments must provide IOSS when SDT is present and no DD, declared value above 150 EUR, effective 15-11-2026, no expiry, all products.">${esc((data.requirement || {}).text || '')}</textarea>
          <button type="button" id="intake-nlp" class="dhl-btn dhl-btn--ghost ccre-gap">Fill the form from my text</button></details>
        <div class="ccre-row ccre-space ccre-gap"><h4>Who and when</h4><span id="m2c-status"></span></div>
        <div class="ccre-m2c-grid">
          ${intakeFieldCard('region', fs.region.label, true, fs.region.accepted, pickHtml('region', opts.region, cur.region || opts.region_default || ''))}
          ${intakeFieldCard('country', fs.country.label, true, fs.country.accepted, `<input class="dhl-input" value="${esc(opts.country)}" disabled>`)}
          ${intakeFieldCard('shipment_type', fs.shipment_type.label, true, fs.shipment_type.accepted,
            `<select name="shipment_type" class="dhl-select"><option value="">— choose —</option>${opts.shipment_type.map((o) => `<option ${o === cur.shipment_type ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`)}
          ${intakeFieldCard('effective_date', 'Effective date', true, fs.effective_date.accepted,
            `<input type="date" name="effective_date" class="dhl-input" value="${esc(cur.effective_date && cur.effective_date !== 'N/A' ? cur.effective_date : '')}">`)}
          ${intakeFieldCard('expiry_date', 'Date of expiry', false, fs.expiry_date.accepted,
            `<input type="date" name="expiry_date" class="dhl-input" value="${esc(cur.expiry_date && cur.expiry_date !== 'N/A' ? cur.expiry_date : '')}">
             <label class="ccre-tick ccre-none"><input type="checkbox" name="no_expiry" ${cur.expiry_date === 'N/A' ? 'checked' : ''}> No expiry</label>`)}
          ${intakeFieldCard('requirement_groups', 'Requirement to raise (group)', true, fs.requirement_groups.accepted,
            multiHtml('requirement_groups', opts.requirement_groups, Array.isArray(cur.requirement_groups) ? cur.requirement_groups : [], {
              labels: Object.fromEntries((opts.requirement_group_details || []).map((g) => [g.code, `${g.code} — ${g.name}`])),
              otherLabel: 'Not in the list… (needs a package change)' }) + groupCatalogHtml(opts), true)}
          ${intakeFieldCard('network_product_codes', fs.network_product_codes.label, false, fs.network_product_codes.accepted,
            `${multiHtml('network_product_codes', opts.network_product_codes, Array.isArray(cur.network_product_codes) ? cur.network_product_codes : [])}
             <label class="ccre-tick ccre-none"><input type="checkbox" name="all_products" ${npcNa ? 'checked' : ''}> All products</label>`, true)}
        </div>
        <h4>Conditions</h4>
        <p class="ccre-hint">Value, weight and any other condition. Pick a field, an operator and the value — <b>AND</b> adds a condition that must also hold, <b>OR</b> an alternative to that row. Value and weight limits become the M2C Min/Max columns; the rest becomes Other Logic.</p>
        <div class="ccre-m2c-field ccre-cond" id="mf-conditions"><div id="cond-builder"></div></div>
        <h4>Other details</h4>
        <div class="ccre-grid2">
          <div><label class="ccre-field-label">Requested go-live</label><input name="requested_rtp" type="date" class="dhl-input" value="${esc(prev.requested_rtp || '')}"></div>
          <div><label class="ccre-field-label">Business owner</label><input name="business_owner" class="dhl-input" value="${esc(prev.business_owner || '')}"></div>
        </div>
        <div class="ccre-row ccre-wrap ccre-gap">
          <button class="dhl-btn dhl-btn--primary" type="submit">Save requirement</button></div></form>`;
    }
  }
  const next = data.requirement ? nextStep('submit_requirement', 'the requirement is complete — send it to the CCRE consultant for approval.') : '';
  el.innerHTML = `<h3>Requirement intake</h3>${reviewNote}${next}${input}<h4>Captured requirement</h4>${requirementCard(data.requirement)}`;
  wireNextStep(el);
  el.querySelectorAll('.ccre-subtabs .dhl-tab').forEach((b) => {
    b.onclick = () => { S.intakeTab = b.dataset.tab; renderStage(); };
  });

  const chatBox = $('intake-chat');
  if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;
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

  const form = $('intake-form');
  if (!form) return;
  let timer = null;
  let touched = !!data.requirement;
  const check = () => api('POST', `/api/onboardings/${S.caseId}/intake/extract`, { text: '', m2c: collectIntake(form) })
    .then((res) => showIntakeCheck(form, res, touched)).catch(() => {});
  const later = () => { touched = true; clearTimeout(timer); timer = setTimeout(check, 400); };
  wirePicks(form);
  wireMulti(form.querySelector('.ccre-m2c-grid'), later);
  renderBuilder($('cond-builder'), condSpec, later);
  const syncBoxes = () => {
    form.expiry_date.disabled = form.no_expiry.checked;
    form.querySelectorAll('[data-multi="network_product_codes"] select, [data-multi="network_product_codes"] button, [data-multi="network_product_codes"] input')
      .forEach((x) => { x.disabled = form.all_products.checked; });
  };
  form.addEventListener('change', () => { syncBoxes(); later(); });
  syncBoxes();
  check();

  $('intake-nlp').onclick = () => run('NLP', async () => {
    const text = form.description.value.trim();
    if (!text) { toast('Write the requirement first.', true); return; }
    const res = await api('POST', `/api/onboardings/${S.caseId}/intake/extract`, { text, m2c: {} });
    const c = res.criteria;
    // Fill only what is still empty — never overwrite a choice already made.
    const setPick = (key, v) => {
      const w = form.querySelector(`[data-pick="${key}"]`);
      if (!w || pickValue(w) || !v || v === 'N/A') return;
      const sel = w.querySelector('select');
      if ([...sel.options].some((o) => o.value === v)) sel.value = v; else { sel.value = OTHER; w.querySelector('.ccre-pick-other').hidden = false; w.querySelector('.ccre-pick-other').value = v; }
    };
    setPick('region', c.region);
    if (!form.shipment_type.value && c.shipment_type) form.shipment_type.value = c.shipment_type;
    if (!form.effective_date.value && c.effective_date && c.effective_date !== 'N/A') form.effective_date.value = c.effective_date;
    if (c.expiry_date === 'N/A') form.no_expiry.checked = true; else if (!form.expiry_date.value && c.expiry_date) form.expiry_date.value = c.expiry_date;
    if (c.network_product_codes === 'N/A') form.all_products.checked = true;
    const setMulti = (key, vals) => {
      const w = form.querySelector(`[data-multi="${key}"]`);
      if (!Array.isArray(vals) || multiValues(w).length) return;
      w.dataset.values = JSON.stringify(vals);
    };
    setMulti('network_product_codes', c.network_product_codes);
    setMulti('requirement_groups', c.requirement_groups);
    wireMulti(form.querySelector('.ccre-m2c-grid'), later);
    if (!(S.cond || []).length && (res.conditions || []).length) S.cond = res.conditions;
    renderBuilder($('cond-builder'), condSpec, later);
    syncBoxes();
    touched = true;
    await check();
    toast('Form filled from your text — check the fields marked in red.');
  });
  form.onsubmit = (e) => {
    e.preventDefault();
    run('Save requirement', async () => {
      const res = await api('POST', `/api/onboardings/${S.caseId}/intake/form`, {
        description: form.description.value || '', m2c: collectIntake(form),
        requested_rtp: form.requested_rtp.value || null, business_owner: form.business_owner.value || null,
      });
      S.condCase = null;
      toast(res.check.complete ? 'Requirement saved and complete — submit it for approval.'
        : `Saved — ${res.check.missing.length} to answer, ${Object.keys(res.check.errors).length} not accepted.`, !res.check.complete);
      await refreshCase();
    });
  };
}

// ── 2. Timeline ──────────────────────────────────────────────
async function renderTimeline(el) {
  const tl = S.overview.timeline;
  if (isBusiness() && !tl) return businessWaiting(el, 'The delivery timeline will appear here once the PM approves it.');
  const planning = state() === 'TIMELINE_PLANNING';
  const editable = !isBusiness() && ['TIMELINE_PLANNING', 'TIMELINE_REVIEW'].includes(state())
    && hasRole('PM', 'ADMIN');
  let html = '<h3>Delivery timeline</h3>';
  if (planning && hasRole('PM', 'ADMIN')) {
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
  if (tl && tl.status === 'DRAFT') html = nextStep('approve_timeline', 'check the plan; approving publishes it to the business and starts rule configuration.') + html;
  el.innerHTML = html;
  wireNextStep(el);
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

// ── Rule configuration workspace ─────────────────────────────
// Sub-tabs: the Import rows (with their bindings = SIR Reference), changes vs the
// workbook, package coverage (Technical SIR/SIRG), the DMG email and the M2C download.
const RC_TABS = [
  ['rows', 'Rules (Import + SIR Reference)'], ['changes', 'Changes vs workbook'],
  ['coverage', 'Package coverage'], ['dmg', 'DMG email'], ['download', 'Validate & download'],
];
const RC_STATUS = {
  ok: ['ccre-st--ok', '&#10003; OK'], warning: ['ccre-st--warn', '! Check'],
  package: ['ccre-st--pkg', '&#9888; Package gap'], error: ['ccre-st--err', '&#10005; Error'],
};

async function renderRuleConfig(el) {
  if (isBusiness()) return businessWaiting(el, 'The CCRE team is configuring the rules and DMG changes for your requirement.');
  const canStart = state() === 'RULE_CONFIG' && hasRole(...CCRE);
  const ws = await api('GET', `/api/onboardings/${S.caseId}/rule-config`);
  if (!ws.draft) {
    el.innerHTML = `<h3>Rule configuration + DMG</h3>
      ${canStart ? `<div class="ccre-next"><div><strong>Next step:</strong> start the M2C draft. It is seeded with ${esc(ws.country)}'s existing rows from the loaded workbook, so you edit what is live instead of retyping it.</div>
        <button id="m2c-start" class="dhl-btn dhl-btn--primary">Start M2C draft</button></div>`
        : '<p class="ccre-hint">The M2C draft starts when the onboarding reaches rule configuration.</p>'}
      <h4>DMG changes</h4>${await dmgSection()}`;
    wireDmg(el);
    if ($('m2c-start')) {
      $('m2c-start').onclick = () => run('Start M2C', async () => {
        const r = await api('POST', `/api/onboardings/${S.caseId}/m2c/start`);
        toast(`M2C draft started — ${r.rules_copied} existing row(s) copied.`);
        await refreshCase();
      });
    }
    return;
  }
  S.rc = ws;
  S.rcTab = S.rcTab || 'rows';
  const s = ws.summary;
  el.innerHTML = `<div class="ccre-row ccre-space ccre-wrap"><h3>Rule configuration + DMG — ${esc(ws.draft.label || ws.draft.version)}</h3>
      <span class="ccre-hint">Workbook ${esc(ws.draft.source_version || '—')} · config package ${esc(ws.package_version || '—')}${ws.editable ? '' : ' · <strong>read only</strong>'}</span></div>
    ${nextStep('request_sanity_check', 'when every row is free of errors and the DMG email task is completed, send the configuration to the sanity check.')}
    <div class="ccre-rc-summary">
      <div><b>${s.rows}</b><span>rows for ${esc(ws.country)}</span></div>
      <div class="ccre-st--ok"><b>${s.ok}</b><span>OK</span></div>
      <div class="ccre-st--warn"><b>${s.warning}</b><span>to check</span></div>
      <div class="ccre-st--pkg"><b>${s.package}</b><span>package gaps</span></div>
      <div class="ccre-st--err"><b>${s.error}</b><span>errors (block submit)</span></div>
    </div>
    <div class="ccre-subtabs">${RC_TABS.map(([k, l]) => `<button class="dhl-tab ${S.rcTab === k ? 'dhl-tab--active' : ''}" data-rctab="${k}">${esc(l)}</button>`).join('')}</div>
    <div id="rc-body"></div>`;
  wireNextStep(el);
  el.querySelectorAll('[data-rctab]').forEach((b) => { b.onclick = () => { S.rcTab = b.dataset.rctab; renderRuleConfig(el); }; });
  const body = $('rc-body');
  if (S.rcTab === 'rows') return rcRows(body, el);
  if (S.rcTab === 'changes') return rcChanges(body);
  if (S.rcTab === 'coverage') return rcCoverage(body);
  if (S.rcTab === 'dmg') { body.innerHTML = await dmgSection(); wireDmg(body); return; }
  return rcDownload(body);
}

const rcBand = (lo, hi, unit) => (lo == null && hi == null ? '—' : `${lo ?? '…'} – ${hi ?? '…'}${unit ? ' ' + unit : ''}`);

async function rcRows(body, panel) {
  const ws = S.rc;
  const m = await api('GET', `/api/onboardings/${S.caseId}/m2c`);
  const proposals = (m.proposals || []).filter((p) => p.status === 'PROPOSED');
  let html = '';
  if (ws.editable) {
    html += `<div class="ccre-row ccre-wrap ccre-gap">
      <button id="rc-from-req" class="dhl-btn dhl-btn--primary">&#8681; Rows from the requirement</button>
      <button id="rc-add" class="dhl-btn dhl-btn--ghost">+ Add row</button>
      <input id="m2c-notes" class="dhl-input ccre-grow" placeholder="Notes for the AI (optional)">
      <button id="m2c-draft" class="dhl-btn dhl-btn--ghost">&#9998; Propose rows from the requirement (AI)</button></div>`;
  }
  html += proposals.map((p) => `<div class="dhl-gate dhl-gate--show ccre-gap">
      <div class="dhl-gate__head"><span class="dhl-gate__title">AI proposal — ${esc(p.rationale || '')}</span>
      <span class="dhl-val-chip dhl-val-chip--warn">not applied</span></div>
      ${table(['Group', 'Shipment', 'Value band', 'Other Logic', 'Why'], (p.payload.rules || []).map((r) =>
        `<tr><td>${esc(r.sirg_cd || '—')}</td><td>${esc(r.shipment_type || '—')}</td>
         <td>${esc(rcBand(r.min_value, r.max_value, r.currency))}</td><td class="ccre-mono">${esc(r.other_logic || '—')}</td><td>${esc(r.rationale || '')}</td></tr>`))}
      ${(p.payload.open_questions || []).length ? `<h4>Open questions</h4>${list(p.payload.open_questions, 'ccre-warn')}` : ''}
      ${ws.editable ? `<div class="dhl-gate__actions"><button class="dhl-btn dhl-btn--primary" data-accept="${esc(p.id)}">&#10003; Add these rows</button>
        <button class="dhl-btn dhl-btn--ghost" data-reject="${esc(p.id)}">&#10006; Discard</button></div>` : ''}
    </div>`).join('');
  html += ws.rows.length ? `<div class="ccre-table-wrap"><table class="dhl-table ccre-rc-table"><thead><tr>
      <th>Row</th><th>Status</th><th>Group (SIRG)</th><th>B2B/B2C</th><th>Value band</th><th>Weight</th><th>Valid</th>
      <th>Other Logic</th><th>Requirement definitions (SIR Reference)</th><th></th></tr></thead><tbody>
      ${ws.rows.map((r) => {
        const [cls, label] = RC_STATUS[r.status];
        return `<tr class="${S.rcOpen === r.id ? 'is-open' : ''}">
          <td>${r.row_no ?? '<em>new</em>'}</td><td><span class="ccre-st ${cls}">${label}</span></td>
          <td>${esc(r.sirg_cd || '—')}</td><td>${esc(r.shipment_type || '—')}</td>
          <td>${esc(rcBand(r.min_value, r.max_value, r.currency))}${r.value_basis ? ` <small>(${esc(r.value_basis)})</small>` : ''}</td>
          <td>${esc(rcBand(r.min_weight, r.max_weight, 'kg'))}</td>
          <td><small>${esc(r.effective_date || '…')} → ${esc(r.expiry_date || '…')}</small></td>
          <td class="ccre-mono ccre-clip" title="${esc(r.other_logic || '')}">${esc(r.other_logic || '—')}</td>
          <td>${r.bindings.length ? r.bindings.map((b) => `<span class="ccre-tag" title="${esc(b.sir_id)}">${esc(b.cmpt_nm || b.sir_name || b.sir_id.slice(0, 8))}${b.waived_to_validate ? ' · waived' : ''}</span>`).join(' ') : '—'}</td>
          <td><button class="dhl-btn dhl-btn--ghost ccre-small-btn" data-open="${esc(r.id)}">${S.rcOpen === r.id ? 'Close' : (ws.editable ? 'Edit' : 'View')}</button></td></tr>
          ${S.rcOpen === r.id ? `<tr class="ccre-rc-editor-row"><td colspan="10"><div id="rc-editor"></div></td></tr>` : ''}`;
      }).join('')}</tbody></table></div>`
    : '<p class="ccre-hint">No rows for this country yet — add one, or let the AI propose rows from the approved requirement.</p>';
  body.innerHTML = html;

  if ($('rc-from-req')) {
    $('rc-from-req').onclick = () => run('Rows from requirement', async () => {
      const rows = await api('POST', `/api/onboardings/${S.caseId}/rule-config/rows/from-requirement`);
      S.rcOpen = rows.length ? rows[0].id : null;
      toast(`${rows.length} row(s) created from the requirement's M2C criteria — bind the requirement definitions next.`);
      await renderRuleConfig(panel);
    });
  }
  if ($('rc-add')) {
    $('rc-add').onclick = () => run('Add row', async () => {
      const row = await api('POST', `/api/onboardings/${S.caseId}/rule-config/rows`, {
        region: (ws.rows[0] || {}).region || null, shipment_type: 'B2C',
        sirg_cd: ws.options.groups_mapped_for_country[0] || null });
      S.rcOpen = row.id;
      toast('Row added — fill it in below.');
      await renderRuleConfig(panel);
    });
  }
  if ($('m2c-draft')) {
    $('m2c-draft').onclick = () => run('AI draft', async () => {
      await api('POST', `/api/onboardings/${S.caseId}/m2c/draft`, { notes: $('m2c-notes').value });
      toast('AI proposal ready — review it above the rows.');
      await renderRuleConfig(panel);
    });
  }
  const decide = (id, accept) => run(accept ? 'Accept' : 'Discard', async () => {
    const res = await api('POST', `/api/proposals/${id}/decide`, { accept, actor: S.me.name, rule_set_id: ws.draft.id });
    toast(accept ? `${res.rules_created.length} row(s) added.` : 'Proposal discarded.');
    await renderRuleConfig(panel);
  });
  body.querySelectorAll('[data-accept]').forEach((b) => { b.onclick = () => decide(b.dataset.accept, true); });
  body.querySelectorAll('[data-reject]').forEach((b) => { b.onclick = () => decide(b.dataset.reject, false); });
  body.querySelectorAll('[data-open]').forEach((b) => {
    b.onclick = () => { S.rcOpen = S.rcOpen === b.dataset.open ? null : b.dataset.open; renderRuleConfig(panel); };
  });
  const open = ws.rows.find((r) => r.id === S.rcOpen);
  if (open) rcEditor($('rc-editor'), open, panel);
}

function rcSelect(id, values, current, ro, blank = true) {
  const vals = [...new Set([...(values || []), ...(current ? [current] : [])])];
  return `<select id="${id}" class="dhl-select" ${ro}>${blank ? '<option value="">—</option>' : ''}${vals.map((v) => `<option ${v === current ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>`;
}

function rcEditor(box, r, panel) {
  const ws = S.rc;
  const ro = ws.editable ? '' : 'disabled';
  const p = ws.options.permitted;
  const issues = r.issues.length ? `<ul class="ccre-issues">${r.issues.map((i) => `<li class="ccre-issue--${i.level}"><b>${esc(ws.options.fields[i.field] || ({ bindings: 'Requirement definitions', doc_reference: 'Document Reference' })[i.field] || i.field || '')}</b> ${esc(i.message)}</li>`).join('')}</ul>`
    : '<p class="ccre-ok">&#10003; No problems found in this row.</p>';
  const groups = [...ws.options.groups_mapped_for_country, ...ws.options.all_groups.filter((g) => !ws.options.groups_mapped_for_country.includes(g))];
  const num = (id, v) => `<input id="${id}" type="number" step="any" class="dhl-input" value="${v ?? ''}" ${ro}>`;
  box.innerHTML = `<div class="ccre-rc-editor">
    ${issues}
    <h4>Import row ${r.row_no ? `(workbook row ${r.row_no})` : '(new)'}</h4>
    <div class="ccre-grid4">
      <div><label class="ccre-field-label">Region</label>${rcSelect('rf-region', p.region, r.region, ro)}</div>
      <div><label class="ccre-field-label">B2B/B2C</label>${rcSelect('rf-shipment_type', p.shipment_type, r.shipment_type, ro)}</div>
      <div><label class="ccre-field-label">Requirement group (SIRG) *</label>${rcSelect('rf-sirg_cd', groups, r.sirg_cd, ro)}
        <small class="ccre-hint">Groups mapped for ${esc(ws.country)} are listed first.</small></div>
      <div><label class="ccre-field-label">Network product codes</label><input id="rf-network_product_codes" class="dhl-input" value="${esc(r.network_product_codes || '')}" ${ro}></div>
      <div><label class="ccre-field-label">Value basis (DV/IV)</label>${rcSelect('rf-value_basis', p.value_basis, r.value_basis, ro)}</div>
      <div><label class="ccre-field-label">Currency</label>${rcSelect('rf-currency', p.currency, r.currency, ro)}</div>
      <div><label class="ccre-field-label">Min value (&ge;)</label>${num('rf-min_value', r.min_value)}</div>
      <div><label class="ccre-field-label">Max value (&le;)</label>${num('rf-max_value', r.max_value)}</div>
      <div><label class="ccre-field-label">Min weight kg (&ge;)</label>${num('rf-min_weight', r.min_weight)}</div>
      <div><label class="ccre-field-label">Max weight kg (&le;)</label>${num('rf-max_weight', r.max_weight)}</div>
      <div><label class="ccre-field-label">Effective date</label><input id="rf-effective_date" type="date" class="dhl-input" value="${esc(r.effective_date || '')}" ${ro}></div>
      <div><label class="ccre-field-label">Expiry date</label><input id="rf-expiry_date" type="date" class="dhl-input" value="${esc(r.expiry_date || '')}" ${ro}></div>
      <div><label class="ccre-field-label">Country hold code</label><input id="rf-country_hold_cd" class="dhl-input" value="${esc(r.country_hold_cd || '')}" ${ro}></div>
      <div><label class="ccre-field-label">Global hold code</label><input id="rf-global_hold_cd" class="dhl-input" value="${esc(r.global_hold_cd || '')}" ${ro}></div>
      <div class="ccre-span2"><label class="ccre-field-label">Document Reference (generated)</label><input class="dhl-input ccre-mono" value="${esc(r.document_reference)}" disabled></div>
    </div>
    <label class="ccre-field-label">Other Logic (condition)</label>
    <textarea id="rf-other_logic" class="dhl-textarea ccre-mono ccre-small" ${ro}>${esc(r.other_logic || '')}</textarea>
    ${ws.editable ? `<details class="ccre-details"><summary>Build the condition from choices</summary><div id="rc-builder"></div></details>` : ''}
    ${ws.editable ? `<div class="ccre-row ccre-wrap ccre-gap">
      <button id="rf-save" class="dhl-btn dhl-btn--primary">Save row</button>
      <button id="rf-align" class="dhl-btn dhl-btn--ghost" title="Copy the approved requirement's region, B2B/B2C, dates, product codes, value, weight and Other Logic onto this row">Align with the requirement</button>
      <button id="rf-dup" class="dhl-btn dhl-btn--ghost">Duplicate row</button>
      <button id="rf-del" class="dhl-btn dhl-btn--ghost ccre-act--reject">Remove row</button></div>` : ''}
    <h4>Requirement definitions for this row (SIR Reference)</h4>
    ${r.bindings.length ? table(['Definition', 'Group', 'Waived to validate', 'Waived if whitelisted', 'Only if service code', 'Attributes', ''],
      r.bindings.map((b) => `<tr><td><b>${esc(b.cmpt_nm || b.sir_name || '—')}</b><br><small class="ccre-mono">${esc(b.sir_id)}</small></td>
        <td>${esc(b.sirg_cd || r.sirg_cd || '—')}</td><td>${b.waived_to_validate ? 'Yes' : 'No'}</td><td>${b.waived_if_whitelisted ? 'Yes' : 'No'}</td>
        <td>${esc(b.check_service_code || '—')}</td><td>${b.attribute_ids.length || 'all'}</td>
        <td>${ws.editable ? `<button class="dhl-btn dhl-btn--ghost ccre-small-btn" data-unbind="${esc(b.id)}">Remove</button>` : ''}</td></tr>`))
      : '<p class="ccre-hint">No definition bound — the row would trigger the group without saying which documents are required.</p>'}
    ${ws.editable ? `<details class="ccre-details" ${r.bindings.length ? '' : 'open'}><summary>+ Bind a requirement definition</summary>
      <div class="ccre-row ccre-wrap ccre-gap"><input id="bd-q" class="dhl-input ccre-grow" placeholder="Search by name or component, e.g. POA, invoice">
        <button id="bd-search" class="dhl-btn dhl-btn--ghost">Search</button></div>
      <div id="bd-results"></div></details>` : ''}
  </div>`;
  if (!ws.editable) return;

  const val = (id) => { const v = $(id).value.trim(); return v === '' ? null : v; };
  const numv = (id) => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
  $('rf-save').onclick = () => run('Save row', async () => {
    const payload = {};
    ['region', 'shipment_type', 'sirg_cd', 'network_product_codes', 'value_basis', 'currency', 'effective_date',
      'expiry_date', 'country_hold_cd', 'global_hold_cd', 'other_logic'].forEach((f) => { payload[f] = val(`rf-${f}`); });
    ['min_value', 'max_value', 'min_weight', 'max_weight'].forEach((f) => { payload[f] = numv(`rf-${f}`); });
    const res = await api('PUT', `/api/onboardings/${S.caseId}/rule-config/rows/${r.id}`, payload);
    toast(res.status === 'error' ? 'Saved — the row still has errors.' : 'Row saved.', res.status === 'error');
    await renderRuleConfig(panel);
  });
  $('rf-align').onclick = () => run('Align', async () => {
    const ok = await dialog('Align with the requirement?', '<p>The row gets the region, B2B/B2C, dates, product codes, value and weight limits and Other Logic. The requirement group and bound definitions stay. The change shows under <b>Changes vs workbook</b>.</p>', 'Align');
    if (!ok) return;
    await api('POST', `/api/onboardings/${S.caseId}/rule-config/rows/${r.id}/align-requirement`);
    toast('Row aligned with the requirement.');
    await renderRuleConfig(panel);
  });
  $('rf-dup').onclick = () => run('Duplicate', async () => {
    const res = await api('POST', `/api/onboardings/${S.caseId}/rule-config/rows/${r.id}/duplicate`);
    S.rcOpen = res.id;
    toast('Row duplicated — the copy is open.');
    await renderRuleConfig(panel);
  });
  $('rf-del').onclick = () => run('Remove', async () => {
    const ok = await dialog('Remove this row?', `<p>Row ${esc(r.row_no ?? '(new)')} — ${esc(r.sirg_cd || '')} ${esc(r.shipment_type || '')}. It will show as <b>removed</b> in the changes and the M2C download.</p>`, 'Remove');
    if (!ok) return;
    await api('DELETE', `/api/onboardings/${S.caseId}/rule-config/rows/${r.id}`);
    S.rcOpen = null;
    toast('Row removed.');
    await renderRuleConfig(panel);
  });
  box.querySelectorAll('[data-unbind]').forEach((b) => {
    b.onclick = () => run('Remove binding', async () => {
      await api('DELETE', `/api/onboardings/${S.caseId}/rule-config/rows/${r.id}/bindings/${b.dataset.unbind}`);
      await renderRuleConfig(panel);
    });
  });
  rcBuilder($('rc-builder'));
  const search = () => run('Search', async () => {
    const group = $('rf-sirg_cd').value;
    const defs = await api('GET', `/api/onboardings/${S.caseId}/rule-config/definitions?q=${encodeURIComponent($('bd-q').value)}&group=${encodeURIComponent(group)}`);
    $('bd-results').innerHTML = defs.length ? table(['Definition', 'Component', 'Mapped', ''], defs.map((d) => `<tr>
        <td><b>${esc(d.name || '—')}</b><br><small class="ccre-mono">${esc(d.sir_id)}</small></td><td>${esc(d.cmpt_nm || '—')}</td>
        <td>${d.mapped_in_group ? `<span class="ccre-st ccre-st--ok">in ${esc(group)} for ${esc(ws.country)}</span>` : d.mapped_for_country ? `<span class="ccre-st ccre-st--warn">other group</span>` : '<span class="ccre-st ccre-st--pkg">not mapped</span>'}</td>
        <td><button class="dhl-btn dhl-btn--ghost ccre-small-btn" data-bind="${esc(d.sir_id)}" data-name="${esc(d.name || d.cmpt_nm || '')}">Bind…</button></td></tr>`))
      : '<p class="ccre-hint">Nothing found in the config package.</p>';
    $('bd-results').querySelectorAll('[data-bind]').forEach((b) => { b.onclick = () => rcBind(r, b.dataset.bind, b.dataset.name, panel); });
  });
  $('bd-search').onclick = search;
  $('bd-q').onkeydown = (e) => { if (e.key === 'Enter') search(); };
}

async function rcBind(r, sirId, name, panel) {
  const attrs = await api('GET', `/api/onboardings/${S.caseId}/rule-config/definitions/${sirId}/attributes`);
  const v = await dialog(`Bind ${name}`, `
    <label class="ccre-tick"><input type="checkbox" name="waived_to_validate"> Waived to validate (always create the case, no SIR validation)</label>
    <label class="ccre-tick"><input type="checkbox" name="waived_if_whitelisted"> Waived if whitelisted</label>
    <label class="ccre-field-label">Only if service code (optional)</label><input class="dhl-input" name="check_service_code" placeholder="e.g. DD">
    <label class="ccre-field-label">Attributes to require (none ticked = the whole definition)</label>
    <div class="ccre-attr-list">${attrs.map((a) => `<label class="ccre-tick"><input type="checkbox" name="att" value="${esc(a.att_id)}">
      ${esc(a.name || a.att_id)} ${a.mandatory ? '<small>(mandatory)</small>' : ''}
      ${a.message_positions.length ? `<small class="ccre-mono">→ ${esc(a.message_positions[0])}</small>` : ''}</label>`).join('') || '<p class="ccre-hint">No attributes listed.</p>'}</div>`, 'Bind');
  if (!v) return;
  await run('Bind', async () => {
    await api('POST', `/api/onboardings/${S.caseId}/rule-config/rows/${r.id}/bindings`, {
      sir_id: sirId, waived_to_validate: !!v.waived_to_validate, waived_if_whitelisted: !!v.waived_if_whitelisted,
      check_service_code: v.check_service_code || null, attribute_ids: v.att || [] });
    toast(`${name} bound to the row.`);
    await renderRuleConfig(panel);
  });
}

function rcBuilder(box) {
  if (!box) return;
  const types = S.rc.options.builder;
  const clauseHtml = () => `<div class="ccre-clause ccre-row ccre-wrap">
      <select class="dhl-select" data-k="type">${Object.entries(types).map(([k, t]) => `<option value="${k}">${esc(t.label)}</option>`).join('')}<option value="raw">Custom expression</option></select>
      <select class="dhl-select" data-k="op"></select>
      <input class="dhl-input ccre-grow" data-k="values">
      <button class="dhl-btn dhl-btn--ghost ccre-small-btn" data-k="del">&#10005;</button></div>`;
  box.innerHTML = `<p class="ccre-hint">Each line is one condition. The result is checked by the same grammar the validator uses.</p>
    <div id="cb-lines">${clauseHtml()}</div>
    <div class="ccre-row ccre-wrap ccre-gap"><button id="cb-more" class="dhl-btn dhl-btn--ghost ccre-small-btn">+ condition</button>
      <label>Combine with <select id="cb-join" class="dhl-select"><option value="and">AND (all must hold)</option><option value="or">OR (any may hold)</option></select></label>
      <button id="cb-build" class="dhl-btn dhl-btn--ghost">Preview</button><button id="cb-use" class="dhl-btn dhl-btn--primary" disabled>Use as Other Logic</button></div>
    <div id="cb-out"></div>
    <details class="ccre-details"><summary>Or pick from the workbook's Other Logic palette</summary><div id="cb-palette"></div></details>`;
  const wire = (line) => {
    const type = line.querySelector('[data-k=type]');
    const op = line.querySelector('[data-k=op]');
    const values = line.querySelector('[data-k=values]');
    const sync = () => {
      const t = types[type.value];
      op.innerHTML = t ? t.ops.map((o) => `<option>${esc(o)}</option>`).join('') : '<option>as written</option>';
      values.placeholder = t ? t.values : 'e.g. !serviceCodeList.contains("DD")';
    };
    type.onchange = sync; sync();
    line.querySelector('[data-k=del]').onclick = () => { line.remove(); };
  };
  box.querySelectorAll('.ccre-clause').forEach(wire);
  $('cb-more').onclick = () => { $('cb-lines').insertAdjacentHTML('beforeend', clauseHtml()); wire($('cb-lines').lastElementChild); };
  let built = null;
  $('cb-build').onclick = () => run('Preview', async () => {
    const clauses = [...box.querySelectorAll('.ccre-clause')].map((l) => ({
      type: l.querySelector('[data-k=type]').value, op: l.querySelector('[data-k=op]').value,
      values: l.querySelector('[data-k=values]').value }));
    const res = await api('POST', `/api/onboardings/${S.caseId}/rule-config/condition`, { clauses, joiner: $('cb-join').value });
    built = res.expression;
    $('cb-out').innerHTML = `<pre class="ccre-pre">${esc(res.expression)}</pre>
      ${res.errors.length ? list(res.errors, 'ccre-inline-error') : '<p class="ccre-ok">&#10003; Valid condition.</p>'}${res.warnings.length ? list(res.warnings, 'ccre-warn') : ''}`;
    $('cb-use').disabled = !!res.errors.length;
  });
  $('cb-use').onclick = () => { if (built !== null) { $('rf-other_logic').value = built; toast('Condition copied into Other Logic — save the row to keep it.'); } };
  box.closest('details').addEventListener('toggle', async (e) => {
    if (!e.target.open || $('cb-palette').dataset.loaded) return;
    const pal = await api('GET', `/api/onboardings/${S.caseId}/rule-config/palette`);
    $('cb-palette').dataset.loaded = '1';
    $('cb-palette').innerHTML = pal.map((p, i) => `<div class="ccre-row ccre-space ccre-pal">
      <code class="ccre-mono ccre-clip" title="${esc(p.expression)}">${esc(p.expression)}</code>
      ${p.ok ? `<button class="dhl-btn dhl-btn--ghost ccre-small-btn" data-pal="${i}">Use</button>` : `<span class="ccre-st ccre-st--err" title="${esc(p.problems.join(' '))}">has errors</span>`}</div>`).join('');
    $('cb-palette').querySelectorAll('[data-pal]').forEach((b) => { b.onclick = () => { $('rf-other_logic').value = pal[+b.dataset.pal].expression; toast('Palette condition copied — save the row to keep it.'); }; });
  });
}

async function rcChanges(body) {
  const ch = await api('GET', `/api/onboardings/${S.caseId}/rule-config/changes`);
  const label = (f) => ch.labels[f] || (f === 'bindings' ? 'Requirement definitions' : f);
  const c = ch.counts;
  body.innerHTML = `<p class="ccre-hint">The draft compared with ${esc(S.rc.country)}'s rows in workbook ${esc(ch.baseline || '—')}. This is exactly what will change in the M2C.</p>
    <div class="ccre-row ccre-wrap ccre-gap"><span class="ccre-st ccre-st--ok">${c.NEW} new</span><span class="ccre-st ccre-st--warn">${c.CHANGED} changed</span>
      <span class="ccre-st ccre-st--err">${c.REMOVED} removed</span><span class="ccre-st">${c.UNCHANGED} unchanged</span></div>
    ${ch.items.filter((i) => i.status !== 'UNCHANGED').length ? table(['Change', 'Row', 'Group', 'What changed'], ch.items.filter((i) => i.status !== 'UNCHANGED').map((i) => `<tr>
      <td><span class="ccre-st ${i.status === 'NEW' ? 'ccre-st--ok' : i.status === 'CHANGED' ? 'ccre-st--warn' : 'ccre-st--err'}">${i.status.toLowerCase()}</span></td>
      <td>${esc(i.row_no ?? 'new')}</td><td>${esc(i.row.sirg_cd || '—')}</td>
      <td>${i.status === 'CHANGED' ? Object.entries(i.fields).map(([f, d]) => `<div><b>${esc(label(f))}</b>: <del>${esc(d.from ?? '—')}</del> → <ins>${esc(d.to ?? '—')}</ins></div>`).join('')
        : i.status === 'NEW' ? `${esc(i.row.shipment_type || '')} ${esc(rcBand(i.row.min_value, i.row.max_value, i.row.currency))} <span class="ccre-mono">${esc(i.row.other_logic || '')}</span>`
        : 'Whole row removed from the M2C'}</td></tr>`))
      : '<p class="ccre-ok">No changes yet — the draft matches the workbook.</p>'}`;
}

async function rcCoverage(body) {
  const cov = await api('GET', `/api/onboardings/${S.caseId}/rule-config/coverage`);
  const yn = (ok) => (ok ? '<span class="ccre-st ccre-st--ok">&#10003;</span>' : '<span class="ccre-st ccre-st--err">&#10005;</span>');
  body.innerHTML = `<p class="ccre-hint">CCRE can only raise a requirement the config package (${esc(cov.package_version || '—')}) ships and maps for ${esc(S.rc.country)} — the <b>Technical SIR</b> and <b>Technical SIRG</b> tabs. Gaps are requested from Support; the sanity check will not pass until the package covers them.</p>
    ${cov.complete ? '<p class="ccre-ok">&#10003; The package covers everything this draft needs.</p>'
      : `<div class="ccre-next"><div><strong>${cov.support_request.length} mapping(s) missing.</strong> Download the request and send it to Support (it is in the package's mapping CSV format).</div>
        <button id="cov-csv" class="dhl-btn dhl-btn--primary">&#8681; Package request (.csv)</button></div>`}
    ${cov.items.length ? table(['Group (SIRG)', 'Definition (SIR)', 'Group in package', 'Definition shipped', `Mapped for ${esc(S.rc.country)}`],
      cov.items.map((i) => `<tr><td><b>${esc(i.sirg_cd)}</b><br><small class="ccre-mono">${esc(i.sirg_id || '—')}</small></td>
        <td>${esc(i.cmpt_nm || i.sir_name || '—')}<br><small class="ccre-mono">${esc(i.sir_id || '(none bound)')}</small></td>
        <td>${yn(i.sirg_in_package)}</td><td>${i.sir_id ? yn(i.sir_in_package) : '—'}</td><td>${i.sir_id ? yn(i.mapped_for_country) : yn(i.group_mapped_for_country)}</td></tr>`))
      : '<p class="ccre-hint">No groups used yet.</p>'}`;
  if ($('cov-csv')) $('cov-csv').onclick = () => run('Download', () => download(`/api/onboardings/${S.caseId}/rule-config/coverage.csv`, 'package_request.csv'));
}

async function rcDownload(body) {
  body.innerHTML = `<div class="ccre-grid2">
    <div class="ccre-card"><h4>M2C workbook</h4><p class="ccre-hint">${esc(S.rc.country)}'s M2C generated from this draft in the workbook's own layout: Import, Export, SIR Reference, Technical SIR, Technical SIRG, Other Logic, Validation — plus a <b>Changes</b> tab. Document references and SIR Reference positions are generated formulas, so they always point at the right row.</p>
      <button id="dl-m2c" class="dhl-btn dhl-btn--primary">&#8681; Download M2C (.xlsx)</button></div>
    <div class="ccre-card"><h4>Full validation</h4><p class="ccre-hint">All 16 deterministic checks across the M2C and the config package — the same run the sanity check uses.</p>
      <button id="m2c-validate" class="dhl-btn dhl-btn--ghost">&#9989; Run validation</button></div></div>
    <div id="m2c-report"></div>
    <h4>Sanity pre-check</h4><p class="ccre-hint">The same six checks the sanity check runs — fix what is marked here, before you submit.</p>
    <div id="rc-precheck"><p class="ccre-hint">Checking…</p></div>`;
  api('GET', `/api/onboardings/${S.caseId}/sanity`).then((s) => {
    $('rc-precheck').innerHTML = sanityCards(s, { inStage: false });
    wireSanity($('rc-precheck'), s, () => rcDownload(body));
  }).catch(() => {});
  $('dl-m2c').onclick = () => run('Download', () => download(`/api/onboardings/${S.caseId}/rule-config/m2c.xlsx`, 'M2C.xlsx'));
  $('m2c-validate').onclick = () => run('Validate', async () => {
    const rep = await api('POST', `/api/onboardings/${S.caseId}/m2c/validate`);
    $('m2c-report').innerHTML = `<h4>Validation</h4>${findingsHtml(rep)}`;
  });
}

// ── DMG email task (inside rule config) ──────────────────────
async function dmgSection() {
  const [d, tpl] = await Promise.all([api('GET', `/api/onboardings/${S.caseId}/dmg`),
    hasRole(...CCRE) ? api('GET', '/api/dmg/template') : Promise.resolve(null)]);
  const t = d.task;
  const inConfig = state() === 'RULE_CONFIG';
  const ccre = hasRole(...CCRE);
  const statusLine = !t ? '<span class="ccre-task ccre-task--open">&#9675; Not prepared</span>'
    : t.completed ? `<span class="ccre-task ccre-task--done">&#10003; Task completed — ${t.status === 'SENT' ? `approved by ${esc(t.decided_by)} and sent${t.sent_at ? ' on ' + esc(t.sent_at.slice(0, 10)) : ''}` : `not required (${esc(t.decision_comment || '')})`}</span>`
    : t.status === 'IN_REVIEW' ? `<span class="ccre-task ccre-task--open">&#9203; Waiting for CCRE review (submitted by ${esc(t.submitted_by)})</span>`
    : '<span class="ccre-task ccre-task--open">&#9998; Draft — edit, then submit for review</span>';
  let html = `<div class="ccre-card"><div class="ccre-row ccre-space"><strong>DMG email</strong>${statusLine}</div>`;
  if (t && t.status === 'DRAFT' && t.decision_comment) {
    html += `<div class="ccre-inline-error">Rejected by ${esc(t.decided_by)}: ${esc(t.decision_comment)}</div>`;
  }
  if (t && t.subject && t.status !== 'NOT_REQUIRED') {
    const edit = ccre && inConfig && t.status === 'DRAFT';
    html += `<div class="ccre-grid2 ccre-gap">
        <div><label class="ccre-field-label">To</label><input id="dmg-to" class="dhl-input" value="${esc(t.to.join(', '))}" ${edit ? '' : 'disabled'}></div>
        <div><label class="ccre-field-label">Cc</label><input id="dmg-cc" class="dhl-input" value="${esc(t.cc.join(', '))}" ${edit ? '' : 'disabled'}></div></div>
      <label class="ccre-field-label">Subject</label><input id="dmg-subject" class="dhl-input" value="${esc(t.subject)}" ${edit ? '' : 'disabled'}>
      <label class="ccre-field-label">Body</label><textarea id="dmg-body" class="dhl-textarea ccre-mail-body" ${edit ? '' : 'disabled'}>${esc(t.body)}</textarea>`;
  }
  if (ccre && inConfig) {
    html += '<div class="ccre-row ccre-wrap ccre-gap">';
    if (!t || t.status === 'DRAFT') html += `<button id="dmg-prepare" class="dhl-btn dhl-btn--ghost">${t ? '&#8635; Refill from template' : '&#9998; Prepare DMG email from template'}</button>`;
    if (t && t.status === 'DRAFT') html += '<button id="dmg-save" class="dhl-btn dhl-btn--ghost">Save draft</button><button id="dmg-submit" class="dhl-btn dhl-btn--primary">Submit for CCRE review</button>';
    if (t && t.status === 'IN_REVIEW') html += '<button id="dmg-approve" class="dhl-btn dhl-btn--primary ccre-act--approve">&#10003; Approve and send</button><button id="dmg-reject" class="dhl-btn dhl-btn--ghost ccre-act--reject">&#10005; Reject</button>';
    if (hasRole('CCRE_CONSULTANT', 'ADMIN') && (!t || !t.completed)) html += '<button id="dmg-na" class="dhl-btn dhl-btn--ghost">Mark DMG not required</button>';
    html += '</div>';
  }
  html += '</div>';
  if (tpl) {
    html += `<details class="ccre-details ccre-card"><summary>DMG email template and recipients (CCRE team)</summary>
      <p class="ccre-hint">Placeholders are filled from the onboarding: ${Object.keys(tpl.placeholders).map((k) => `<code>{{${esc(k)}}}</code>`).join(' ')}</p>
      <div class="ccre-grid2"><div><label class="ccre-field-label">To *</label><input id="tpl-to" class="dhl-input" value="${esc(tpl.to.join(', '))}" placeholder="dmg-team@dhl.com"></div>
        <div><label class="ccre-field-label">Cc</label><input id="tpl-cc" class="dhl-input" value="${esc(tpl.cc.join(', '))}"></div></div>
      <label class="ccre-field-label">Subject</label><input id="tpl-subject" class="dhl-input" value="${esc(tpl.subject)}">
      <label class="ccre-field-label">Body</label><textarea id="tpl-body" class="dhl-textarea ccre-mail-body">${esc(tpl.body)}</textarea>
      <button id="tpl-save" class="dhl-btn dhl-btn--primary ccre-gap">Save template</button>
      <span class="ccre-hint">Last saved by ${esc(tpl.updated_by || '—')}</span></details>`;
  }
  return html;
}

function wireDmg(el) {
  const list = (id) => $(id).value.split(/[,;\s]+/).filter(Boolean);
  const reload = async (msg) => { if (msg) toast(msg); await refreshCase(); };
  const on = (id, label, fn) => { const b = $(id); if (b) b.onclick = () => run(label, fn); };
  on('dmg-prepare', 'Prepare DMG email', async () => { await api('POST', `/api/onboardings/${S.caseId}/dmg/prepare`); await reload('DMG email filled from the template.'); });
  const save = async () => api('PUT', `/api/onboardings/${S.caseId}/dmg`, { subject: $('dmg-subject').value, body: $('dmg-body').value, to: list('dmg-to'), cc: list('dmg-cc') });
  on('dmg-save', 'Save', async () => { await save(); toast('Draft saved.'); });
  on('dmg-submit', 'Submit', async () => { await save(); await api('POST', `/api/onboardings/${S.caseId}/dmg/submit`); await reload('Submitted for CCRE review.'); });
  on('dmg-approve', 'Approve', async () => {
    const r = await api('POST', `/api/onboardings/${S.caseId}/dmg/decide`, { approve: true });
    await reload(r.status === 'SENT' ? 'Approved — DMG email sent. Task completed.' : 'Approved.');
  });
  on('dmg-reject', 'Reject', async () => {
    const v = await dialog('Reject the DMG email', '<label class="ccre-field-label">Reason (required)</label><textarea class="dhl-textarea ccre-small" name="comment" required></textarea>', 'Reject');
    if (!v) return;
    await api('POST', `/api/onboardings/${S.caseId}/dmg/decide`, { approve: false, comment: v.comment });
    await reload('Returned to draft with your reason.');
  });
  on('dmg-na', 'Not required', async () => {
    const v = await dialog('DMG not required', '<label class="ccre-field-label">Why is no DMG change needed? (required)</label><textarea class="dhl-textarea ccre-small" name="comment" required></textarea>', 'Confirm');
    if (!v) return;
    await api('POST', `/api/onboardings/${S.caseId}/dmg/not-required`, { comment: v.comment });
    await reload('DMG marked not required — task completed.');
  });
  on('tpl-save', 'Save template', async () => {
    await api('PUT', '/api/dmg/template', { subject: $('tpl-subject').value, body: $('tpl-body').value, to: list('tpl-to'), cc: list('tpl-cc') });
    toast('DMG template saved.');
    await renderStage();
  });
}

// ── 4. Sanity check — a plain checklist ──────────────────────
// ── 4. Sanity check — six plain checks, each with how to fix it ──
const SANITY_STATUS = {
  pass: ['ccre-st--ok', '&#10003; Passed'], fail: ['ccre-st--err', '&#10005; Needs attention'],
  waived: ['ccre-st--pkg', '&#9888; Accepted as exception'], info: ['ccre-st', '&#9432; For review'],
};

function sanityFindings(i) {
  const f = i.findings || [];
  if (!f.length) return '';
  if (i.key === 'rows') {
    return table(['Row', 'Group', 'What is wrong'], f.map((x) => `<tr><td>${esc(x.row)}</td><td>${esc(x.group || '—')}</td><td>${list(x.problems)}</td></tr>`));
  }
  if (i.key === 'requirement_match') {
    return f.map((x) => `<div class="ccre-sanity-sub"><b>${esc(x.problem)}</b>
      ${x.differences.length ? table(['Field', 'The requirement says', 'The M2C says'], x.differences.map((d) =>
        `<tr><td>${esc(d.field)}</td><td>${esc(d.requirement ?? '— (not set)')}</td><td>${esc(d.m2c ?? '— (not set)')}</td></tr>`)) : ''}</div>`).join('');
  }
  if (i.key === 'rules') {
    return table(['Check', 'What is wrong', 'Where'], f.map((x) => `<tr><td>${esc(x.check)}</td><td>${esc(x.message)}</td><td>${esc((x.rows || []).join(', ') || x.where)}</td></tr>`));
  }
  if (i.key === 'package') {
    return table(['Requirement group', 'Definition', 'Missing in the package'], f.map((x) => `<tr><td>${esc(x.group || '—')}</td><td>${esc(x.definition)}</td><td>${esc(x.needed)}</td></tr>`));
  }
  if (i.key === 'changes') {
    return table(['Change', 'Row', 'Group', 'What changed'], f.map((x) => `<tr><td>${esc(x.status)}</td><td>${esc(x.row)}</td><td>${esc(x.group || '—')}</td>
      <td>${Object.entries(x.fields || {}).map(([k, v]) => `<div><b>${esc(k)}</b>: <del>${esc(v.from ?? '—')}</del> → <ins>${esc(v.to ?? '—')}</ins></div>`).join('') || (x.status === 'new' ? 'New row' : 'Whole row')}</td></tr>`));
  }
  return '';
}

function sanityCards(s, { inStage }) {
  return s.items.map((i, n) => {
    const [cls, label] = SANITY_STATUS[i.status];
    const actions = [];
    if (i.fix && i.status === 'fail') {
      if (i.fix.action === 'package_request') actions.push(`<button class="dhl-btn dhl-btn--ghost" data-sfix="package">&#8681; ${esc(i.fix.label)}</button>`);
      else if (inStage && hasRole(...CCRE)) actions.push(`<button class="dhl-btn dhl-btn--ghost" data-sfix="send_back">${esc(i.fix.label)}</button>`);
      else if (!inStage) actions.push(`<span class="ccre-hint">Fix it here in rule configuration.</span>`);
    }
    if (i.waivable && i.status === 'fail' && s.can_waive) actions.push(`<button class="dhl-btn dhl-btn--ghost" data-swaive="${esc(i.key)}">Accept as exception…</button>`);
    const waiver = i.waiver ? `<div class="ccre-waiver"><b>Accepted as exception</b> by ${esc(i.waiver.by)}: ${esc(i.waiver.reason)}${i.waiver.reference ? ` · ref <b>${esc(i.waiver.reference)}</b>` : ''}
      ${s.can_waive ? `<button class="dhl-btn dhl-btn--ghost ccre-small-btn" data-srevoke="${esc(i.waiver.id)}">Revoke</button>` : ''}</div>` : '';
    return `<div class="ccre-sanity-card ccre-sanity-card--${i.status}">
      <div class="ccre-sanity-num">${n + 1}</div>
      <div class="ccre-sanity-body">
        <div class="ccre-row ccre-space ccre-wrap"><strong>${esc(i.title)}</strong><span class="ccre-st ${cls}">${label}</span></div>
        <div>${esc(i.summary)}</div>
        <details class="ccre-accept"><summary>Why this matters</summary><div>${esc(i.why)}</div></details>
        ${waiver}
        ${(i.findings || []).length ? `<details class="ccre-details" ${i.status === 'fail' ? 'open' : ''}><summary>${i.key === 'changes' ? 'Show the changes' : `Details (${i.findings.length})`}</summary>${sanityFindings(i)}</details>` : ''}
        ${(i.notes || []).length ? `<details class="ccre-details"><summary>Notes to read (${i.notes.length})</summary>${list(i.notes.map((x) => `${x.check}: ${x.message}`))}</details>` : ''}
        ${actions.length ? `<div class="ccre-row ccre-wrap ccre-gap">${actions.join('')}</div>` : ''}
      </div></div>`;
  }).join('');
}

function wireSanity(el, s, rerender) {
  el.querySelectorAll('[data-sfix="package"]').forEach((b) => {
    b.onclick = () => run('Download', () => download(`/api/onboardings/${S.caseId}/rule-config/coverage.csv`, 'package_request.csv'));
  });
  el.querySelectorAll('[data-sfix="send_back"]').forEach((b) => { b.onclick = () => sanitySendBack(s); });
  el.querySelectorAll('[data-swaive]').forEach((b) => {
    b.onclick = () => run('Exception', async () => {
      const item = s.items.find((x) => x.key === b.dataset.swaive);
      const v = await dialog(`Accept as exception: ${item.title}`, `
        <p class="ccre-hint">${b.dataset.swaive === 'package' ? 'Use this when Support has been asked to add the mapping and UAT may continue meanwhile.' : 'Use this when the M2C differs from the requirement on purpose (e.g. split into two rows).'}</p>
        <label class="ccre-field-label">Reason (required)</label><textarea class="dhl-textarea ccre-small" name="reason" required></textarea>
        <label class="ccre-field-label">Reference (Support ticket, email…)</label><input class="dhl-input" name="reference" placeholder="e.g. INC0012345">`, 'Accept as exception');
      if (!v) return;
      await api('POST', `/api/onboardings/${S.caseId}/sanity/waivers`, { item_key: b.dataset.swaive, reason: v.reason, reference: v.reference || null });
      toast('Recorded — the sanity check ran again.');
      await rerender();
    });
  });
  el.querySelectorAll('[data-srevoke]').forEach((b) => {
    b.onclick = () => run('Revoke', async () => {
      await api('DELETE', `/api/onboardings/${S.caseId}/sanity/waivers/${b.dataset.srevoke}`);
      toast('Exception revoked.');
      await rerender();
    });
  });
}

function sanitySendBack(s) {
  return run('Send back', async () => {
    const v = await dialog('Send back to rule configuration', `<p class="ccre-hint">The reason is filled in from the checks that need attention — edit it if you like.</p>
      <label class="ccre-field-label">Reason (shared with the team, kept on the audit trail)</label>
      <textarea class="dhl-textarea" name="comment" rows="6" required>${esc(s.send_back_reason || '')}</textarea>`, 'Send back');
    if (!v) return;
    await api('POST', `/api/onboardings/${S.caseId}/transition`, { name: 'sanity_failed', comment: v.comment });
    toast('Sent back to rule configuration.');
    S.viewStage = null;
    await refreshCase();
  });
}

async function renderSanity(el) {
  if (isBusiness()) return businessWaiting(el, 'The CCRE team is checking the configuration before testing starts.');
  const s = await api('GET', `/api/onboardings/${S.caseId}/sanity`);
  const scored = s.items.filter((i) => i.status !== 'info');
  const good = scored.filter((i) => i.status !== 'fail').length;
  const last = s.latest_run;
  const banner = s.ready
    ? `<div class="ccre-sanity-banner ccre-sanity-banner--ok"><b>&#10003; Ready to approve</b> — all ${scored.length} checks passed${s.counts.waived ? ` (${s.counts.waived} accepted as exception)` : ''}.</div>`
    : `<div class="ccre-sanity-banner ccre-sanity-banner--bad"><b>${scored.length - good} of ${scored.length} checks need attention.</b> Each card says what is wrong and how to fix it — send it back to rule configuration (button at the bottom), or accept a package gap or a deliberate difference as an exception.</div>`;
  el.innerHTML = `<div class="ccre-row ccre-space ccre-wrap"><h3>Sanity check</h3>
      <div class="ccre-row ccre-wrap" style="gap:8px">
        ${s.can_run ? '<button id="san-run" class="dhl-btn dhl-btn--ghost">&#8635; Run again</button>' : ''}
        ${last ? '<button id="san-report" class="dhl-btn dhl-btn--ghost">&#8681; Report (.xlsx)</button>' : ''}</div></div>
    <p class="ccre-hint">${esc(s.explanation)}</p>
    ${banner}
    <div class="ccre-sanity-progress"><div style="width:${Math.round((good / Math.max(scored.length, 1)) * 100)}%"></div></div>
    ${last ? `<p class="ccre-hint">Last run ${esc(last.at.replace('T', ' ').slice(0, 16))} by ${esc(last.run_by === 'system:on-entry' ? 'the system (on entering the stage)' : last.run_by)} — <b>${esc(last.status)}</b>${last.current ? '' : ' · <span class="ccre-err">the configuration changed since — run it again</span>'}</p>` : ''}
    ${s.ready ? nextStep('sanity_passed', 'every check passed — approve so UAT test cases can be prepared.') : ''}
    ${sanityCards(s, { inStage: s.in_stage })}
    ${s.in_stage && hasRole(...CCRE) && !s.ready ? `<div class="ccre-next ccre-next--back"><div><strong>Not ready?</strong> Send it back to rule configuration — the reason is filled in from the checks above.</div>
      <button id="san-back" class="dhl-btn dhl-btn--primary">Send back to rule config</button></div>` : ''}
    ${s.runs.length > 1 ? `<details class="ccre-details"><summary>Run history (${s.runs.length})</summary>${table(['When', 'By', 'Result', 'Passed / failed / exceptions', 'Cycle', ''],
      s.runs.map((r) => `<tr><td>${esc(r.at.replace('T', ' ').slice(0, 16))}</td><td>${esc(r.run_by)}</td><td>${esc(r.status)}</td><td>${r.passed} / ${r.failed} / ${r.waived}</td><td>${r.cycle}</td>
        <td><button class="dhl-btn dhl-btn--ghost ccre-small-btn" data-srep="${esc(r.id)}">Report</button></td></tr>`))}</details>` : ''}`;
  wireNextStep(el);
  wireSanity(el, s, () => renderSanity(el));
  if ($('san-run')) $('san-run').onclick = () => run('Run', async () => { const r = await api('POST', `/api/onboardings/${S.caseId}/sanity/run`); toast(r.status === 'PASS' ? 'All checks passed.' : `${r.failed} check(s) need attention.`, r.status !== 'PASS'); await refreshCase(); });
  if ($('san-report')) $('san-report').onclick = () => run('Report', () => download(`/api/onboardings/${S.caseId}/sanity/report.xlsx`, 'sanity.xlsx'));
  el.querySelectorAll('[data-srep]').forEach((b) => { b.onclick = () => run('Report', () => download(`/api/onboardings/${S.caseId}/sanity/report.xlsx?run_id=${b.dataset.srep}`, 'sanity.xlsx')); });
  if ($('san-back')) $('san-back').onclick = () => sanitySendBack(s);
}

// ── 5/6. UAT test cases — AI rows + "+ scenario", decided row by row ──
async function renderTestCases(el) {
  const cases = await api('GET', `/api/onboardings/${S.caseId}/uat/test-cases`);
  const st = state();
  const scenarioStates = ['RULE_CONFIG', 'SANITY_CHECK', 'UAT_TC_PREP', 'UAT_TC_REVIEW_CCRE', 'UAT_TC_REVIEW_BUSINESS'];
  const ccre = hasRole(...CCRE);
  const ccreDecides = ccre && scenarioStates.includes(st);
  const bizDecides = isBusiness() && st === 'UAT_TC_REVIEW_BUSINESS';
  const canAdd = (ccre && scenarioStates.includes(st)) || bizDecides;
  const canGenerate = ccre && ['RULE_CONFIG', 'SANITY_CHECK', 'UAT_TC_PREP'].includes(st);
  const pendingStatus = isBusiness() ? 'CCRE_APPROVED' : 'DRAFT';
  const pending = cases.filter((c) => c.status === pendingStatus).length;
  const statusText = { DRAFT: 'Waiting for CCRE', CCRE_APPROVED: 'Waiting for business', BUSINESS_APPROVED: 'Approved — will run', REJECTED: 'Rejected' };
  if (isBusiness() && !cases.length && !bizDecides) {
    return businessWaiting(el, 'Test cases will be shared with you for review once the CCRE team has prepared and approved them.');
  }
  const decideBtns = (c) => {
    if ((ccreDecides && c.status === 'DRAFT') || (bizDecides && c.status === 'CCRE_APPROVED')) {
      return `<div class="ccre-dl"><button class="dhl-btn dhl-btn--ghost ccre-act--approve" data-approve="${esc(c.id)}">&#10003; Approve</button>
        <button class="dhl-btn dhl-btn--ghost ccre-act--reject" data-reject="${esc(c.id)}">&#10005; Reject</button></div>`;
    }
    if (ccre && c.status === 'REJECTED' && ['UAT_TC_PREP', 'UAT_TC_REVIEW_CCRE'].includes(st)) {
      return `<button class="dhl-btn dhl-btn--ghost dhl-btn--sm" data-reopen="${esc(c.id)}">Reopen</button>`;
    }
    return '';
  };
  el.innerHTML = `<h3>UAT test cases</h3>
    <p class="ccre-hint">Every row is approved or rejected on its own — first by the CCRE team, then by the business team. Only rows approved by both are executed.</p>
    <div class="ccre-row ccre-wrap ccre-gap">
      ${canGenerate ? '<button id="tc-gen" class="dhl-btn dhl-btn--ghost">&#129514; Generate test cases (AI)</button>' : ''}
      ${canAdd ? '<button id="tc-add" class="dhl-btn dhl-btn--primary">+ Add scenario</button>' : ''}
      ${(ccreDecides || bizDecides) && pending ? `<button id="tc-all" class="dhl-btn dhl-btn--ghost ccre-act--approve">&#10003; Approve all ${pending} waiting</button>` : ''}
    </div>
    <div id="tc-add-box" class="ccre-card ccre-gap" hidden>
      <label class="ccre-field-label">Describe the scenario in plain words — it is converted into a test case and goes through review</label>
      <textarea id="tc-scenario" class="dhl-textarea ccre-small" placeholder="e.g. A consumer parcel to Germany, duty paid (DDP), worth 80 EUR, must ask for the Power of Attorney."></textarea>
      <button id="tc-convert" class="dhl-btn dhl-btn--primary ccre-gap">Convert to test case</button>
    </div>
    ${table(isBusiness() ? ['Test', 'What is tested', 'Expected outcome', 'Status', 'Decision']
      : ['Test', 'Source', 'Kind', 'What is tested', 'Inputs', 'Expected', 'Status', 'Decision'], cases.map((c) => `<tr>
      <td class="ccre-mono">${esc(c.test_id)}</td>
      ${isBusiness() ? '' : `<td><span class="ccre-badge-src">${esc(c.source || 'AI')}</span></td><td>${esc(c.kind)}</td>`}
      <td>${esc(c.business_summary)}</td>
      ${isBusiness() ? '' : `<td>${esc((c.input_conditions || []).map(cond).join('; '))}</td>`}
      <td>${c.expected_case_created ? `${esc(c.expected_requirement || '')} is requested` : `${esc(c.expected_requirement || 'Nothing')} is not requested`}</td>
      <td>${esc(statusText[c.status] || c.status)}${c.review_comment ? `<div class="ccre-hint">${esc(c.review_comment)}</div>` : ''}</td>
      <td>${decideBtns(c)}</td></tr>`))}`;
  const decide = (body) => api('POST', `/api/onboardings/${S.caseId}/uat/test-cases/decide`, body);
  if ($('tc-gen')) $('tc-gen').onclick = () => run('Generate', async () => {
    const res = await api('POST', `/api/onboardings/${S.caseId}/uat/test-cases/generate`, {});
    toast(`${res.length} AI test case(s) added for review.`);
    await refreshCase();
  });
  if ($('tc-add')) $('tc-add').onclick = () => { $('tc-add-box').hidden = !$('tc-add-box').hidden; $('tc-scenario').focus(); };
  if ($('tc-convert')) $('tc-convert').onclick = () => run('Convert scenario', async () => {
    const text = $('tc-scenario').value.trim();
    if (text.length < 5) throw new Error('Describe the scenario first.');
    $('tc-convert').disabled = true;
    const res = await api('POST', `/api/onboardings/${S.caseId}/uat/test-cases/scenario`, { text });
    toast(`${res.length} test case(s) created from your scenario — waiting for review.`);
    await refreshCase();
  });
  if ($('tc-all')) $('tc-all').onclick = () => run('Approve all', async () => {
    await decide({ all_pending: true, approve: true });
    await refreshCase();
  });
  el.querySelectorAll('[data-approve]').forEach((b) => { b.onclick = () => run('Approve', async () => {
    await decide({ ids: [b.dataset.approve], approve: true }); await refreshCase(); }); });
  el.querySelectorAll('[data-reject]').forEach((b) => { b.onclick = () => run('Reject', async () => {
    const v = await dialog('Reject test case', '<label class="ccre-field-label">Reason (required)</label><textarea class="dhl-textarea ccre-small" name="comment" required></textarea>', 'Reject');
    if (!v) return;
    await decide({ ids: [b.dataset.reject], approve: false, comment: v.comment });
    await refreshCase(); }); });
  el.querySelectorAll('[data-reopen]').forEach((b) => { b.onclick = () => run('Reopen', async () => {
    await api('POST', `/api/uat/test-cases/${b.dataset.reopen}/reopen`); await refreshCase(); }); });
}

// ── 7. UAT execution (results only; evidence is downloaded) ──
async function download(path, fallbackName) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (S.me && S.me.dev) headers['X-CCRE-Role'] = S.devRole;
  const resp = await fetch(path, { headers });
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    try { msg = (await resp.json()).detail || msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  const blob = await resp.blob();
  const cd = resp.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename="([^"]+)"/);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function resultRows(results, analyse) {
  return results.map((r) => {
    const cmp = r.comparison;
    const compareCell = cmp ? (cmp.error ? `<span class="ccre-diff">${esc(cmp.endpoint)}: error</span>`
      : cmp.identical ? `<span class="ccre-same">Same as ${esc(cmp.endpoint)}</span>`
      : `<span class="ccre-diff">${esc(cmp.differences)} difference(s) vs ${esc(cmp.endpoint)}</span>`) : '—';
    return `<tr>
      <td class="ccre-mono">${esc(r.test_id)}</td>
      <td>${esc(r.business_summary || '')}</td>
      <td><span class="ccre-verdict ccre-verdict--${esc(r.verdict)}">${esc(r.verdict)}</span></td>
      <td>${esc(isBusiness() ? (r.business_explanation || '') : (r.reason || ''))}
        ${r.analysis ? `<div class="ccre-card ccre-gap"><strong>Likely cause:</strong> ${esc(r.analysis.likely_cause)}<br>
          <strong>Next:</strong> ${esc(r.analysis.recommended_action)}</div>` : ''}
        ${analyse && r.verdict !== 'PASS' && !r.analysis ? `<button class="dhl-btn dhl-btn--ghost dhl-btn--sm ccre-gap" data-analyse="${esc(r.id)}">Analyse failure (AI)</button>` : ''}</td>
      <td>${compareCell}</td>
      <td><div class="ccre-dl">
        <button class="dhl-btn dhl-btn--ghost" data-dl="${esc(r.id)}" data-part="request">Request</button>
        <button class="dhl-btn dhl-btn--ghost" data-dl="${esc(r.id)}" data-part="response">Response</button>
        ${cmp ? `<button class="dhl-btn dhl-btn--ghost" data-dl="${esc(r.id)}" data-part="compare">${esc(cmp.endpoint)}</button>` : ''}
      </div></td></tr>`;
  });
}

function runsHtml(runs, analyse) {
  if (!runs.length) return '<p class="ccre-hint">No UAT run yet.</p>';
  return runs.map((r) => `<div class="ccre-card"><div class="ccre-row ccre-space">
      <strong>Cycle ${r.cycle} · ${esc(r.executor)}</strong>
      <span><span class="ccre-verdict ccre-verdict--PASS">${r.passed} passed</span> ·
        <span class="ccre-verdict ccre-verdict--FAIL">${r.failed} failed</span> · ${r.errors} errors
        <button class="dhl-btn dhl-btn--primary dhl-btn--sm" data-dlrun="${esc(r.id)}">&#11015; Download all (zip)</button></span></div>
      ${table(['Test', 'What is tested', 'Result', 'Why', 'Environment comparison', 'Download'], resultRows(r.results, analyse))}</div>`).join('');
}

function wireResults(el) {
  el.querySelectorAll('[data-analyse]').forEach((b) => {
    b.onclick = () => run('Failure analysis', async () => {
      await api('POST', `/api/uat/results/${b.dataset.analyse}/analyse`);
      await renderStage();
    });
  });
  el.querySelectorAll('[data-dl]').forEach((b) => {
    b.onclick = () => run('Download', () => download(`/api/uat/results/${b.dataset.dl}/download?part=${b.dataset.part}`,
      `${b.dataset.part}.json`));
  });
  el.querySelectorAll('[data-dlrun]').forEach((b) => {
    b.onclick = () => run('Download', () => download(`/api/uat/runs/${b.dataset.dlrun}/download`, 'uat_run.zip'));
  });
}

async function renderExecution(el) {
  if (isBusiness()) return businessWaiting(el, 'The CCRE team is executing the approved test cases.');
  const canRun = state() === 'UAT_EXECUTION' && hasRole(...CCRE);
  const [templates, runs, targets] = await Promise.all([api('GET', '/api/uat/templates'),
    api('GET', `/api/onboardings/${S.caseId}/uat/runs`),
    hasRole(...CCRE) ? api('GET', '/api/uat/endpoints') : Promise.resolve([])]);
  const tplOptions = templates.map((t) =>
    `<option value="${esc(t.id)}" ${t.country === S.overview.country ? 'selected' : ''}>${esc(t.name)}${t.country ? ' · ' + esc(t.country) : ''}</option>`).join('');
  const epOptions = targets.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
  el.innerHTML = `<h3>UAT execution</h3>
    ${canRun ? `<div class="ccre-card"><div class="ccre-run-bar">
        <div><label class="ccre-field-label">Run against</label><select id="run-ep" class="dhl-input">
          ${epOptions}<option value="">Built-in mock (offline demo)</option></select></div>
        <div><label class="ccre-field-label">Compare with (optional)</label><select id="run-cmp" class="dhl-input">
          <option value="">— no comparison —</option>${epOptions}</select></div>
        <div><label class="ccre-field-label">Sample payload</label><select id="tpl" class="dhl-input">${tplOptions}</select></div>
        <button id="run-uat" class="dhl-btn dhl-btn--primary">&#9654; Run UAT</button>
      </div>
      ${targets.length ? '' : '<p class="ccre-hint">No endpoints yet — an admin adds them under Admin → UAT execution endpoints.</p>'}
      <details class="ccre-details ccre-gap"><summary>Upload sample payload files (JSON)</summary>
        <div class="ccre-row ccre-gap"><input id="tpl-files" type="file" accept=".json" multiple class="dhl-input">
          <input id="tpl-country" class="dhl-input ccre-narrow" maxlength="2" placeholder="CC" value="${esc(S.overview.country)}">
          <button id="tpl-upload" class="dhl-btn dhl-btn--ghost">Upload</button></div></details>
    </div>` : '<p class="ccre-hint">Execution is available while the onboarding is in “UAT execution”.</p>'}
    <h4>Results</h4>${runsHtml(runs, false)}`;
  if ($('run-uat')) {
    $('run-uat').onclick = () => run('UAT run', async () => {
      $('run-uat').disabled = true;
      $('run-uat').textContent = 'Running…';
      const res = await api('POST', `/api/onboardings/${S.caseId}/uat/runs`, {
        template_id: $('tpl').value || null, endpoint_id: $('run-ep').value || null,
        compare_endpoint_id: $('run-cmp').value || null });
      toast(`UAT finished: ${res.run.passed} passed, ${res.run.failed} failed, ${res.run.errors} errors.`);
      await refreshCase();
    });
  }
  if ($('tpl-upload')) {
    $('tpl-upload').onclick = () => run('Upload', async () => {
      const files = Array.from($('tpl-files').files || []);
      if (!files.length) throw new Error('Choose one or more JSON files.');
      for (const f of files) {
        await api('POST', '/api/uat/templates', { name: f.name.replace(/\.json$/i, ''),
          country: $('tpl-country').value || null, body: await f.text() });
      }
      toast(`${files.length} sample payload(s) uploaded.`);
      await renderStage();
    });
  }
  wireResults(el);
}

// ── 8. UAT review + sign-off ─────────────────────────────────
async function renderResults(el) {
  const runs = await api('GET', `/api/onboardings/${S.caseId}/uat/runs`);
  if (isBusiness()) {
    if (!runs.length) return businessWaiting(el, 'The results will be shared with you after the CCRE team has reviewed them.');
    el.innerHTML = `<h3>UAT results for your sign-off</h3>
      <p>${runs[0].passed} of ${runs[0].results.length} test cases behaved as expected. Download the requests and responses to review, then sign off with the button above or reject with a reason.</p>
      ${runsHtml(runs.slice(0, 1), false)}`;
    wireResults(el);
    return;
  }
  el.innerHTML = `<h3>UAT review and sign-off</h3>
    <p class="ccre-hint">The CCRE team reviews first. Failures → analyse → “Failures found — correct the M2C” restarts the cycle at rule config. All passed → CCRE accepts → business signs off.</p>
    ${runsHtml(runs.slice(0, 1), hasRole(...CCRE))}
    ${runs.length > 1 ? `<details class="ccre-details"><summary>Earlier cycles (${runs.length - 1})</summary>${runsHtml(runs.slice(1), false)}</details>` : ''}`;
  wireResults(el);
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

// ── Admin: UAT execution endpoints ───────────────────────────
const EP_FIELDS = { url: 'ep-url', method: 'ep-method', auth_header: 'ep-auth', timeout_seconds: 'ep-timeout',
  groups_path: 'ep-groups', case_flag_path: 'ep-case', status_path: 'ep-status', status_ok_value: 'ep-ok',
  compare_path: 'ep-compare' };
let EP_PRESETS = {};
let EP_LIST = [];

function fillEndpointForm(e) {
  $('ep-id').value = e ? e.id : '';
  $('ep-name').value = e ? e.name : '';
  Object.entries(EP_FIELDS).forEach(([k, id]) => { $(id).value = e && e[k] !== null && e[k] !== undefined ? e[k] : ''; });
  if (!e) { $('ep-method').value = 'POST'; $('ep-auth').value = 'x-api-key'; $('ep-timeout').value = 30; }
  $('ep-headers').value = JSON.stringify((e && e.extra_headers) || { 'Content-Type': 'application/json' });
  $('ep-active').value = e && !e.active ? 'false' : 'true';
  $('ep-secret').value = '';
  $('ep-secret').placeholder = e && e.secret_set ? `stored (${e.secret_hint}) — leave empty to keep` : 'API key';
  $('ep-clear-secret').checked = false;
  $('ep-save').textContent = e ? 'Update endpoint' : 'Save endpoint';
}

async function renderEndpoints() {
  const [presets, endpoints, templates] = await Promise.all([
    api('GET', '/api/admin/endpoint-presets'), api('GET', '/api/admin/endpoints'), api('GET', '/api/uat/templates')]);
  EP_PRESETS = presets;
  EP_LIST = endpoints;
  $('ep-preset').innerHTML = '<option value="">— choose to fill the response paths —</option>'
    + Object.keys(presets).map((n) => `<option>${esc(n)}</option>`).join('');
  const tplOptions = templates.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
  $('ep-table').innerHTML = table(['Name', 'URL', 'Credential', 'Active', 'Test with sample', ''], endpoints.map((e) => `<tr data-ep="${esc(e.id)}">
    <td><strong>${esc(e.name)}</strong></td><td class="ccre-mono">${esc(e.method)} ${esc(e.url)}</td>
    <td>${e.secret_set ? `${esc(e.auth_header)}: ${esc(e.secret_hint)}` : '<span class="ccre-hint">none</span>'}</td>
    <td>${e.active ? 'yes' : 'no'}</td>
    <td><div class="ccre-row"><select class="dhl-input" data-tpl>${tplOptions}</select>
      <button class="dhl-btn dhl-btn--ghost dhl-btn--sm" data-test>Test</button></div><div class="ccre-hint" data-test-out></div></td>
    <td><button class="dhl-btn dhl-btn--ghost dhl-btn--sm" data-edit>Edit</button>
      <button class="dhl-btn dhl-btn--ghost dhl-btn--sm" data-del>Delete</button></td></tr>`));
  $('ep-table').querySelectorAll('tr[data-ep]').forEach((tr) => {
    const id = tr.dataset.ep;
    tr.querySelector('[data-edit]').onclick = () => { fillEndpointForm(EP_LIST.find((x) => x.id === id)); $('ep-form').scrollIntoView(); };
    tr.querySelector('[data-del]').onclick = () => run('Delete endpoint', async () => {
      const v = await dialog('Delete endpoint', '<p>Delete this endpoint and its stored credential?</p>', 'Delete');
      if (!v) return;
      await api('DELETE', `/api/admin/endpoints/${id}`);
      toast('Endpoint deleted.');
      await renderEndpoints();
    });
    tr.querySelector('[data-test]').onclick = () => run('Test endpoint', async () => {
      const out = tr.querySelector('[data-test-out]');
      out.textContent = 'Sending…';
      const r = await api('POST', `/api/admin/endpoints/${id}/test`, { template_id: tr.querySelector('[data-tpl]').value || null });
      out.textContent = r.reachable
        ? `HTTP ${r.status} in ${r.latency_ms} ms — response ${r.response_readable ? 'readable' : 'not readable with the paths'}. ${r.check.join(' ')}`
        : `Not reachable: ${r.error}`;
    });
  });
}

$('ep-preset').onchange = (e) => {
  const p = EP_PRESETS[e.target.value];
  if (!p) return;
  Object.entries(EP_FIELDS).forEach(([k, id]) => { if (p[k] !== undefined) $(id).value = p[k]; });
  $('ep-headers').value = JSON.stringify(p.extra_headers || {});
  toast(p.help || 'Preset applied.');
};
$('ep-reset').onclick = () => fillEndpointForm(null);
$('ep-form').onsubmit = (e) => {
  e.preventDefault();
  run('Save endpoint', async () => {
    let headers;
    try { headers = JSON.parse($('ep-headers').value || '{}'); } catch { throw new Error('Extra headers must be JSON, e.g. {"Content-Type": "application/json"}'); }
    const body = { name: $('ep-name').value.trim(), extra_headers: headers, active: $('ep-active').value === 'true' };
    Object.entries(EP_FIELDS).forEach(([k, id]) => { body[k] = $(id).value; });
    body.timeout_seconds = Number(body.timeout_seconds || 30);
    if ($('ep-secret').value) body.secret = $('ep-secret').value;
    const id = $('ep-id').value;
    if (id) {
      body.clear_secret = $('ep-clear-secret').checked;
      await api('PATCH', `/api/admin/endpoints/${id}`, body);
    } else {
      await api('POST', '/api/admin/endpoints', body);
    }
    toast('Endpoint saved. The credential is stored encrypted.');
    fillEndpointForm(null);
    await renderEndpoints();
  });
};

// ── Admin: email settings and sent-mail log ──────────────────
async function renderMail() {
  const [m, log] = await Promise.all([api('GET', '/api/admin/mail'), api('GET', '/api/admin/notifications')]);
  $('mail-host').value = m.host || '';
  $('mail-port').value = m.port;
  $('mail-security').value = m.security;
  $('mail-user').value = m.username || '';
  $('mail-pass').value = '';
  $('mail-pass').placeholder = m.password_set ? 'stored — leave empty to keep' : 'password';
  $('mail-from').value = m.from_address;
  $('mail-url').value = m.public_url;
  $('mail-mode').textContent = m.mode === 'smtp' ? `Sending through ${m.host}.` : `No SMTP host — emails are written to ${m.outbox_folder}.`;
  $('mail-log').innerHTML = table(['When', 'Type', 'Subject', 'To', 'Cc', 'Status'], log.map((n) => `<tr>
    <td>${esc((n.at || '').slice(0, 16).replace('T', ' '))}</td><td>${esc(n.kind)}</td>
    <td><details class="ccre-details"><summary>${esc(n.subject)}</summary><pre class="ccre-pre">${esc(n.body)}</pre></details></td>
    <td>${esc(n.to.join(', '))}</td><td>${esc(n.cc.length ? n.cc.length + ' user(s)' : '—')}</td>
    <td>${esc(n.status)}${n.error ? `<div class="ccre-inline-error">${esc(n.error)}</div>` : ''}</td></tr>`));
}

$('mail-form').onsubmit = (e) => {
  e.preventDefault();
  run('Save email settings', async () => {
    const body = { host: $('mail-host').value.trim() || null, port: Number($('mail-port').value || 587),
      security: $('mail-security').value, username: $('mail-user').value.trim() || null,
      from_address: $('mail-from').value.trim(), public_url: $('mail-url').value.trim() };
    if ($('mail-pass').value) body.password = $('mail-pass').value;
    await api('PUT', '/api/admin/mail', body);
    toast('Email settings saved.');
    await renderMail();
  });
};
$('mail-test').onclick = () => run('Test email', async () => {
  const r = await api('POST', '/api/admin/mail/test', { to: $('mail-test-to').value.trim() });
  toast(`Test email: ${r.status}${r.error ? ' — ' + r.error : ''}`, r.status === 'FAILED');
  await renderMail();
});

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

// ── Admin: beta files (config packages) ──────────────────────
const PKG_STATUS = { ACTIVE: 'ccre-st--ok', REVIEWED: 'ccre-st--warn', SUPERSEDED: '', REJECTED: 'ccre-st--err' };

async function uploadFile(path, file) {
  const fd = new FormData();
  fd.append('file', file);
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, { method: 'POST', headers, body: fd });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Upload failed (${resp.status})`);
  return data;
}

function pkgReviewHtml(u) {
  const s = u.summary || {};
  const sev = { error: 'ccre-issue--error', warning: 'ccre-issue--warning', info: 'ccre-issue--package' };
  const w = u.workbook;
  const ch = u.changes_vs_active;
  return `${kv([['File', u.filename], ['Version (changelog)', `${s.declared_version || '—'} released ${s.release_date || '—'}`],
      ['Loaded as', u.version], ['Groups · mappings · countries', `${s.groups} · ${s.mappings} · ${s.countries}`],
      ['Definitions · fields', `${s.definitions} · ${s.attributes}`], ['SHA-256', u.sha256]])}
    ${(s.pending_in_changelog || []).length ? `<h4>Still "Unreleased" in the changelog</h4>${list(s.pending_in_changelog)}` : ''}
    <h4>Review (${u.ok ? 'no blocking problems' : 'blocking problems — cannot be activated'})</h4>
    <ul class="ccre-issues">${(u.findings || []).map((f) => `<li class="${sev[f.severity]}"><b>${esc(f.severity)}</b> ${esc(f.message)}
      ${f.details.length ? `<details class="ccre-details"><summary>${f.count} item(s)</summary>${list(f.details.map(String))}</details>` : ''}</li>`).join('') || '<li class="ccre-issue--package">Nothing to report.</li>'}</ul>
    ${w ? `<h4>Compared with the M2C workbook (${esc(w.workbook_version || '—')})</h4>
      ${kv([['Same definition', w.same], ['Different definition', w.definition_differs.length], ['Only in the workbook', w.workbook_only.length],
        ['Only in the package', w.package_only.length], ['Countries only in the workbook', w.countries_only_in_workbook.join(', ') || '—']])}` : ''}
    ${ch ? `<h4>Changes against the active package (${esc(ch.active_version || 'none')})</h4>
      ${kv([['Mappings added', ch.added.length], ['Mappings removed', ch.removed.length], ['Countries added', ch.countries_added.join(', ') || '—'],
        ['Countries removed', ch.countries_removed.join(', ') || '—']])}` : ''}`;
}

async function renderPackages() {
  const data = await api('GET', '/api/admin/packages');
  $('pkg-active').innerHTML = data.active_upload_id
    ? `<span class="ccre-st ccre-st--ok">Active: ${esc(data.active_version)}</span>`
    : data.legacy_active ? `<span class="ccre-st ccre-st--warn">In use: ${esc(data.active_version)} (loaded before uploads existed — upload and activate a beta file to make the choice explicit)</span>`
      : '<span class="ccre-st ccre-st--err">No config package loaded yet</span>';
  $('pkg-list').innerHTML = data.uploads.length ? table(['File', 'Version', 'Released', 'Uploaded', 'Review', 'Status', ''],
    data.uploads.map((u) => `<tr><td>${esc(u.filename)}</td><td>${esc(u.version)}</td><td>${esc(u.release_date || '—')}</td>
      <td>${esc(u.uploaded_by)}<br><small>${esc(u.uploaded_at.slice(0, 16).replace('T', ' '))}</small></td>
      <td>${['error', 'warning', 'info'].map((k) => (u.counts[k] ? `<span class="ccre-st ${k === 'error' ? 'ccre-st--err' : k === 'warning' ? 'ccre-st--warn' : ''}">${u.counts[k]} ${k}</span>` : '')).join(' ') || '&#10003;'}</td>
      <td><span class="ccre-st ${PKG_STATUS[u.status] || ''}">${esc(u.status)}</span>${u.decision_note ? `<br><small>${esc(u.decision_note)}</small>` : ''}</td>
      <td><button class="dhl-btn dhl-btn--ghost dhl-btn--sm" data-pkg-view="${esc(u.id)}">Review</button>
        ${u.ok && u.status !== 'ACTIVE' && u.status !== 'REJECTED' ? `<button class="dhl-btn dhl-btn--primary dhl-btn--sm" data-pkg-act="${esc(u.id)}">Activate</button>` : ''}
        ${u.status === 'REVIEWED' ? `<button class="dhl-btn dhl-btn--ghost dhl-btn--sm ccre-act--reject" data-pkg-rej="${esc(u.id)}">Reject</button>` : ''}</td></tr>`))
    : '<p class="ccre-hint">No beta file uploaded yet.</p>';
  $('pkg-upload').onclick = () => run('Upload', async () => {
    const f = $('pkg-file').files[0];
    if (!f) { toast('Choose the .zip first.', true); return; }
    $('pkg-upload').disabled = true;
    try {
      const u = await uploadFile('/api/admin/packages', f);
      let msg = 'Uploaded and reviewed — check the review, then activate.';
      if (u.already_uploaded) msg = 'This exact file was uploaded before — showing its review.';
      else if (!u.ok) msg = 'Uploaded, but the review found blocking problems.';
      toast(msg, !u.ok);
      await renderPackages();
      await showPackage(u.id);
    } finally { $('pkg-upload').disabled = false; }
  });
  $('pkg-list').querySelectorAll('[data-pkg-view]').forEach((b) => { b.onclick = () => run('Review', () => showPackage(b.dataset.pkgView)); });
  $('pkg-list').querySelectorAll('[data-pkg-act]').forEach((b) => {
    b.onclick = () => run('Activate', async () => {
      const v = await dialog('Activate this beta file?', `<p>From now on every check — package coverage, the sanity check, rule configuration, the mapping explorer — uses this package. The previous one stays available.</p>
        <label class="ccre-field-label">Note (optional, e.g. the Support ticket)</label><input class="dhl-input" name="note">`, 'Activate');
      if (!v) return;
      await api('POST', `/api/admin/packages/${b.dataset.pkgAct}/activate`, { note: v.note || '' });
      toast('Beta file activated.');
      await renderPackages();
    });
  });
  $('pkg-list').querySelectorAll('[data-pkg-rej]').forEach((b) => {
    b.onclick = () => run('Reject', async () => {
      const v = await dialog('Reject this beta file', '<label class="ccre-field-label">Why (required)</label><textarea class="dhl-textarea ccre-small" name="note" required></textarea>', 'Reject');
      if (!v) return;
      await api('POST', `/api/admin/packages/${b.dataset.pkgRej}/reject`, { note: v.note });
      await renderPackages();
    });
  });
}

async function showPackage(id) {
  const u = await api('GET', `/api/admin/packages/${id}`);
  await dialog(`Review — ${u.filename}`, `<div class="ccre-pkg-review">${pkgReviewHtml(u)}</div>`, 'Close');
}

// ── Reference: mapping explorer ──────────────────────────────
async function renderReference() {
  const [ref, drift] = await Promise.all([api('GET', '/api/reference/countries'), api('GET', '/api/reference/drift')]);
  S.ref = ref;
  $('ref-active').innerHTML = `<span class="ccre-st ccre-st--ok">Config package in use: ${esc(ref.package_version || 'none')}</span>
    <span class="ccre-st">M2C workbook: ${esc(drift.workbook_version || 'none')}</span>`;
  const cSel = $('ref-country');
  cSel.innerHTML = ref.countries.map((c) => `<option>${esc(c.country)}</option>`).join('');
  const where = (g) => {
    if (g.in_workbook && g.in_package) return 'workbook + package';
    return g.in_workbook ? 'workbook only' : 'package only';
  };
  const fillGroups = () => {
    const c = ref.countries.find((x) => x.country === cSel.value);
    $('ref-group').innerHTML = (c ? c.groups : []).map((g) => `<option value="${esc(g.code)}">${esc(g.code)} — ${where(g)}</option>`).join('');
  };
  cSel.onchange = fillGroups;
  if (S.refPick) cSel.value = S.refPick[0];
  fillGroups();
  if (S.refPick) $('ref-group').value = S.refPick[1];
  $('ref-trace').onclick = () => run('Trace', traceReference);
  const t = drift.total;
  $('ref-drift').innerHTML = `<p class="ccre-hint">Each (country, group) in either source: <b>same</b> definition in both, a <b>different</b> definition, or present on one side only. A different definition usually means the workbook was updated for a newer beta file.</p>
    ${kv([['Same', t.same], ['Different definition', t.differs], ['Only in the workbook', t.workbook_only], ['Only in the package', t.package_only]])}
    ${table(['Country', 'Same', 'Different definition', 'Workbook only', 'Package only', ''], drift.countries.map((r) => `<tr>
      <td><b>${esc(r.country)}</b></td><td>${r.same}</td><td>${r.differs ? `<span class="ccre-st ccre-st--warn">${r.differs}</span>` : 0}</td>
      <td>${r.workbook_only ? `<span class="ccre-st ccre-st--err">${r.workbook_only}</span>` : 0}</td><td>${r.package_only}</td>
      <td><button class="dhl-btn dhl-btn--ghost ccre-small-btn" data-ref-c="${esc(r.country)}">Pick</button></td></tr>`))}`;
  $('ref-drift').querySelectorAll('[data-ref-c]').forEach((b) => {
    b.onclick = () => { cSel.value = b.dataset.refC; fillGroups(); window.scrollTo({ top: 0, behavior: 'smooth' }); };
  });
}

async function traceReference() {
  const c = $('ref-country').value;
  const g = $('ref-group').value;
  if (!c || !g) return;
  S.refPick = [c, g];
  const t = await api('GET', `/api/reference/trace?country=${encodeURIComponent(c)}&group=${encodeURIComponent(g)}`);
  const icon = { ok: ['ccre-st--ok', '&#10003;'], missing: ['ccre-st--err', '&#10005;'], na: ['', '—'] };
  const chain = t.checks.map((x, i) => `<div class="ccre-chain-step ccre-chain-step--${x.status}">
      <div class="ccre-sanity-num">${i + 1}</div>
      <div><div class="ccre-row ccre-space ccre-wrap"><strong>${esc(x.title)}</strong><span class="ccre-st ${icon[x.status][0]}">${icon[x.status][1]}</span></div>
      <div class="ccre-mono ccre-small-text">${esc(x.detail)}</div></div></div>`).join('');
  const defs = t.definitions.map((d) => `<details class="ccre-details ccre-card" ${d.in_package_mapping ? 'open' : ''}>
      <summary><b>${esc(d.cmpt_nm || '(not shipped)')}</b> — ${esc(d.name || d.sir_id)}
        ${d.in_package_mapping ? '<span class="ccre-st ccre-st--ok">package mapping</span>' : ''}
        ${d.in_workbook_mapping ? '<span class="ccre-st">workbook mapping</span>' : ''}
        ${d.shipped ? '' : '<span class="ccre-st ccre-st--err">file not in package</span>'}</summary>
      <p class="ccre-hint ccre-mono">${esc(d.sir_id)}</p>
      ${d.attributes.length ? table(['Field', 'Entity', 'Mandatory', 'Goes to (message position)'], d.attributes.map((a) => `<tr>
        <td>${esc(a.name || a.att_id)}<br><small class="ccre-mono">${esc(a.att_id)}</small></td><td><small>${esc(a.entity)}</small></td>
        <td>${a.mandatory ? 'yes' : ''}</td><td class="ccre-mono"><small>${esc(a.message_positions.join(' · ') || '—')}</small></td></tr>`)) : '<p class="ccre-hint">No fields (definition not shipped by the active package).</p>'}
    </details>`).join('');
  const fieldsCell = (b) => (b.whole_definition ? '<i>the whole definition</i>' : b.attributes.map((a) => `${a.found ? '&#10003;' : '&#10005;'} ${esc(a.name || a.att_id)}${a.message_positions.length ? ` <small class="ccre-mono">&rarr; ${esc(a.message_positions[0])}</small>` : ''}`).join('<br>'));
  const binds = t.bindings.length ? table(['Import row', 'Definition', 'Fields asked for (SIR Reference)', 'Waived if whitelisted', 'Waived to validate', 'Service code'],
    t.bindings.map((b) => `<tr><td>${esc(b.rule_row)}</td><td>${esc(b.cmpt_nm || '')}<br><small class="ccre-mono">${esc(b.sir_id || '')}</small>
      ${b.definition_mapped ? '' : '<br><span class="ccre-st ccre-st--err">not the definition the package maps</span>'}</td>
      <td>${fieldsCell(b)}</td>
      <td>${b.waived_if_whitelisted ? 'Y' : ''}</td><td>${b.waived_to_validate ? 'Y' : ''}</td><td>${esc(b.check_service_code || '')}</td></tr>`))
    : '<p class="ccre-hint">No SIR Reference lines for this rule.</p>';
  const rules = t.rules.length ? table(['Import row', 'B2B/B2C', 'Value band', 'Other Logic'], t.rules.map((r) => `<tr><td>${r.row_no}</td><td>${esc(r.shipment_type || '')}</td>
      <td>${esc(r.min_value ?? '…')} – ${esc(r.max_value ?? '…')} ${esc(r.currency || '')}</td><td class="ccre-mono"><small>${esc(r.other_logic || '—')}</small></td></tr>`)) : '';
  $('ref-result').innerHTML = `<div class="ccre-sanity-banner ${t.can_raise ? 'ccre-sanity-banner--ok' : 'ccre-sanity-banner--bad'}"><b>${esc(t.country)} · ${esc(t.group)}:</b> ${esc(t.verdict)}</div>
    <div class="ccre-chain">${chain}</div>
    <h4>When — the M2C Import rule(s)</h4>${rules || '<p class="ccre-hint">No Import rule.</p>'}
    <h4>What — the definition(s) and their fields</h4>${defs || '<p class="ccre-hint">No definition on either side.</p>'}
    <h4>Which fields are asked — SIR Reference</h4>${binds}`;
}
