/* ============================================================
   CCRE Rules Intelligence — single-page UI
   Talks only to /api/* on the same origin.
   ============================================================ */
'use strict';

const $ = (id) => document.getElementById(id);

// ── State ────────────────────────────────────────────────────
const state = {
  cases: [],
  ruleSets: [],
  caseId: null,
  ruleSetId: null,
  interpretation: null,   // last interpretation for the selected case
  proposalId: null,       // proposal awaiting a decision
  sessionId: null,
  busy: false,
};

// ── Helpers ──────────────────────────────────────────────────
function escHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  const text = await resp.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
  if (!resp.ok) {
    const d = data && data.detail;
    const msg = typeof d === 'string' ? d
      : d && d.message ? `${d.message}${d.reasons ? ' — ' + d.reasons.join('; ') : ''}`
      : Array.isArray(d) ? d.map((e) => e.msg).join('; ')
      : `HTTP ${resp.status}`;
    throw new Error(msg);
  }
  return data;
}

function setBusy(label) {
  state.busy = !!label;
  $('busy').textContent = label ? `⏳ ${label}…` : '';
  refreshButtons();
}

function showError(msg) {
  $('error-msg').textContent = msg;
  $('error-box').classList.add('dhl-error-box--show');
}
function clearError() { $('error-box').classList.remove('dhl-error-box--show'); }

function showResult(title, html) {
  $('output-title').textContent = title;
  $('output-empty').style.display = 'none';
  const el = $('result');
  el.innerHTML = html;
  el.hidden = false;
  el.scrollTop = 0;
}

function markStep(id, how) {
  const el = $(id);
  if (!el) return;
  el.classList.remove('dhl-step--active', 'dhl-step--done');
  if (how) el.classList.add(how === 'done' ? 'dhl-step--done' : 'dhl-step--active');
}

async function run(label, step, fn) {
  if (state.busy) return;
  clearError();
  setBusy(label);
  if (step) markStep(step, 'active');
  try {
    await fn();
    if (step) markStep(step, 'done');
  } catch (err) {
    if (step) markStep(step, null);
    showError(err.message || String(err));
  } finally {
    setBusy(null);
  }
}

function list(items, cls) {
  if (!items || !items.length) return '<p class="ccre-hint">None.</p>';
  return `<ul class="ccre-list">${items.map((i) => `<li class="${cls || ''}">${escHtml(i)}</li>`).join('')}</ul>`;
}

function kv(pairs) {
  return `<dl class="ccre-kv">${pairs.map(([k, v]) =>
    `<dt>${escHtml(k)}</dt><dd>${v === null || v === undefined || v === '' ? '—' : escHtml(v)}</dd>`).join('')}</dl>`;
}

function pre(obj) {
  return `<pre class="ccre-pre">${escHtml(typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2))}</pre>`;
}

// ── Header status ────────────────────────────────────────────
async function loadStatus() {
  const badge = $('status-badge');
  try {
    const [health, agents] = await Promise.all([api('GET', '/api/health'), api('GET', '/api/agents')]);
    const pkgs = health.packages || [];
    badge.className = 'dhl-badge dhl-badge--online';
    $('status-label').textContent =
      `Online · LLM ${agents.llm_mode}${agents.available ? '' : ' (off)'} · ${pkgs.length} package(s)`;
    if (pkgs.length) markStep('pl-ingest', 'done');
  } catch (err) {
    badge.className = 'dhl-badge dhl-badge--error';
    $('status-label').textContent = 'Offline';
  }
}

// ── Cases & rule sets ────────────────────────────────────────
async function loadCases(selectId) {
  state.cases = await api('GET', '/api/cases');
  const sel = $('case-select');
  sel.innerHTML = state.cases.length
    ? state.cases.map((c) => `<option value="${escHtml(c.id)}">${escHtml(c.code)} · ${escHtml(c.ctry_cd)} · ${escHtml(c.state)}</option>`).join('')
    : '<option value="">— create a case first —</option>';
  state.caseId = selectId || (state.cases[0] && state.cases[0].id) || null;
  if (state.caseId) sel.value = state.caseId;
  refreshButtons();
}

async function loadRuleSets(selectId) {
  state.ruleSets = await api('GET', '/api/rule-sets');
  const opts = state.ruleSets.length
    ? state.ruleSets.map((r) => `<option value="${escHtml(r.id)}">${escHtml(r.version)}${r.label ? ' · ' + escHtml(r.label) : ''} · ${r.rule_count} rules${r.sealed ? ' · sealed' : ''}</option>`).join('')
    : '<option value="">— no rule sets loaded —</option>';
  $('ruleset-select').innerHTML = opts;
  $('gate-ruleset').innerHTML = opts;
  state.ruleSetId = selectId || (state.ruleSets[0] && state.ruleSets[0].id) || null;
  if (state.ruleSetId) { $('ruleset-select').value = state.ruleSetId; $('gate-ruleset').value = state.ruleSetId; }
  refreshButtons();
}

function refreshButtons() {
  const b = state.busy;
  const hasReq = $('req-text').value.trim().length > 0;
  $('btn-interpret').disabled = b || !state.caseId || !hasReq;
  $('btn-draft').disabled = b || !state.caseId || (!hasReq && !state.interpretation);
  $('btn-validate').disabled = b || !state.ruleSetId;
  $('btn-tests').disabled = b || !state.ruleSetId;
  $('btn-export').disabled = b || !state.ruleSetId;
  $('btn-analyse').disabled = b || !$('f-test').value.trim();
  $('btn-accept').disabled = b || !state.proposalId;
  $('btn-reject').disabled = b || !state.proposalId;
  $('btn-chat-send').disabled = b || !$('chat-input').value.trim();
}

// ── Renderers ────────────────────────────────────────────────
function renderInterpretation(res) {
  const i = res.interpretation;
  const conds = (i.conditions || []).map((c) =>
    `${c.field} ${c.operator}${c.value !== null && c.value !== undefined ? ' ' + c.value : ''}`);
  return `
    <h3>Requirement reading ${res.needs_clarification
      ? '<span class="dhl-val-chip dhl-val-chip--warn">needs clarification</span>'
      : '<span class="dhl-val-chip dhl-val-chip--pass">clear</span>'}</h3>
    ${kv([['Country', i.country_code], ['Shipment type', i.shipment_type], ['Direction', i.direction],
          ['Requirement groups', (i.requirement_groups || []).join(', ')], ['Confidence', i.confidence],
          ['Expected behaviour', i.expected_behaviour]])}
    <h4>Conditions</h4>${list(conds)}
    <h4>Ambiguities</h4>${list(i.ambiguities, 'ccre-warn')}
    <h4>Missing information</h4>${list(i.missing_information, 'ccre-warn')}
    <h4>Reasoning</h4><p>${escHtml(i.reasoning || '—')}</p>
    <h4>Next</h4><p>${escHtml(res.gate)} Then click <strong>Draft rules</strong>.</p>`;
}

function renderChangeSet(res) {
  const cs = res.change_set;
  const rows = (cs.rules || []).map((r) => `<tr>
      <td>${escHtml(r.ctry_cd)}</td><td>${escHtml(r.sirg_cd || '—')}</td><td>${escHtml(r.shipment_type || '—')}</td>
      <td>${escHtml(r.currency || '—')}</td><td>${escHtml(r.min_value ?? '—')}–${escHtml(r.max_value ?? '—')}</td>
      <td class="ccre-mono">${escHtml(r.other_logic || '—')}</td><td>${escHtml(r.rationale || '')}</td></tr>`).join('');
  const diags = (res.expression_diagnostics || []).map((d) =>
    `Rule ${d.rule_index + 1}: ${[...d.errors, ...d.warnings].join('; ')}`);
  return `
    <h3>${escHtml(cs.summary)} <span class="dhl-val-chip dhl-val-chip--warn">staged · not applied</span></h3>
    <p class="ccre-hint">Proposal <code>${escHtml(res.proposal_id)}</code> — review it, then accept or reject in the panel above.</p>
    <div class="ccre-table-wrap"><table class="ccre-table">
      <thead><tr><th>Country</th><th>Group</th><th>Shipment</th><th>Currency</th><th>Value band</th><th>Other Logic</th><th>Rationale</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <h4>Expression diagnostics</h4>${list(diags, 'ccre-bad')}
    <h4>Risks</h4>${list(cs.risks, 'ccre-warn')}
    <h4>Open questions</h4>${list(cs.open_questions, 'ccre-warn')}`;
}

function renderValidation(rep, heading) {
  const sevCls = { blocker: 'ccre-bad', caution: 'ccre-warn', info: 'ccre-info' };
  const items = (rep.findings || []).map((f) => `<li class="${sevCls[f.severity] || ''}">
      <div class="ccre-finding__head"><span class="ccre-finding__code">${escHtml(f.code)}</span>
      <span class="dhl-val-chip ${f.severity === 'blocker' ? 'dhl-val-chip--fail' : f.severity === 'caution' ? 'dhl-val-chip--warn' : ''}">${escHtml(f.severity)}</span>
      <span class="ccre-finding__where">${escHtml(f.where)}</span></div>
      <div>${escHtml(f.message)}</div>
      ${f.evidence ? `<div class="ccre-finding__evidence">${escHtml(f.evidence)}</div>` : ''}</li>`).join('');
  return `<h3>${escHtml(heading || 'Validation report')} ${rep.clean
      ? '<span class="dhl-val-chip dhl-val-chip--pass">gate OPEN</span>'
      : '<span class="dhl-val-chip dhl-val-chip--fail">gate LOCKED</span>'}</h3>
    <p class="ccre-hint">${(rep.checks_run || []).length} deterministic checks ran. Blockers cannot be waived by any user or agent.</p>
    ${items ? `<ul class="ccre-list">${items}</ul>` : '<p>No findings.</p>'}`;
}

function showMetrics(rep) {
  const cards = [
    { label: 'Blockers', value: rep.blocker_count, cls: rep.blocker_count ? 'dhl-metric-card--red' : 'dhl-metric-card--green' },
    { label: 'To confirm', value: rep.caution_count, cls: rep.caution_count ? 'dhl-metric-card--amber' : 'dhl-metric-card--green' },
    { label: 'Info', value: rep.info_count },
    { label: 'Checks', value: (rep.checks_run || []).length },
    { label: 'Gate', value: rep.clean ? 'OPEN' : 'LOCKED', cls: rep.clean ? 'dhl-metric-card--green' : 'dhl-metric-card--red' },
  ];
  $('metrics-body').innerHTML = cards.map((m) => `<div class="dhl-metric-card${m.cls ? ' ' + m.cls : ''}">
      <div class="dhl-metric-card__value">${escHtml(m.value)}</div>
      <div class="dhl-metric-card__label">${escHtml(m.label)}</div></div>`).join('');
  $('analysis-metrics').classList.add('dhl-analysis-metrics--show');
}

function renderSuite(res) {
  const s = res.suite;
  const rows = (s.cases || []).map((c) => `<tr>
      <td class="ccre-mono">${escHtml(c.test_id)}</td><td>${escHtml(c.kind)}</td><td>${escHtml(c.scenario)}</td>
      <td>${escHtml((c.input_conditions || []).map((i) => `${i.field} ${i.operator} ${i.value ?? ''}`).join('; '))}</td>
      <td>${escHtml(c.expected_requirement || 'none')}</td><td>${c.expected_case_created ? 'yes' : 'no'}</td>
      <td>${escHtml(c.priority)}</td></tr>`).join('');
  return `<h3>${escHtml(s.summary)}</h3>
    <p class="ccre-hint">${res.rules_in_scope} rule(s) in scope · ${escHtml(res.gate)}</p>
    <div class="ccre-table-wrap"><table class="ccre-table">
      <thead><tr><th>Test</th><th>Kind</th><th>Scenario</th><th>Inputs</th><th>Expected group</th><th>Case created</th><th>Priority</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <h4>Uncovered conditions</h4>${list(s.uncovered_conditions, 'ccre-warn')}`;
}

function renderAnalysis(res) {
  const a = res.analysis;
  return `<h3>Failure analysis — ${escHtml(a.test_id)}
      ${a.change_rules ? '<span class="dhl-val-chip dhl-val-chip--fail">rule change suggested</span>'
                       : '<span class="dhl-val-chip dhl-val-chip--pass">no rule change</span>'}</h3>
    ${kv([['Likely cause', a.likely_cause], ['Category', a.category], ['Confidence', a.confidence],
          ['Recommended action', a.recommended_action]])}
    <h4>Evidence</h4>${list(a.evidence)}
    <p class="ccre-hint">${escHtml(res.gate)}</p>`;
}

function renderExport(res) {
  const files = Object.entries(res.files || {}).map(([name, body]) => `<div>
      <div class="ccre-file__name">${escHtml(name)}</div>${pre(body)}</div>`).join('');
  return `<h3>Handover bundle — ${escHtml(res.version)}</h3>
    <p>${escHtml(res.handover_note)}</p>
    <div class="ccre-files">${files}</div>
    <h4>Evidence</h4>${pre(res.evidence)}`;
}

// ── Actions ──────────────────────────────────────────────────
function showGate(proposalId) {
  state.proposalId = proposalId;
  $('gate-panel').classList.toggle('dhl-gate--show', !!proposalId);
  if (proposalId) markStep('pl-gateB', 'active');
  refreshButtons();
}

function wireActions() {
  $('btn-interpret').onclick = () => run('Interpreting requirement', 'pl-interpret', async () => {
    const res = await api('POST', `/api/cases/${state.caseId}/interpret`,
      { requirement_text: $('req-text').value.trim(), actor: $('gate-actor').value.trim() || 'ui' });
    state.interpretation = res.interpretation;
    markStep('pl-gateA', 'active');
    showResult('Requirement interpretation', renderInterpretation(res));
  });

  $('btn-draft').onclick = () => run('Drafting rules', 'pl-draft', async () => {
    const res = await api('POST', `/api/cases/${state.caseId}/draft-rules`, {
      requirement_text: $('req-text').value.trim(),
      interpretation: state.interpretation,
      actor: $('gate-actor').value.trim() || 'ui',
    });
    markStep('pl-gateA', 'done');
    showResult('Proposed change-set', renderChangeSet(res));
    showGate(res.proposal_id);
  });

  const decide = (accept) => run(accept ? 'Accepting proposal' : 'Rejecting proposal', null, async () => {
    const actor = $('gate-actor').value.trim();
    if (!actor) throw new Error('Enter your name — every decision is recorded against a named person.');
    const body = { accept, actor, rule_set_id: $('gate-ruleset').value || null };
    const res = await api('POST', `/api/proposals/${state.proposalId}/decide`, body);
    showGate(null);
    markStep('pl-gateB', 'done');
    if (accept) {
      markStep('pl-validate', 'done');
      showMetrics(res.validation);
      showResult('Proposal accepted — validation', renderValidation(res.validation,
        `${res.rules_created.length} rule(s) written · validation`));
      await loadRuleSets(body.rule_set_id);
    } else {
      showResult('Proposal rejected', '<h3>Proposal rejected</h3><p>No rule was written. The decision is on the audit trail.</p>');
    }
  });
  $('btn-accept').onclick = () => decide(true);
  $('btn-reject').onclick = () => decide(false);

  $('btn-validate').onclick = () => run('Validating', 'pl-validate', async () => {
    const qs = state.caseId ? `?case_id=${encodeURIComponent(state.caseId)}` : '';
    const rep = await api('POST', `/api/rule-sets/${state.ruleSetId}/validate${qs}`);
    showMetrics(rep);
    showResult('Validation report', renderValidation(rep));
  });

  $('btn-tests').onclick = () => run('Designing tests', 'pl-tests', async () => {
    const country = $('rs-country').value.trim().toUpperCase() || null;
    const res = await api('POST', `/api/rule-sets/${state.ruleSetId}/test-suite`, { country, actor: 'ui' });
    showResult('Test suite', renderSuite(res));
  });

  $('btn-export').onclick = () => run('Building export', 'pl-export', async () => {
    const res = await api('GET', `/api/rule-sets/${state.ruleSetId}/export`);
    showResult('Export', renderExport(res));
  });

  $('btn-analyse').onclick = () => run('Analysing failure', 'pl-rca', async () => {
    const res = await api('POST', '/api/failures/analyse', {
      test_id: $('f-test').value.trim(), expected: $('f-expected').value.trim(),
      actual: $('f-actual').value.trim(), details: $('f-details').value.trim(),
      case_id: state.caseId, actor: 'ui',
    });
    showResult('Failure analysis', renderAnalysis(res));
  });

  $('btn-new-case').onclick = () => { $('new-case-form').hidden = !$('new-case-form').hidden; };
  $('btn-create-case').onclick = () => run('Creating case', null, async () => {
    const body = {
      code: $('nc-code').value.trim(),
      ctry_cd: $('nc-country').value.trim().toUpperCase(),
      title: $('nc-title').value.trim(),
    };
    if (!body.code || !body.ctry_cd || !body.title) throw new Error('Case code, country and title are required.');
    const created = await api('POST', '/api/cases', body);
    $('new-case-form').hidden = true;
    await loadCases(created.id);
  });

  $('case-select').onchange = (e) => { state.caseId = e.target.value || null; state.interpretation = null; refreshButtons(); };
  $('ruleset-select').onchange = (e) => { state.ruleSetId = e.target.value || null; refreshButtons(); };
  $('req-text').oninput = () => { $('char-count').textContent = `${$('req-text').value.length} chars`; refreshButtons(); };
  $('f-test').oninput = refreshButtons;

  // Tabs
  document.querySelectorAll('.dhl-tab').forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll('.dhl-tab').forEach((t) => t.classList.remove('dhl-tab--active'));
      document.querySelectorAll('.dhl-tab-panel').forEach((p) => p.classList.remove('dhl-tab-panel--active'));
      tab.classList.add('dhl-tab--active');
      $(`tab-${tab.dataset.tab}`).classList.add('dhl-tab-panel--active');
    };
  });

  $('btn-test-report').onclick = async () => {
    const resp = await fetch('/api/test-report/xlsx', { method: 'HEAD' }).catch(() => null);
    if (resp && resp.ok) { window.location.href = '/api/test-report/xlsx'; }
    else { showError('No test report yet. Run `pytest` in the project folder; it writes test_report.xlsx.'); }
  };
}

// ── Chat popup ───────────────────────────────────────────────
function chatMarkup(text) {
  // Minimal, safe markdown: fenced code, inline code, bold.
  const parts = String(text).split(/```(?:\w+)?\n?([\s\S]*?)```/g);
  return parts.map((p, i) => (i % 2 === 1
    ? `<pre class="ccre-chat-pre">${escHtml(p)}</pre>`
    : escHtml(p).replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>'))).join('');
}

function addChat(role, text, thinking) {
  const box = $('chat-popup-msgs');
  const welcome = box.querySelector('.dhl-chat-welcome');
  if (welcome) welcome.remove();
  const div = document.createElement('div');
  div.className = `dhl-chat-msg dhl-chat-msg--${role}${thinking ? ' dhl-chat-msg--thinking' : ''}`;
  div.innerHTML = `<div class="dhl-chat-msg__label">${role === 'user' ? 'You' : 'CCRE Expert'}</div>
    <div class="dhl-chat-msg__bubble">${role === 'user' ? escHtml(text).replace(/\n/g, '<br>') : chatMarkup(text)}</div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

async function sendChat(message) {
  if (!message || state.busy) return;
  $('chat-input').value = '';
  addChat('user', message);
  const pending = addChat('agent', 'Thinking…', true);
  setBusy('Asking the expert');
  try {
    if (!state.sessionId) state.sessionId = (await api('POST', '/api/session')).session_id;
    const res = await api('POST', '/api/run', { message, session_id: state.sessionId });
    pending.remove();
    addChat('agent', res.response || '(no reply)');
  } catch (err) {
    pending.remove();
    addChat('agent', `⚠️ ${err.message}`);
  } finally {
    setBusy(null);
  }
}

function wireChat() {
  const popup = $('chat-popup');
  $('btn-chat-toggle').onclick = () => popup.classList.toggle('dhl-chat-popup--open');
  $('btn-chat-close').onclick = () => popup.classList.remove('dhl-chat-popup--open');
  $('chat-input').oninput = refreshButtons;
  $('chat-input').onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat($('chat-input').value.trim()); }
  };
  $('btn-chat-send').onclick = () => sendChat($('chat-input').value.trim());
  $('btn-chat-clear-history').onclick = () => {
    $('chat-popup-msgs').innerHTML = '';
    state.sessionId = null;
  };
  document.querySelectorAll('.dhl-suggestion').forEach((b) => {
    b.onclick = () => sendChat(b.dataset.query);
  });
}

// ── Boot ─────────────────────────────────────────────────────
(async function boot() {
  wireActions();
  wireChat();
  await loadStatus();
  try {
    await Promise.all([loadCases(), loadRuleSets()]);
  } catch (err) {
    showError(`Could not load cases or rule sets: ${err.message}`);
  }
})();
