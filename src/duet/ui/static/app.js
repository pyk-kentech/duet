/* duet 관리자 UI — 의존성 없음. 모델 출력은 innerHTML 을 쓰지 않고 DOM 노드로만 그린다. */
'use strict';

const TOKEN = document.querySelector('meta[name="duet-token"]').content;
const $ = (sel, root = document) => root.querySelector(sel);
const LOCAL = 'local';

// =================================================================== DOM helpers
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'value' && (tag === 'input' || tag === 'textarea' || tag === 'select')) el.value = v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, String(v));
    }
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of [children].flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

// =================================================================== labels / format
const STATUS = {
  running: '실행 중', done_approved: '승인 완료', done_unapproved: '미승인 종료', done_design: '설계 완료',
  stopped_rate_limit: '한도 도달', stopped_user: '사용자 중지', failed: '실패', broken: '기록 손상',
  stale: '멈춤 (비정상 종료)',
};
const STEP = {
  propose: '설계안', critique: '비판·개정', synthesize: '설계 종합', implement: '구현', fix: '리뷰 반영',
  review: '리뷰', test: '테스트', base: '기준 커밋', stalled: '수렴 안 됨', design_only: '설계만', approved: '승인', unapproved: '미승인',
};
const PHASE = { init: '준비', debate: '설계 토론', build: '구현·리뷰', done: '끝' };
const CHECK_STATUS = { ok: '정상', warn: '확인 필요', missing: '없음', error: '오류' };

function statusKey(run) { return run.stale ? 'stale' : run.status; }
function statusBadge(run, live) {
  const key = statusKey(run);
  return h('span', { class: `badge s-${key}${live ? ' live' : ''}` }, live ? '실행 중' : (STATUS[key] || key));
}
function agentTag(name) {
  if (!name) return null;
  const base = String(name).replace(/^mock-/, '');
  return h('span', { class: `agent agent-${base === 'claude' ? 'claude' : base === 'codex' ? 'codex' : 'x'}` }, name);
}
function verdictTag(v) {
  if (!v) return null;
  const label = v.status === 'APPROVED' ? '승인' : '반려';
  const extra = v.must_fix ? ` ${v.must_fix}` : '';
  const title = v.parse_failed ? '판정 블록이 없어 반려로 간주' : v.contradiction ? 'APPROVED 인데 must_fix>0 → 반려' : '';
  return h('span', { class: `verdict v-${v.status}`, title: title || null }, label + extra + (v.parse_failed || v.contradiction ? ' ?' : ''));
}
const TEST_STATUS = { passed: '통과', failed: '실패', error: '실행 불가', timeout: '시간 초과' };
function testTag(status) {
  if (!status) return null;
  return h('span', { class: `verdict t-${status}` }, `테스트 ${TEST_STATUS[status] || status}`);
}
function decisionTag(hst) {
  if (!hst) return null;
  const title = (hst.reasons || []).join(' · ');
  if (hst.approved) return h('span', { class: 'verdict v-APPROVED', title }, '승인' + (hst.reviewer_status !== 'APPROVED' ? ' *' : ''));
  return h('span', { class: 'verdict v-CHANGES_REQUESTED', title }, '반려' + (hst.blocking != null ? ` ${hst.blocking}` : ''));
}
function fmtDur(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  if (sec < 60) return `${sec}초`;
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m < 60) return s ? `${m}분 ${s}초` : `${m}분`;
  const hh = Math.floor(m / 60);
  if (hh < 48) return `${hh}시간 ${m % 60}분`;
  return `${Math.floor(hh / 24)}일 ${hh % 24}시간`;
}
function fmtWhen(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff >= 0 && diff < 60) return '방금';
  if (diff >= 0 && diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff >= 0 && diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return fmtDate(d);
}
function fmtDate(d) {
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fmtTok(n) {
  n = Number(n) || 0;
  if (n < 1000) return String(n);
  if (n < 1e6) return (n / 1000).toFixed(n < 10000 ? 1 : 0) + 'k';
  return (n / 1e6).toFixed(n < 1e7 ? 2 : 1) + 'M';
}
function fmtUsd(v) { return v ? `$${Number(v).toFixed(2)}` : ''; }
function usageLine(u) {
  if (!u) return '';
  const parts = [`입력 ${fmtTok(u.input_tokens)}`, `출력 ${fmtTok(u.output_tokens)}`];
  if (u.cost_usd) parts.push(`API 환산 ${fmtUsd(u.cost_usd)}`);
  return parts.join(' · ');
}
function oneLine(s, n = 120) {
  s = String(s || '').replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
function baseName(p) { return String(p).split('/').filter(Boolean).pop() || p; }
function joinPath(root, name) { return String(root).replace(/\/+$/, '') + '/' + String(name).replace(/^\/+/, ''); }

// =================================================================== api
class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
async function api(path, { method = 'GET', body, query, machine } = {}) {
  const url = new URL(path, location.origin);
  const q = { ...(query || {}) };
  if (machine && machine !== LOCAL && method === 'GET') q.machine = machine;
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
  const opts = { method, headers: { 'X-Duet-Token': TOKEN } };
  if (body !== undefined || method === 'POST' || (machine && machine !== LOCAL && method !== 'GET')) {
    const b = { ...(body || {}) };
    if (machine && machine !== LOCAL) b.machine = machine;
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(b);
  }
  if (method === 'DELETE' && machine && machine !== LOCAL) url.searchParams.set('machine', machine);
  let res;
  try { res = await fetch(url, opts); }
  catch { throw new ApiError('서버에 연결할 수 없습니다. 터미널에서 duet ui 가 켜져 있는지 확인하세요.', 0); }
  let data = null;
  try { data = await res.json(); } catch { /* 본문 없음 */ }
  if (!res.ok) throw new ApiError((data && data.error) || `요청 실패 (${res.status})`, res.status);
  return data;
}

// =================================================================== toast
let toastTimer = null;
function toast(msg, bad = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (bad ? ' bad' : '');
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, bad ? 7000 : 3500);
}
function errorBox(e) {
  return h('div', { class: 'alert alert-bad' }, h('b', null, '오류'), h('span', null, e.message || String(e)));
}
// =================================================================== markdown (안전한 DOM 렌더러)
const INLINE_RE = new RegExp([
  '(`+)([\\s\\S]*?[^`])\\1(?!`)',                 // 1,2 code
  '\\*\\*([^*][\\s\\S]*?)\\*\\*',                 // 3 bold
  '\\[([^\\]\\n]+)\\]\\(([^)\\s]+)\\)',           // 4,5 link
  '(https?:\\/\\/[^\\s<>()]+[^\\s<>().,;:!?\'"])', // 6 url
  '(?<![\\w*])\\*([^*\\s][^*\\n]*?)\\*(?![\\w*])', // 7 em
  '(?<![\\w])_([^_\\s][^_\\n]*?)_(?![\\w])',      // 8 em
].join('|'));

function inline(text) {
  const out = [];
  let rest = String(text);
  while (rest) {
    const m = INLINE_RE.exec(rest);
    if (!m) { out.push(rest); break; }
    if (m.index > 0) out.push(rest.slice(0, m.index));
    if (m[1] !== undefined) out.push(h('code', null, m[2]));
    else if (m[3] !== undefined) out.push(h('strong', null, inline(m[3])));
    else if (m[4] !== undefined) out.push(mdLink(m[4], m[5]));
    else if (m[6] !== undefined) out.push(mdLink(m[6], m[6]));
    else if (m[7] !== undefined) out.push(h('em', null, inline(m[7])));
    else if (m[8] !== undefined) out.push(h('em', null, inline(m[8])));
    rest = rest.slice(m.index + m[0].length);
  }
  return out;
}
function mdLink(label, href) {
  if (/^https?:\/\//i.test(href)) {
    return h('a', { href, target: '_blank', rel: 'noopener noreferrer' }, inline(label));
  }
  // 로컬 파일 경로 링크([core.py:93](/tmp/x/core.py:93))는 클릭할 수 없으니 텍스트로
  if (label === href) return h('span', { class: 'localref' }, href);
  return [inline(label), ' ', h('span', { class: 'localref' }, `(${href})`)];
}

const RE = {
  fence: /^\s{0,3}(`{3,}|~{3,})\s*([\w+#.-]*)/,
  heading: /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/,
  hr: /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/,
  quote: /^\s{0,3}>\s?/,
  list: /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/,
  tableSep: /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/,
  verdictOpen: /^\s*<verdict>\s*$/i,
  verdictClose: /^\s*<\/verdict>\s*$/i,
};
function splitRow(line) {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, '|'));
}
function isBlockStart(line, next) {
  return RE.fence.test(line) || RE.heading.test(line) || RE.hr.test(line) || RE.quote.test(line) ||
    RE.list.test(line) || RE.verdictOpen.test(line) || (line.includes('|') && next !== undefined && RE.tableSep.test(next));
}

function markdown(text) {
  const frag = document.createDocumentFragment();
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m;
    if ((m = RE.fence.exec(line))) {
      const fence = m[1], body = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence)) body.push(lines[i++]);
      i++;
      frag.append(h('pre', null, h('code', m[2] ? { 'data-lang': m[2] } : null, body.join('\n'))));
      continue;
    }
    if (RE.verdictOpen.test(line)) {
      const body = [];
      i++;
      while (i < lines.length && !RE.verdictClose.test(lines[i])) body.push(lines[i++]);
      i++;
      frag.append(verdictBox(body.join('\n')));
      continue;
    }
    if ((m = RE.heading.exec(line))) { frag.append(h('h' + m[1].length, null, inline(m[2]))); i++; continue; }
    if (RE.hr.test(line)) { frag.append(h('hr')); i++; continue; }
    if (line.includes('|') && i + 1 < lines.length && RE.tableSep.test(lines[i + 1])) {
      const head = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(splitRow(lines[i++]));
      frag.append(h('table', null,
        h('thead', null, h('tr', null, head.map(c => h('th', null, inline(c))))),
        h('tbody', null, rows.map(r => h('tr', null, head.map((_, k) => h('td', null, inline(r[k] || ''))))))));
      continue;
    }
    if (RE.quote.test(line)) {
      const body = [];
      while (i < lines.length && lines[i].trim() && RE.quote.test(lines[i])) body.push(lines[i++].replace(RE.quote, ''));
      frag.append(h('blockquote', null, markdown(body.join('\n'))));
      continue;
    }
    if (RE.list.test(line)) {
      const [node, next] = parseList(lines, i);
      frag.append(node);
      i = next;
      continue;
    }
    const para = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i], lines[i + 1])) para.push(lines[i++].trim());
    const p = h('p');
    para.forEach((t, k) => { if (k) p.append(h('br')); append(p, inline(t)); });
    frag.append(p);
  }
  return frag;
}

function parseList(lines, start) {
  const first = RE.list.exec(lines[start]);
  const indent = first[1].length;
  const ordered = /\d/.test(first[2]);
  const list = h(ordered ? 'ol' : 'ul');
  if (ordered) { const n = parseInt(first[2], 10); if (n !== 1) list.setAttribute('start', String(n)); }
  let i = start;
  while (i < lines.length) {
    const m = RE.list.exec(lines[i]);
    if (!m || m[1].length !== indent || /\d/.test(m[2]) !== ordered) break;
    const body = [m[3]];
    i++;
    // 같은 항목의 이어지는 줄 / 하위 목록
    while (i < lines.length) {
      const l = lines[i];
      if (!l.trim()) {
        const nxt = lines[i + 1];
        if (nxt !== undefined && nxt.trim() && (nxt.match(/^\s*/)[0].length > indent)) { body.push(''); i++; continue; }
        break;
      }
      const lm = RE.list.exec(l);
      if (lm && lm[1].length <= indent) break;
      if (!lm && l.match(/^\s*/)[0].length <= indent && isBlockStart(l, lines[i + 1])) break;
      body.push(lm ? l : l.replace(/^\s+/, ''));
      i++;
    }
    const li = h('li');
    const firstLines = [];
    let k = 0;
    while (k < body.length && !RE.list.test(body[k]) && !RE.fence.test(body[k])) firstLines.push(body[k++]);
    firstLines.filter(Boolean).forEach((t, n) => { if (n) li.append(h('br')); append(li, inline(t.trim())); });
    if (k < body.length) {
      const restText = body.slice(k).map(l => l.replace(new RegExp(`^\\s{0,${indent + 4}}`), '')).join('\n');
      li.append(markdown(restText));
    }
    list.append(li);
  }
  return [list, i];
}

function verdictBox(body) {
  const status = (/status\s*:\s*\**\s*`?(APPROVED|CHANGES_REQUESTED)/i.exec(body) || [])[1];
  const mustFix = (/must_fix\s*:\s*\**\s*`?(\d+)/i.exec(body) || [])[1];
  return h('div', { class: 'verdict-box' },
    h('span', { class: 'label' }, '판정'),
    status ? verdictTag({ status: status.toUpperCase(), must_fix: mustFix ? Number(mustFix) : null }) : h('code', null, body.trim()),
    mustFix !== undefined ? h('span', { class: 'muted small' }, `반드시 고칠 것 ${mustFix}건`) : null);
}

// =================================================================== diff
function renderDiff(text) {
  const pre = h('pre', { class: 'diff' });
  if (!text) { pre.append('(변경 없음)'); return pre; }
  const frag = document.createDocumentFragment();
  for (const line of text.split('\n')) {
    let cls = 'l';
    if (line.startsWith('diff --git')) cls += ' file';
    else if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('index ') ||
             line.startsWith('new file') || line.startsWith('deleted file') || line.startsWith('commit ') ||
             line.startsWith('similarity') || line.startsWith('rename ')) cls += ' meta';
    else if (line.startsWith('@@')) cls += ' hunk';
    else if (line.startsWith('[변경 파일 요약]') || line.startsWith('(잠금 파일')) cls += ' file';
    else if (line.startsWith('+')) cls += ' add';
    else if (line.startsWith('-')) cls += ' del';
    frag.append(h('span', { class: cls }, line || ' '));
  }
  pre.append(frag);
  return pre;
}

// =================================================================== routing
// #/                       프로젝트 (모든 머신)
// #/p/<path>               이 머신의 프로젝트,   #/m/<id>/p/<path>  원격 머신의 프로젝트
// .../r/<run>?tab=talk     실행
// #/setup?m=<id>  #/usage?m=<id>  #/settings
const enc = encodeURIComponent;
function prefix(machine) { return machine && machine !== LOCAL ? `#/m/${enc(machine)}` : '#'; }
const hrefProject = (m, p, tab) => `${prefix(m)}/p/${enc(p)}` + (tab ? '?tab=' + tab : '');
const hrefRun = (m, p, r, tab) => `${prefix(m)}/p/${enc(p)}/r/${enc(r)}` + (tab ? '?tab=' + tab : '');

function parseHash() {
  const raw = location.hash.replace(/^#/, '') || '/';
  const [pathPart, qs] = raw.split('?');
  let parts = pathPart.split('/').filter(Boolean);
  const q = new URLSearchParams(qs || '');
  try {
    if (parts[0] === 'setup') return { name: 'setup', machine: q.get('m') || LOCAL };
    if (parts[0] === 'usage') return { name: 'usage', machine: q.get('m') || LOCAL };
    if (parts[0] === 'settings') return { name: 'settings' };
    let machine = LOCAL;
    if (parts[0] === 'm' && parts[1]) { machine = decodeURIComponent(parts[1]); parts = parts.slice(2); }
    if (parts[0] === 'p' && parts[1]) {
      const project = decodeURIComponent(parts[1]);
      if (parts[2] === 'r' && parts[3]) return { name: 'run', machine, project, run: decodeURIComponent(parts[3]), tab: q.get('tab') || 'talk' };
      return { name: 'project', machine, project, tab: q.get('tab') || 'runs' };
    }
  } catch { /* 잘못된 인코딩 */ }
  return { name: 'home' };
}

let currentView = null;
let pollTimer = null;
const app = { groups: [], settings: null };

function machineName(id) {
  if (!id || id === LOCAL) return '이 머신';
  const g = app.groups.find(x => x.id === id);
  return g ? g.name : id;
}

async function route() {
  clearTimeout(pollTimer);
  if (currentView && currentView.destroy) currentView.destroy();
  const r = parseHash();
  const main = $('#main');
  const prev = currentView;
  if (prev && r.name === 'run' && prev instanceof RunView && prev.r.project === r.project && prev.r.run === r.run && prev.r.machine === r.machine) {
    prev.switchTab(r.tab);
    currentView = prev;
    schedule(prev, 0);
    return;
  }
  main.replaceChildren(h('div', { class: 'loading' }, '불러오는 중…'));
  const V = { run: RunView, project: ProjectView, setup: SetupView, usage: UsageView, settings: SettingsView }[r.name] || HomeView;
  currentView = new V(main, r);
  document.querySelectorAll('[data-nav]').forEach(a => {
    const nav = a.getAttribute('data-nav');
    a.classList.toggle('active', nav === r.name || (nav === 'home' && ['home', 'project', 'run'].includes(r.name)));
  });
  schedule(currentView, 0);
}
function schedule(view, delay) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(() => tick(view), delay);
}
async function tick(view) {
  if (view !== currentView) return;
  const sidebar = refreshSidebar();
  try {
    await view.load();
    setConnected(true);
  } catch (e) {
    if (e.status === 401 || e.status === 0) setConnected(false, e.message);
    view.showError(e);
  }
  await sidebar;
  const iv = view.interval ? view.interval() : 0;
  if (view === currentView && iv) schedule(view, document.hidden ? 15000 : iv);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && currentView) schedule(currentView, 0); });

function setConnected(ok, msg) {
  const foot = $('#side-foot');
  foot.textContent = ok ? `연결됨 · ${new Date().toLocaleTimeString('ko-KR', { hour12: false })} 갱신` : (msg || '연결 끊김');
  foot.classList.toggle('bad', !ok);
}

async function loadGroups() {
  const d = await api('/api/projects');
  app.groups = d.machines || [{ id: LOCAL, name: '이 머신', local: true, projects: d.projects, jobs: d.jobs }];
  return app.groups;
}
async function refreshSidebar() {
  try { await loadGroups(); } catch { return; }
  const r = parseHash();
  const box = $('#side-projects');
  const groups = app.groups.filter(g => g.local || g.projects.length || g.error);
  box.replaceChildren(...groups.map(g => h('div', { class: 'side-group' },
    h('div', { class: 'side-title' }, g.local ? '이 머신' : g.name, g.error ? h('span', { class: 'warn-dot', title: g.error }) : null),
    h('ul', null, g.projects.length ? g.projects.map(p => {
      const st = p.latest ? statusKey(p.latest) : '';
      return h('li', null, h('a', {
        href: hrefProject(g.id, p.path), title: p.path,
        class: (r.project === p.path && (r.machine || LOCAL) === g.id ? 'active' : null),
      }, h('span', { class: `dot s-${p.live ? 'running live' : st}` }), h('span', { class: 'name' }, p.name)));
    }) : h('li', { class: 'empty' }, g.error ? h('a', { href: `#/setup?m=${enc(g.id)}`, title: g.error }, '확인 필요 → 환경·로그인') : '없음')))));
}
async function loadSettings(force) {
  if (!app.settings || force) app.settings = await api('/api/settings');
  return app.settings;
}

// =================================================================== home
class HomeView {
  constructor(main) { this.main = main; this.addValue = ''; }
  interval() { return 5000; }
  showError(e) { this.main.replaceChildren(h('div', { class: 'page' }, errorBox(e))); }
  async load() {
    await loadGroups();
    if (this.main.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return;
    this.render();
  }
  render() {
    const sections = app.groups.map(g => {
      const cards = g.projects.map(p => {
        const l = p.latest;
        return h('a', { class: 'card project-card', href: hrefProject(g.id, p.path) },
          h('div', { class: 'row' }, h('h3', null, p.name), h('span', { class: 'spacer' }),
            p.live ? statusBadge({ status: 'running' }, true) : l ? statusBadge(l) : h('span', { class: 'badge plain' }, '기록 없음')),
          h('div', { class: 'path' }, p.path),
          l ? h('div', { class: 'task' }, oneLine(l.task, 160)) : null,
          h('div', { class: 'meta' },
            h('span', null, `실행 ${p.run_count}개`),
            l ? h('span', null, `${PHASE[l.phase] || l.phase} · ${STEP[l.step] || l.step || '-'}`) : null,
            l && l.last_verdict ? verdictTag({ status: l.last_verdict }) : null,
            l ? h('span', null, fmtWhen(l.updated_at)) : null,
            p.exists ? null : h('span', { class: 'badge s-failed' }, '폴더 없음')));
      });
      const jobs = (g.jobs || []).filter(j => j.running || j.returncode !== 0).slice(0, 4);
      return h('section', { class: 'machine-section' },
        h('div', { class: 'machine-head' },
          h('h2', null, g.local ? '이 머신' : g.name),
          g.local ? null : h('span', { class: 'mono' }, g.ssh),
          g.error ? h('span', { class: 'badge s-failed' }, '연결 안 됨') : null,
          h('span', { class: 'spacer' }),
          h('a', { class: 'btn btn-sm', href: `#/setup?m=${enc(g.id)}` }, '환경·로그인'),
          h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: () => openRunDialog({ machine: g.id }) }, '새 실행')),
        g.error ? h('div', { class: 'alert alert-warn' }, h('span', null, g.error)) : null,
        cards.length ? h('div', { class: 'grid' }, cards)
          : g.error ? null : h('div', { class: 'card empty-state small' }, '아직 프로젝트가 없습니다. ‘새 실행’으로 시작하세요.'),
        jobs.length ? h('div', { class: 'jobs' }, jobs.map(jobCard)) : null);
    });
    const form = h('form', { class: 'add-form', onsubmit: ev => this.add(ev) },
      h('input', { type: 'text', name: 'path', placeholder: '/절대/경로/프로젝트 — 이 머신의 기존 작업 폴더를 목록에 추가', value: this.addValue, spellcheck: 'false', autocomplete: 'off' }),
      h('button', { class: 'btn', type: 'submit' }, '추가'));
    const noRemote = app.groups.length === 1;
    this.main.replaceChildren(h('div', { class: 'page' },
      h('div', { class: 'page-head' },
        h('div', null, h('h1', null, '프로젝트'), h('div', { class: 'muted' }, '두 모델이 설계를 토론하고 서로의 코드를 리뷰한 기록을 봅니다.')),
        h('span', { class: 'spacer' }),
        h('button', { class: 'btn btn-primary', type: 'button', onclick: () => openRunDialog({}) }, '새 실행')),
      sections, form,
      noRemote ? h('p', { class: 'muted small' }, '다른 머신에서도 돌리려면 ', h('a', { href: '#/settings' }, '설정 > 원격 머신'), '에서 SSH 머신을 추가하세요.') : null));
  }
  async add(ev) {
    ev.preventDefault();
    const input = ev.target.elements.path;
    this.addValue = input.value;
    try {
      const r = await api('/api/projects', { method: 'POST', body: { path: input.value } });
      this.addValue = '';
      toast(`추가했습니다: ${r.path}`);
      input.blur();
      schedule(this, 0);
    } catch (e) { toast(e.message, true); }
  }
}

function jobCard(j) {
  const ok = j.running ? '진행 중' : j.returncode === 0 ? '끝남' : `종료 코드 ${j.returncode}`;
  return h('div', { class: 'card job' },
    h('div', { class: 'row' },
      h('b', null, j.kind === 'run' ? '새 실행' : '이어하기'),
      h('span', { class: 'mono small faint' }, j.project),
      h('span', { class: 'spacer' }),
      h('span', { class: `badge ${j.running ? 's-running live' : j.returncode === 0 ? 's-done_approved' : 's-failed'}` }, ok)),
    !j.running && j.returncode !== 0 && j.log_tail ? h('pre', { class: 'small' }, j.log_tail.trim()) : null);
}
// =================================================================== project
function crumbs(r, ...rest) {
  return h('div', { class: 'crumbs' }, h('a', { href: '#/' }, '프로젝트'), h('span', { class: 'sep' }, '/'),
    r.machine && r.machine !== LOCAL ? [h('span', null, machineName(r.machine)), h('span', { class: 'sep' }, '/')] : null,
    rest);
}

class ProjectView {
  constructor(main, r) { this.main = main; this.r = r; this.designText = undefined; }
  interval() { return this.data && this.data.live ? 2500 : 6000; }
  showError(e) { this.main.replaceChildren(h('div', { class: 'page' }, crumbs(this.r), errorBox(e))); }
  async load() {
    const m = this.r.machine;
    this.data = await api('/api/runs', { query: { project: this.r.project }, machine: m });
    if (this.r.tab === 'design' && this.designText === undefined) {
      const d = await api('/api/design', { query: { project: this.r.project }, machine: m });
      this.designText = d.text;
    }
    this.render();
  }
  render() {
    const d = this.data, m = this.r.machine;
    const live = d.live;
    const liveRun = live ? d.runs.find(x => x.run_id === live.run_id) : null;
    const head = h('div', { class: 'page-head' },
      h('div', null, crumbs(this.r), h('h1', null, baseName(d.project)), h('div', { class: 'sub' }, d.project)),
      h('span', { class: 'spacer' }),
      h('div', { class: 'actions' },
        live ? h('button', { class: 'btn btn-danger', type: 'button', onclick: () => stopRun(m, d.project) }, '중지') : null,
        h('button', { class: 'btn', type: 'button', onclick: () => this.remove() }, '목록에서 제거'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: live ? true : null,
          title: live ? '이 폴더에서 이미 실행 중입니다' : null,
          onclick: () => openRunDialog({ machine: m, project: d.project, defaults: d.defaults, hasDesign: d.has_design }) }, '새 실행')));
    const banner = live ? h('div', { class: 'alert alert-info' },
      h('span', { class: 'spinner' }),
      h('span', null, '실행 중: ', liveRun ? h('a', { href: hrefRun(m, d.project, live.run_id) }, live.run_id) : (live.run_id || '시작하는 중'),
        ` · pid ${live.pid}`, liveRun ? ` · ${PHASE[liveRun.phase] || liveRun.phase} / ${STEP[liveRun.step] || liveRun.step}` : '')) : null;
    const tabs = h('nav', { class: 'tabs' },
      h('a', { href: hrefProject(m, d.project, 'runs'), class: this.r.tab === 'runs' ? 'active' : null }, '실행 기록', h('span', { class: 'count' }, d.runs.length)),
      h('a', { href: hrefProject(m, d.project, 'design'), class: this.r.tab === 'design' ? 'active' : null }, '설계 문서'));
    let body;
    if (this.r.tab === 'design') {
      body = h('div', { class: 'card' }, this.designText
        ? h('div', { class: 'viewer-body md' }, markdown(this.designText))
        : h('div', { class: 'empty-state' }, 'DESIGN.md 가 아직 없습니다.'));
    } else if (!d.runs.length) {
      body = h('div', { class: 'card empty-state' }, h('h3', null, '실행 기록이 없습니다'), h('p', null, '‘새 실행’으로 시작하세요.'));
    } else {
      body = h('div', { class: 'card table-wrap' }, h('table', { class: 'runs' },
        h('thead', null, h('tr', null, ['실행', '상태', '과제', '진행', '판정', '호출', '갱신'].map(t => h('th', null, t)))),
        h('tbody', null, d.runs.map(run => h('tr', { onclick: () => { location.hash = hrefRun(m, d.project, run.run_id); } },
          h('td', { class: 'id' }, h('a', { href: hrefRun(m, d.project, run.run_id) }, run.run_id)),
          h('td', null, statusBadge(run, run.live)),
          h('td', { class: 'task-cell' }, h('div', { class: 'ellipsis', title: run.task }, oneLine(run.task, 90))),
          h('td', { class: 'nowrap small' }, `${PHASE[run.phase] || run.phase || '-'} · ${STEP[run.step] || run.step || '-'}${run.round ? ` · ${run.round}회차` : ''}`),
          h('td', null, verdictTag(run.last_verdict ? { status: run.last_verdict } : null)),
          h('td', { class: 'nowrap small' }, `${run.calls}회 · ${fmtDur(run.total_sec)}`),
          h('td', { class: 'nowrap small muted' }, fmtWhen(run.updated_at)))))));
    }
    this.main.replaceChildren(h('div', { class: 'page' }, head, banner, tabs, body));
  }
  async remove() {
    if (!confirm(`목록에서만 제거합니다. 파일은 지우지 않습니다.\n\n${this.r.project}`)) return;
    try {
      await api('/api/projects', { method: 'DELETE', query: { project: this.r.project }, machine: this.r.machine });
      location.hash = '#/';
    } catch (e) { toast(e.message, true); }
  }
}

// =================================================================== run
class RunView {
  constructor(main, r) {
    this.main = main; this.r = r;
    this.selected = null; this.entryCache = new Map(); this.lastEntryCount = -1;
    this.consoleOffset = 0; this.consoleText = ''; this.commitSel = ''; this.diffCache = new Map();
    this.commits = null; this.designWhich = 'current';
    this.built = false;
  }
  get m() { return this.r.machine; }
  q(extra) { return { project: this.r.project, run: this.r.run, ...(extra || {}) }; }
  interval() { return this.data && this.data.live ? 2000 : 6000; }
  showError(e) {
    if (!this.built) {
      this.main.replaceChildren(h('div', { class: 'page' },
        crumbs(this.r, h('a', { href: hrefProject(this.m, this.r.project) }, baseName(this.r.project))), errorBox(e)));
    } else {
      this.errorSlot.replaceChildren(errorBox(e));
    }
  }
  build() {
    this.headSlot = h('div');
    this.errorSlot = h('div');
    this.tabsSlot = h('nav', { class: 'tabs' });
    this.panelSlot = h('div');
    this.main.replaceChildren(h('div', { class: 'page' },
      crumbs(this.r, h('a', { href: hrefProject(this.m, this.r.project) }, baseName(this.r.project)), h('span', { class: 'sep' }, '/'),
        h('span', null, this.r.run)),
      this.headSlot, this.errorSlot, this.tabsSlot, this.panelSlot));
    this.built = true;
  }
  switchTab(tab) {
    this.r.tab = tab;
    if (this.built) { this.renderTabs(); this.panelBuilt = null; this.renderPanel(true); }
  }
  async load() {
    const d = await api('/api/run', { query: this.q(), machine: this.m });
    this.data = d;
    this.loadedAt = Date.now();
    if (!this.built) this.build();
    this.errorSlot.replaceChildren();
    this.renderHead();
    this.renderTabs();
    await this.renderPanel(false);
  }

  // ---------------------------------------------------------------- head
  renderHead() {
    const d = this.data, st = d.state, c = st.config || {};
    const run = { status: st.status, stale: d.stale };
    const pos = `${PHASE[st.phase] || st.phase} · ${STEP[st.step] || st.step || '-'}${st.round ? ` · ${st.round}회차` : ''}`;
    const totalSec = st.calls.reduce((a, x) => a + (x.sec || 0), 0);
    const modelOf = a => (c[`${a}.model`] || '기본') + (c[`${a}.effort`] ? ` · ${c[`${a}.effort`]}` : '');
    const chips = h('div', { class: 'chips' },
      this.m !== LOCAL ? h('span', { class: 'chip' }, '머신 ', h('b', null, machineName(this.m))) : null,
      c.skip_design ? h('span', { class: 'chip' }, '설계 생략') : h('span', { class: 'chip' }, '종합 ', h('b', null, c.synth), ` · 토론 ${c.debate_rounds}라운드`),
      c.design_only ? h('span', { class: 'chip' }, '설계만') : h('span', { class: 'chip' }, '구현 ', h('b', null, c.implementer), ' · 리뷰 ', h('b', null, c.reviewer), ` · 최대 ${c.max_review}회`),
      h('span', { class: 'chip' }, 'claude ', h('b', null, modelOf('claude'))),
      h('span', { class: 'chip' }, 'codex ', h('b', null, modelOf('codex'))),
      c.mock ? h('span', { class: 'chip' }, 'mock') : null,
      c.block_severity ? h('span', { class: 'chip' }, '반려 기준 ', h('b', null, { P1: 'P1', P2: 'P1·P2', P3: 'P1·P2·P3' }[c.block_severity] || c.block_severity)) : null,
      c.test_command ? h('span', { class: 'chip' }, '테스트 ', h('b', null, c.test_command === 'auto' ? '자동' : c.test_command)) : null,
      st.base_commit ? h('span', { class: 'chip' }, '기준 ', h('b', { class: 'mono' }, st.base_commit)) : null,
      h('span', { class: 'chip' }, `호출 ${st.calls.length}회 · ${fmtDur(totalSec)}`));
    const totals = {};
    for (const call of st.calls) {
      if (!call.usage) continue;
      const t = totals[call.agent] || (totals[call.agent] = { input_tokens: 0, output_tokens: 0, cost_usd: 0 });
      t.input_tokens += call.usage.input_tokens || 0;
      t.output_tokens += call.usage.output_tokens || 0;
      t.cost_usd += call.usage.cost_usd || 0;
    }
    const usageChips = Object.keys(totals).length ? h('div', { class: 'chips' },
      h('span', { class: 'faint small' }, '사용량'),
      Object.entries(totals).map(([a, t]) => h('span', { class: 'chip tok' }, agentTag(a), ' ', usageLine(t)))) : null;

    const alerts = [];
    if (d.stale) alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '멈춤'),
      h('span', null, '상태는 ‘실행 중’인데 duet 프로세스가 없습니다. 터미널이 닫혔거나 비정상 종료된 것 같습니다. 이어하기로 계속할 수 있습니다.')));
    if (st.error && !d.live) alerts.push(h('div', { class: `alert ${st.status === 'failed' ? 'alert-bad' : 'alert-warn'}` },
      h('b', null, STATUS[st.status] || st.status), h('span', null, st.error)));
    if (st.stop_reason === 'stalled' && !d.live) alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '수렴 안 됨'),
      h('span', null, `막는 지적 수가 ${c.stall_rounds || 2}라운드 연속 줄지 않아 멈췄습니다 (${(st.review_history || []).map(x => x.blocking ?? '?').join(' → ')}). 마지막 리뷰를 읽고 직접 판단하거나, 이어하기로 계속할 수 있습니다.`)));
    const limits = this.latestLimits();
    if (limits) alerts.push(limits);

    this.headSlot.replaceChildren(h('div', { class: 'card card-pad run-head' },
      h('div', { class: 'title' },
        h('h1', null, st.run_id), statusBadge(run, d.live),
        h('span', { class: 'muted' }, pos),
        h('span', { class: 'spacer' }),
        this.actions()),
      chips, usageChips,
      this.roundsSummary(),
      st.task.length > 200
        ? h('details', null, h('summary', { class: 'muted small' }, '과제: ' + oneLine(st.task, 100)), h('div', { class: 'task-box' }, st.task))
        : h('div', { class: 'task-box' }, st.task),
      alerts));
  }
  latestLimits() {
    const calls = this.data.state.calls.filter(c => c.usage && c.usage.rate_limits && c.usage.rate_limits.primary);
    if (!calls.length) return null;
    const rl = calls[calls.length - 1].usage.rate_limits;
    const p = rl.primary;
    if (p.used_percent < 70) return null;
    return h('div', { class: `alert ${p.used_percent >= 90 ? 'alert-bad' : 'alert-warn'}` }, h('b', null, 'Codex 한도'),
      h('span', null, `${windowLabel(p.window_minutes)} 창의 ${p.used_percent.toFixed(0)}% 사용` + (p.resets_at ? ` · ${resetLabel(p.resets_at)}` : '')));
  }
  actions() {
    const d = this.data, hint = d.resume || {};
    const box = h('div', { class: 'actions' });
    if (d.live) {
      box.append(h('button', { class: 'btn btn-danger', type: 'button', onclick: () => stopRun(this.m, d.project) }, '중지'));
      return box;
    }
    if (hint.possible) {
      let input = null;
      if (hint.needs_max_review) {
        input = h('input', { type: 'number', min: hint.current_max_review + 1, max: 10, value: Math.min(hint.current_max_review + 1, 10), 'aria-label': '리뷰 최대 횟수' });
        box.append(h('label', null, '리뷰 최대', input, '회까지'));
      }
      box.append(h('button', { class: 'btn btn-primary', type: 'button', onclick: async ev => {
        ev.target.disabled = true;
        try {
          await api('/api/actions/resume', { method: 'POST', machine: this.m,
            body: { project: d.project, run: d.state.run_id, max_review: input ? Number(input.value) : undefined } });
          toast('이어하기를 시작했습니다. 잠시 뒤 진행 상황이 보입니다.');
          schedule(this, 1200);
        } catch (e) { toast(e.message, true); ev.target.disabled = false; }
      } }, hint.needs_max_review ? '리뷰 계속하기' : '이어하기'));
    }
    return box;
  }
  roundsSummary() {
    const st = this.data.state;
    const hist = Object.fromEntries((st.review_history || []).map(x => [x.file, x]));
    const entries = this.data.entries.filter(e => e.meta.step === 'test' || (e.meta.ok !== 'false' && !e.label.endsWith('_failed')));
    const items = [];
    for (const e of entries) {
      const s = e.meta.step;
      if (s === 'implement' || s === 'fix') items.push(h('span', { class: 'chip' }, `${e.meta.round}회차 ${STEP[s]}`));
      else if (s === 'test') items.push(h('span', { class: 'arrow' }, '→'), testTag(e.meta.test_status));
      else if (s === 'review') {
        items.push(h('span', { class: 'arrow' }, '→'));
        items.push(h('span', { class: 'chip' }, '리뷰 ', hist[e.name] ? decisionTag(hist[e.name]) : verdictTag(e.verdict)));
      }
    }
    if (!items.length) return null;
    return h('div', { class: 'rounds' }, h('span', { class: 'faint small' }, '리뷰 이력'), items);
  }

  // ---------------------------------------------------------------- tabs
  renderTabs() {
    const d = this.data, t = this.r.tab;
    const mk = (key, label, count) => h('a', { href: hrefRun(this.m, this.r.project, this.r.run, key), class: t === key ? 'active' : null },
      label, count !== undefined ? h('span', { class: 'count' }, count) : null);
    this.tabsSlot.replaceChildren(
      mk('talk', '대화', d.entries.length), mk('console', '콘솔'), mk('changes', '변경 사항'), mk('design', '설계 문서'));
  }
  async renderPanel(force) {
    const t = this.r.tab;
    if (t === 'console') return this.renderConsole(force);
    if (t === 'changes') return this.renderChanges(force);
    if (t === 'design') return this.renderDesign(force);
    return this.renderTalk(force);
  }

  // ---------------------------------------------------------------- talk
  async renderTalk(force) {
    const d = this.data;
    if (this.panelBuilt !== 'talk') {
      this.timelineEl = h('ul', { class: 'card timeline' });
      this.viewerEl = h('section', { class: 'card viewer' });
      this.panelSlot.replaceChildren(h('div', { class: 'split' }, this.timelineEl, this.viewerEl));
      this.panelBuilt = 'talk';
      force = true;
    }
    if (!this.selected && d.entries.length) this.selected = d.entries[d.entries.length - 1].name;
    this.renderTimeline();
    const changed = d.entries.length !== this.lastEntryCount;
    this.lastEntryCount = d.entries.length;
    if (force || changed || !this.viewerEl.childNodes.length) await this.renderViewer();
  }
  renderTimeline() {
    const d = this.data;
    const items = [];
    let lastPhase = null;
    const phaseOf = s => (['propose', 'critique', 'synthesize'].includes(s) ? '설계 토론' : '구현 · 리뷰');
    for (const e of d.entries) {
      const m = e.meta;
      const ph = phaseOf(m.step);
      if (ph !== lastPhase) { items.push(h('li', { class: 'phase-label' }, ph)); lastPhase = ph; }
      const isTest = m.step === 'test';
      const failed = !isTest && (m.ok === 'false' || e.label.endsWith('_failed'));
      const roundTxt = m.round && m.round !== '0' ? `${m.round}회차` : '';
      const hst = (d.state.review_history || []).find(x => x.file === e.name);
      items.push(h('li', { class: failed ? 'failed' : null }, h('button', {
        type: 'button', class: this.selected === e.name ? 'active' : null,
        onclick: () => { this.selected = e.name; this.renderTimeline(); this.renderViewer(); },
      },
        h('span', { class: 'seq' }, String(e.seq).padStart(2, '0')),
        h('span', { class: 'what' }, agentTag(m.agent), h('span', { class: 'ellipsis' }, STEP[m.step] || m.step)),
        h('span', { class: 'dur' }, m.duration_sec ? fmtDur(m.duration_sec) : ''),
        h('span', { class: 'sub' },
          roundTxt ? h('span', null, roundTxt) : null,
          failed ? h('span', null, m.rate_limited === 'true' ? '한도 도달' : m.timed_out === 'true' ? '시간 초과' : `실패 (exit ${m.exit_code})`) : null,
          m.attempt && m.attempt !== '1' ? h('span', null, `재시도 ${Number(m.attempt) - 1}`) : null,
          m.tokens_out ? h('span', { class: 'tok', title: `입력 ${m.tokens_in || 0} 토큰` }, `출력 ${fmtTok(m.tokens_out)}`) : null,
          isTest ? testTag(m.test_status) : hst ? decisionTag(hst) : verdictTag(e.verdict)))));
    }
    const cc = d.current_call;
    if (d.live) {
      const elapsed = cc ? cc.elapsed_sec + Math.round((Date.now() - this.loadedAt) / 1000) : null;
      items.push(h('li', { class: 'pending' }, h('button', { type: 'button', disabled: true },
        h('span', { class: 'seq' }, h('span', { class: 'spinner' })),
        h('span', { class: 'what' }, cc ? agentTag(cc.agent) : null, h('span', null, cc ? `${STEP[cc.step] || cc.step} 진행 중` : '준비 중')),
        h('span', { class: 'dur' }, elapsed !== null ? fmtDur(elapsed) : ''),
        cc && cc.retry ? h('span', { class: 'sub' }, `재시도 ${cc.retry}`) : null)));
    }
    if (!items.length) items.push(h('li', { class: 'empty-state small' }, '아직 기록이 없습니다.'));
    this.timelineEl.replaceChildren(...items);
  }
  async renderViewer() {
    const name = this.selected;
    if (!name) { this.viewerEl.replaceChildren(h('div', { class: 'empty-state' }, '왼쪽에서 발언을 고르세요.')); return; }
    let entry = this.entryCache.get(name);
    if (!entry) {
      try {
        entry = await api('/api/entry', { query: this.q({ file: name }), machine: this.m });
        this.entryCache.set(name, entry);
      } catch (e) { this.viewerEl.replaceChildren(errorBox(e)); return; }
    }
    if (this.selected !== name) return;
    const m = entry.meta;
    const listed = this.data.entries.find(x => x.name === name);
    const info = [m.model ? m.model + (m.effort ? `·${m.effort}` : '') : '', m.mode === 'write' ? '쓰기' : m.mode === 'read' ? '읽기 전용' : '',
      m.duration_sec ? fmtDur(m.duration_sec) : '', m.tokens_out ? `출력 ${fmtTok(m.tokens_out)} 토큰` : '',
      m.timestamp ? m.timestamp.replace('T', ' ') : ''].filter(Boolean).join(' · ');
    this.viewerEl.replaceChildren(
      h('div', { class: 'viewer-head' },
        agentTag(m.agent), h('b', null, STEP[m.step] || m.step || ''),
        m.round && m.round !== '0' ? h('span', { class: 'muted' }, `${m.round}회차`) : null,
        listed ? verdictTag(listed.verdict) : null,
        h('span', { class: 'spacer' }),
        h('span', { class: 'muted small' }, info),
        h('span', { class: 'file' }, name)),
      h('div', { class: 'viewer-body md' }, markdown(entry.body)));
  }

  // ---------------------------------------------------------------- console
  async renderConsole(force) {
    if (this.panelBuilt !== 'console') {
      this.consoleEl = h('pre', { class: 'console' });
      this.panelSlot.replaceChildren(h('div', { class: 'card' },
        h('div', { class: 'viewer-head' }, h('b', null, '진행 로그'), h('span', { class: 'file' }, 'console.log'),
          h('span', { class: 'spacer' }), h('span', { class: 'muted small' }, '터미널에 찍힌 것과 같습니다')),
        this.consoleEl));
      this.consoleEl.textContent = this.consoleText;
      this.panelBuilt = 'console';
    }
    const atBottom = this.consoleEl.scrollTop + this.consoleEl.clientHeight >= this.consoleEl.scrollHeight - 8;
    const c = await api('/api/console', { query: this.q({ offset: this.consoleOffset }), machine: this.m });
    if (c.text) {
      this.consoleText += c.text;
      this.consoleEl.append(c.text);
    }
    this.consoleOffset = c.offset;
    if (!this.consoleText) this.consoleEl.textContent = '(아직 로그가 없습니다. 이전 버전 duet 으로 실행한 기록에는 콘솔 로그가 없습니다.)';
    if (atBottom || force) this.consoleEl.scrollTop = this.consoleEl.scrollHeight;
  }

  // ---------------------------------------------------------------- changes
  async renderChanges(force) {
    if (this.panelBuilt !== 'changes') {
      this.commitsEl = h('ul', { class: 'card commit-list' });
      this.diffEl = h('section', { class: 'card viewer' });
      this.panelSlot.replaceChildren(h('div', { class: 'split' }, this.commitsEl, this.diffEl));
      this.panelBuilt = 'changes';
      force = true;
    }
    if (force || this.data.live || !this.commits) {
      const c = await api('/api/commits', { query: this.q(), machine: this.m });
      const sig = c.commits.map(x => x.sha).join();
      if (sig !== this.commitSig) { this.commitSig = sig; this.commits = c; this.diffCache.delete(''); force = true; }
    }
    this.renderCommitList();
    if (force) await this.renderDiff();
  }
  renderCommitList() {
    const c = this.commits;
    const items = [h('li', null, h('button', { type: 'button', class: this.commitSel === '' ? 'active' : null,
      onclick: () => { this.commitSel = ''; this.renderCommitList(); this.renderDiff(); } },
      h('b', null, '기준 대비 전체'), h('span', { class: 'sha' }, '리뷰어가 받는 diff')))];
    for (const x of (c && c.commits) || []) {
      items.push(h('li', null, h('button', { type: 'button', class: this.commitSel === x.sha ? 'active' : null,
        onclick: () => { this.commitSel = x.sha; this.renderCommitList(); this.renderDiff(); } },
        h('span', null, x.subject), h('span', { class: 'sha' }, `${x.short} · ${fmtWhen(x.date)}`))));
    }
    if (c && !c.base) items.push(h('li', { class: 'empty-state small' }, '아직 구현 단계에 들어가지 않았습니다.'));
    this.commitsEl.replaceChildren(...items);
  }
  async renderDiff() {
    const key = this.commitSel;
    let d = this.diffCache.get(key);
    if (!d) {
      this.diffEl.replaceChildren(h('div', { class: 'loading' }, '불러오는 중…'));
      try {
        d = await api('/api/diff', { query: this.q({ commit: key || undefined }), machine: this.m });
        this.diffCache.set(key, d);
      } catch (e) { this.diffEl.replaceChildren(errorBox(e)); return; }
    }
    if (this.commitSel !== key) return;
    this.diffEl.replaceChildren(
      h('div', { class: 'viewer-head' }, h('b', null, d.title), d.truncated ? h('span', { class: 'badge s-done_unapproved' }, '너무 길어 일부만 표시') : null),
      renderDiff(d.text));
  }

  // ---------------------------------------------------------------- design
  async renderDesign(force) {
    if (this.panelBuilt !== 'design' || force) {
      const d = await api('/api/design', { query: this.q({ which: this.designWhich }), machine: this.m });
      const switcher = this.data.has_design_backup ? h('div', { class: 'actions' },
        h('button', { class: `btn btn-sm${this.designWhich === 'current' ? ' btn-primary' : ''}`, type: 'button', onclick: () => { this.designWhich = 'current'; this.renderDesign(true); } }, '현재 DESIGN.md'),
        h('button', { class: `btn btn-sm${this.designWhich === 'backup' ? ' btn-primary' : ''}`, type: 'button', onclick: () => { this.designWhich = 'backup'; this.renderDesign(true); } }, '덮어쓰기 전 백업')) : null;
      this.panelSlot.replaceChildren(h('div', { class: 'card' },
        h('div', { class: 'viewer-head' }, h('b', null, '설계 문서'), h('span', { class: 'file' }, d.path), h('span', { class: 'spacer' }), switcher),
        d.text ? h('div', { class: 'viewer-body md' }, markdown(d.text)) : h('div', { class: 'empty-state' }, '아직 없습니다.')));
      this.panelBuilt = 'design';
    }
  }
}

async function stopRun(machine, project) {
  if (!confirm('실행을 중지할까요?\n진행 중인 호출은 버리고, 나중에 이어하기로 그 단계부터 다시 할 수 있습니다.')) return;
  try {
    const r = await api('/api/actions/stop', { method: 'POST', body: { project }, machine });
    toast(`중지 신호를 보냈습니다 (pid ${r.stopped}).`);
    if (currentView) schedule(currentView, 800);
  } catch (e) { toast(e.message, true); }
}
// =================================================================== 공통: 머신 탭
function machineTabs(current, hrefOf) {
  const groups = app.groups.length ? app.groups : [{ id: LOCAL, name: '이 머신', local: true }];
  return h('div', { class: 'subtabs' }, groups.map(g =>
    h('a', { href: hrefOf(g.id), class: g.id === current ? 'active' : null }, g.local ? '이 머신' : g.name)));
}
function windowLabel(min) {
  min = Number(min) || 0;
  if (!min) return '';
  if (min % 1440 === 0) return `${min / 1440}일`;
  if (min % 60 === 0) return `${min / 60}시간`;
  return `${min}분`;
}
function resetLabel(epoch) {
  if (!epoch) return '';
  const d = new Date(Number(epoch) * 1000);
  const left = (d.getTime() - Date.now()) / 1000;
  return `${fmtDate(d)} 초기화` + (left > 0 ? ` (${fmtDur(left)} 후)` : '');
}

// =================================================================== setup (환경·로그인)
class SetupView {
  constructor(main, r) { this.main = main; this.r = r; this.term = null; this.termOffset = 0; this.termText = ''; this.termTimer = null; }
  interval() { return 0; }
  destroy() { clearTimeout(this.termTimer); }
  showError(e) { this.main.replaceChildren(h('div', { class: 'page' }, this.head(), errorBox(e))); }
  head() {
    return h('div', { class: 'page-head' },
      h('div', null, h('h1', null, '환경·로그인'),
        h('div', { class: 'muted' }, 'duet 가 쓰는 도구의 설치와 로그인 상태를 확인하고, 없으면 여기서 설치·로그인합니다.')),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn', type: 'button', onclick: () => this.reload() }, '다시 점검'));
  }
  async reload() { this.checksEl && this.checksEl.replaceChildren(h('div', { class: 'loading' }, '점검 중…')); await this.load(); }
  async load() {
    if (!app.groups.length) await loadGroups();
    if (!this.built) {
      this.checksEl = h('div', { class: 'stack' }, h('div', { class: 'loading' }, '점검 중…'));
      this.termSlot = h('div');
      this.main.replaceChildren(h('div', { class: 'page' }, this.head(),
        machineTabs(this.r.machine, id => `#/setup?m=${enc(id)}`), this.checksEl, this.termSlot));
      this.built = true;
    }
    const m = this.r.machine;
    const parts = [];
    if (m !== LOCAL) {
      const info = await api('/api/machines/probe', { method: 'POST', machine: m });
      parts.push(this.remoteCard(info));
      if (!(info.reachable && info.deployed && info.up_to_date)) { this.checksEl.replaceChildren(...parts); return; }
    }
    const d = await api('/api/doctor', { machine: m });
    parts.push(this.checksCard(d));
    this.checksEl.replaceChildren(...parts);
  }
  remoteCard(info) {
    const m = this.r.machine;
    const rows = [];
    rows.push(['SSH 연결', info.reachable ? 'ok' : 'error', info.reachable ? (info.uname || '연결됨') : info.error,
      info.hint ? h('span', { class: 'mono small' }, info.hint) : null]);
    if (info.reachable) {
      rows.push(['Python 3.11+', info.python ? 'ok' : 'missing', info.python || '찾지 못했습니다. uv 를 설치한 뒤 Python 3.12 를 설치하세요.',
        info.python ? null : [this.actBtn('install_uv'), this.actBtn('install_python')]]);
      const dep = info.deployed ? (info.up_to_date ? 'ok' : 'warn') : 'missing';
      rows.push(['duet 배포', dep, info.deployed ? (info.up_to_date ? `최신 (${info.remote_hash})` : `업데이트 필요 (원격 ${info.remote_hash} · 이 머신 ${info.local_hash})`) : '아직 배포하지 않았습니다.',
        info.python ? h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: ev => this.deploy(ev) }, info.deployed ? '업데이트' : '배포') : null]);
    }
    return h('div', { class: 'card table-wrap' }, h('table', { class: 'checks-table' },
      h('thead', null, h('tr', null, h('th', null, `원격 머신: ${machineName(m)}`), h('th', null, '상태'), h('th', null, '내용'), h('th', null, ''))),
      h('tbody', null, rows.map(([name, st, detail, acts]) => h('tr', null,
        h('td', null, h('b', null, name)), h('td', null, h('span', { class: `badge s-${st}` }, CHECK_STATUS[st] || st)),
        h('td', null, detail), h('td', null, h('div', { class: 'acts' }, acts)))))));
  }
  checksCard(d) {
    const rows = d.checks.map(c => h('tr', null,
      h('td', null, h('b', null, c.name), c.path ? h('div', { class: 'ver' }, c.path) : null),
      h('td', null, h('span', { class: `badge s-${c.status}` }, CHECK_STATUS[c.status] || c.status)),
      h('td', null, c.version ? h('div', { class: 'ver' }, c.version.split(' (')[0]) : null, h('div', { class: 'small' }, c.detail)),
      h('td', null, h('div', { class: 'acts' }, c.actions.map(a => this.actBtn(a, c.status !== 'ok' || a.startsWith('login') ? 'btn-primary' : ''))))));
    return h('div', { class: 'stack' },
      h('div', { class: `alert ${d.ready ? 'alert-info' : 'alert-warn'}` }, h('b', null, d.ready ? '준비됨' : '준비 안 됨'),
        h('span', null, d.ready ? '실제 Claude·Codex 로 실행할 수 있습니다.' : 'git, Claude Code, Codex CLI 가 모두 설치·로그인되어야 실제 실행이 됩니다.')),
      h('div', { class: 'card table-wrap' }, h('table', { class: 'checks-table' },
        h('thead', null, h('tr', null, ['도구', '상태', '버전·내용', ''].map(t => h('th', null, t)))),
        h('tbody', null, rows))));
  }
  actBtn(id, cls = '') {
    const a = (app.actions || {})[id];
    const label = a ? a.title : id;
    return h('button', { class: `btn btn-sm ${cls}`, type: 'button', title: a ? a.command : null, onclick: () => this.runAction(id) }, label);
  }
  async deploy(ev) {
    ev.target.disabled = true;
    try {
      const r = await api('/api/machines/deploy', { method: 'POST', machine: this.r.machine });
      toast(`배포했습니다: ${r.version}`);
      await this.reload();
    } catch (e) { toast(e.message, true); ev.target.disabled = false; }
  }
  async runAction(id) {
    const a = (app.actions || {})[id] || {};
    if (id.startsWith('install') && !confirm(`${a.title || id}\n\n다음 명령을 실행합니다:\n${a.command || ''}`)) return;
    try {
      const job = await api('/api/setup/action', { method: 'POST', body: { action: id }, machine: this.r.machine });
      this.openTerm(job);
    } catch (e) { toast(e.message, true); }
  }
  openTerm(job) {
    clearTimeout(this.termTimer);
    this.term = job; this.termOffset = 0; this.termText = '';
    this.preEl = h('pre');
    this.linksEl = h('div', { class: 'term-links' });
    this.linksEl.hidden = true;
    const input = h('input', { type: 'text', placeholder: '코드나 답을 입력하고 Enter', autocomplete: 'off', spellcheck: 'false' });
    const secret = h('input', { type: 'checkbox', onchange: () => { input.type = secret.checked ? 'password' : 'text'; } });
    const send = async () => {
      if (!input.value) return;
      try { await api('/api/term/input', { method: 'POST', body: { id: job.id, text: input.value } }); input.value = ''; }
      catch (e) { toast(e.message, true); }
    };
    input.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); send(); } });
    this.statusEl = h('span', { class: 'badge s-running live' }, '실행 중');
    this.inputRow = h('div', { class: 'term-input' }, input, h('label', null, secret, '비밀번호(숨김)'),
      h('button', { class: 'btn btn-sm', type: 'button', onclick: send }, '보내기'),
      h('button', { class: 'btn btn-sm btn-danger', type: 'button', onclick: () => api('/api/term/kill', { method: 'POST', body: { id: job.id } }).catch(e => toast(e.message, true)) }, '중지'));
    this.termSlot.replaceChildren(h('div', { class: 'card term' },
      h('div', { class: 'viewer-head' }, h('b', null, job.title), this.statusEl,
        job.machine && job.machine !== LOCAL ? h('span', { class: 'muted small' }, machineName(job.machine)) : null,
        h('span', { class: 'spacer' }), job.note ? h('span', { class: 'muted small' }, job.note) : null),
      this.preEl, this.linksEl, this.inputRow));
    this.termSlot.scrollIntoView({ behavior: 'smooth', block: 'start' });
    this.pollTerm();
  }
  async pollTerm() {
    const job = this.term;
    if (!job || currentView !== this) return;
    let t;
    try { t = await api('/api/term', { query: { id: job.id, offset: this.termOffset } }); }
    catch (e) { toast(e.message, true); return; }
    if (t.text) { this.termText += t.text; this.preEl.append(t.text); this.preEl.scrollTop = this.preEl.scrollHeight; }
    this.termOffset = t.offset;
    if (t.urls && t.urls.length) {
      this.linksEl.hidden = false;
      this.linksEl.replaceChildren(h('span', { class: 'muted small' }, '링크:'),
        t.urls.filter(u => /^https?:\/\//.test(u)).map(u => h('a', { href: u, target: '_blank', rel: 'noopener noreferrer' }, u)));
    }
    if (t.running) { this.termTimer = setTimeout(() => this.pollTerm(), 700); return; }
    this.statusEl.className = `badge ${t.returncode === 0 ? 's-ok' : 's-failed'}`;
    this.statusEl.textContent = t.returncode === 0 ? '끝남' : `종료 코드 ${t.returncode}`;
    this.inputRow.hidden = true;
    await this.reload();
  }
}

// =================================================================== usage (사용량)
function meter(label, w) {
  const pct = Math.max(0, Math.min(100, Number(w.used_percent) || 0));
  return h('div', { class: 'meter' },
    h('div', { class: 'meter-label' }, h('b', null, `${label}${w.window_minutes ? ` (${windowLabel(w.window_minutes)} 창)` : ''}`),
      h('span', null, `${pct.toFixed(0)}% 사용`)),
    h('div', { class: 'meter-bar' }, h('div', { class: `meter-fill${pct >= 90 ? ' high' : pct >= 70 ? ' mid' : ''}`, 'data-pct': pct })),
    w.resets_at ? h('div', { class: 'muted small' }, resetLabel(w.resets_at)) : null);
}
class UsageView {
  constructor(main, r) { this.main = main; this.r = r; }
  interval() { return 30000; }
  showError(e) { this.main.replaceChildren(h('div', { class: 'page' }, h('h1', null, '사용량'), errorBox(e))); }
  async load() {
    if (!app.groups.length) await loadGroups();
    const u = await api('/api/usage', { machine: this.r.machine });
    const cl = u.codex_limits;
    const codexCard = h('div', { class: 'card section-card' },
      h('div', { class: 'row' }, h('h2', null, 'Codex 구독 한도'), cl && cl.plan_type ? h('span', { class: 'chip' }, cl.plan_type) : null,
        h('span', { class: 'spacer' }), cl && cl.as_of ? h('span', { class: 'muted small' }, `기준 ${fmtWhen(cl.as_of)}`) : null),
      cl ? [cl.primary ? meter('주 한도', cl.primary) : null, cl.secondary ? meter('보조 한도', cl.secondary) : null,
        cl.reached ? h('div', { class: 'alert alert-bad' }, h('b', null, '한도 도달'), h('span', null, cl.reached)) : null]
        : h('p', { class: 'muted' }, '최근 Codex 세션 기록이 없습니다. Codex 를 한 번 쓰면 보입니다.'),
      h('p', { class: 'desc' }, 'Codex 가 남긴 마지막 세션 기록 기준입니다(duet 밖에서 쓴 것 포함).'));
    const cw = u.claude_local.windows;
    const claudeCard = h('div', { class: 'card section-card' },
      h('h2', null, 'Claude Code 사용량'),
      h('div', { class: 'stat-grid' }, Object.entries(cw).map(([name, w]) => h('div', { class: 'card stat' },
        h('span', { class: 'k' }, `최근 ${name}`), h('span', { class: 'v' }, `출력 ${fmtTok(w.output_tokens)}`),
        h('span', { class: 's' }, `입력 ${fmtTok(w.input_tokens)} · 응답 ${w.messages}개`)))),
      Object.keys(u.claude_local.output_by_model_7d || {}).length ? h('table', { class: 'plain' },
        h('thead', null, h('tr', null, h('th', null, '모델 (7일)'), h('th', { class: 'num' }, '출력 토큰'))),
        h('tbody', null, Object.entries(u.claude_local.output_by_model_7d).sort((a, b) => b[1] - a[1]).map(([m, n]) =>
          h('tr', null, h('td', null, m), h('td', { class: 'num' }, fmtTok(n)))))) : null,
      h('p', { class: 'desc' }, 'Claude CLI 는 구독 한도(%)를 알려주지 않아, 이 머신의 Claude Code 기록에서 토큰을 합산했습니다. 남은 한도는 claude 대화창의 /usage 로 확인하세요.'));
    const du = u.duet;
    const agentRows = Object.entries(du.by_agent).map(([a, t]) => h('tr', null, h('td', null, agentTag(a)),
      h('td', { class: 'num' }, t.calls || 0), h('td', { class: 'num' }, fmtTok(t.input_tokens)), h('td', { class: 'num' }, fmtTok(t.output_tokens)),
      h('td', { class: 'num' }, fmtUsd(t.cost_usd) || '-')));
    const dayRows = Object.entries(du.by_day).map(([day, agents]) => h('tr', null, h('td', null, day),
      ['claude', 'codex'].map(a => h('td', { class: 'num' }, agents[a] ? `${fmtTok(agents[a].output_tokens)} (${agents[a].calls}회)` : '-'))));
    const projRows = du.projects.map(p => h('tr', null, h('td', null, h('a', { href: hrefProject(this.r.machine, p.path) }, p.name)),
      ['claude', 'codex'].map(a => h('td', { class: 'num' }, p.by_agent[a] ? `${fmtTok(p.by_agent[a].output_tokens)} (${p.by_agent[a].calls}회)` : '-'))));
    const duetCard = h('div', { class: 'card section-card' },
      h('h2', null, 'duet 실행이 쓴 양'),
      agentRows.length ? [
        h('table', { class: 'plain' }, h('thead', null, h('tr', null, h('th', null, '에이전트'), h('th', { class: 'num' }, '호출'),
          h('th', { class: 'num' }, '입력 토큰'), h('th', { class: 'num' }, '출력 토큰'), h('th', { class: 'num' }, 'API 환산'))), h('tbody', null, agentRows)),
        h('table', { class: 'plain' }, h('thead', null, h('tr', null, h('th', null, '날짜'), h('th', { class: 'num' }, 'claude 출력'), h('th', { class: 'num' }, 'codex 출력'))), h('tbody', null, dayRows)),
        h('table', { class: 'plain' }, h('thead', null, h('tr', null, h('th', null, '프로젝트'), h('th', { class: 'num' }, 'claude 출력'), h('th', { class: 'num' }, 'codex 출력'))), h('tbody', null, projRows)),
      ] : h('p', { class: 'muted' }, '아직 사용량이 기록된 실행이 없습니다. 이번 업데이트 이후 실행부터 기록됩니다.'),
      h('p', { class: 'desc' }, 'API 환산은 Claude 가 알려주는 같은 양의 API 요금 추정치이며, 구독 요금과는 다릅니다.'));
    this.main.replaceChildren(h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', null, h('h1', null, '사용량'),
        h('div', { class: 'muted' }, '구독 한도와 duet 실행이 쓴 토큰을 봅니다. 로컬 기록만 읽으므로 사용량을 쓰지 않습니다.'))),
      machineTabs(this.r.machine, id => `#/usage?m=${enc(id)}`), codexCard, claudeCard, duetCard));
    // CSP 때문에 style 속성을 쓰지 않고 CSSOM 으로 폭을 정한다
    this.main.querySelectorAll('.meter-fill').forEach(el => { el.style.width = `${el.getAttribute('data-pct')}%`; });
  }
}
// =================================================================== settings (설정)
function effortSelect(name, agent, value, sugg, model) {
  let levels = sugg[agent].efforts;
  if (agent === 'codex' && model) {
    const m = sugg.codex.models.find(x => x.id === model);
    if (m && m.efforts && m.efforts.length) levels = m.efforts;
  }
  const sel = h('select', { name }, h('option', { value: '' }, '기본값'), levels.map(l => h('option', { value: l }, l)));
  if (value && !levels.includes(value)) sel.append(h('option', { value }, value));
  sel.value = value || '';
  return sel;
}
function modelDatalists(sugg) {
  $('#claude-models').replaceChildren(...sugg.claude.models.map(m => h('option', { value: m.id }, m.label)));
  $('#codex-models').replaceChildren(...sugg.codex.models.map(m => h('option', { value: m.id }, m.label)));
}

class SettingsView {
  constructor(main) { this.main = main; this.editing = null; }
  interval() { return 0; }
  showError(e) { this.main.replaceChildren(h('div', { class: 'page' }, h('h1', null, '설정'), errorBox(e))); }
  async load() {
    const v = await loadSettings(true);
    await checkServer();
    modelDatalists(v.suggestions);
    this.render(v);
  }
  render(v) {
    const s = v.settings, sugg = v.suggestions, eff = v.effective, d = s.defaults || {};
    // ---------------- 작업 폴더 위치
    const roots = [...s.workspace_roots];
    const rootList = h('div', { class: 'list-edit' });
    const drawRoots = () => rootList.replaceChildren(...roots.map((r, i) => h('div', { class: 'item' },
      h('input', { type: 'text', value: r, oninput: ev => { roots[i] = ev.target.value; } }),
      i === 0 ? h('span', { class: 'chip' }, '기본') : h('button', { class: 'btn btn-sm', type: 'button', onclick: () => { roots.unshift(...roots.splice(i, 1)); drawRoots(); } }, '기본으로'),
      h('button', { class: 'btn btn-sm btn-danger', type: 'button', onclick: () => { roots.splice(i, 1); drawRoots(); } }, '삭제'))),
      roots.length ? null : h('p', { class: 'muted small' }, '아직 없습니다.'));
    drawRoots();
    const newRoot = h('input', { type: 'text', placeholder: '~/projects 또는 /절대/경로', spellcheck: 'false' });
    const rootsCard = h('div', { class: 'card section-card' },
      h('h2', null, '작업 폴더 위치'),
      h('p', { class: 'desc' }, '새 실행 때 이 위치를 고르고 폴더 이름만 쓰면 됩니다. 첫 번째가 기본입니다.'),
      rootList,
      h('div', { class: 'add-form' }, newRoot, h('button', { class: 'btn', type: 'button', onclick: () => {
        if (newRoot.value.trim()) { roots.push(newRoot.value.trim()); newRoot.value = ''; drawRoots(); }
      } }, '추가')),
      h('div', { class: 'actions' }, h('button', { class: 'btn btn-primary', type: 'button', onclick: () => this.save({ workspace_roots: roots.filter(x => x.trim()) }) }, '저장')));

    // ---------------- 기본 실행 설정
    const sel = (name, value, opts, empty) => {
      const e = h('select', { name }, empty ? h('option', { value: '' }, empty) : null, opts.map(o => h('option', { value: o }, o)));
      e.value = value || '';
      return e;
    };
    const f = {
      implementer: sel('implementer', d.implementer || '', ['claude', 'codex'], `기본값 (${eff.implementer})`),
      reviewer: sel('reviewer', d.reviewer || '', ['codex', 'claude'], `기본값 (${eff.reviewer})`),
      synth: sel('synth', d.synth || '', ['claude', 'codex'], '리뷰 담당'),
      debate_rounds: h('input', { type: 'number', min: 0, max: 5, value: d.debate_rounds ?? '', placeholder: String(eff.debate_rounds) }),
      max_review: h('input', { type: 'number', min: 1, max: 10, value: d.max_review ?? '', placeholder: String(eff.max_review) }),
      test_command: h('input', { type: 'text', value: d.test_command || '', placeholder: '자동 감지 (none 이면 끔)', spellcheck: 'false' }),
      block_severity: sel('block_severity', d.block_severity || '', ['P1', 'P2', 'P3'], `기본값 (${eff.block_severity})`),
      stall_rounds: h('input', { type: 'number', min: 0, max: 10, value: d.stall_rounds ?? '', placeholder: String(eff.stall_rounds) }),
      require_tests_pass: h('input', { type: 'checkbox', checked: (d.require_tests_pass ?? eff.require_tests_pass) ? true : null }),
      claude_model: h('input', { type: 'text', list: 'claude-models', value: (d.claude || {}).model || '', placeholder: 'CLI 기본값', spellcheck: 'false' }),
      codex_model: h('input', { type: 'text', list: 'codex-models', value: (d.codex || {}).model || '', placeholder: 'CLI 기본값', spellcheck: 'false' }),
    };
    f.claude_effort = effortSelect('claude_effort', 'claude', (d.claude || {}).effort, sugg);
    f.codex_effort = effortSelect('codex_effort', 'codex', (d.codex || {}).effort, sugg, (d.codex || {}).model);
    f.codex_model.addEventListener('change', () => {
      const ne = effortSelect('codex_effort', 'codex', f.codex_effort.value, sugg, f.codex_model.value);
      f.codex_effort.replaceWith(ne); f.codex_effort = ne;
    });
    const field = (label, el) => h('label', { class: 'field' }, h('span', { class: 'field-label' }, label), el);
    const defaultsCard = h('div', { class: 'card section-card' },
      h('h2', null, '기본 실행 설정'),
      h('p', { class: 'desc' }, 'CLI 와 UI 의 모든 실행에 적용됩니다. 작업 폴더의 duet.toml 이나 실행할 때 고른 값이 더 우선합니다.'),
      h('div', { class: 'form-grid' },
        field('구현', f.implementer), field('리뷰', f.reviewer), field('설계 종합', f.synth),
        field('토론 라운드', f.debate_rounds), field('리뷰 최대', f.max_review)),
      h('div', { class: 'form-grid' },
        field('Claude 모델', f.claude_model), field('Claude 추론', f.claude_effort),
        field('Codex 모델', f.codex_model), field('Codex 추론', f.codex_effort)),
      h('h3', null, '리뷰·테스트'),
      h('p', { class: 'desc' }, '반려 기준: 이 심각도 이상의 지적이 남아 있으면 반려합니다(P1 핵심 동작·보안, P2 설계 위반·일반 입력 오류, P3 드문 경계 사례). 수렴 판단: 막는 지적 수가 N 라운드 연속 줄지 않으면 멈춥니다(0=끔).'),
      h('div', { class: 'form-grid' },
        field('테스트 명령', f.test_command), field('반려 기준', f.block_severity), field('수렴 판단 라운드', f.stall_rounds),
        h('label', { class: 'checkline' }, f.require_tests_pass, '테스트 실패 시 승인 안 함')),
      h('div', { class: 'actions' }, h('button', { class: 'btn btn-primary', type: 'button', onclick: () => this.save({ defaults: {
        implementer: f.implementer.value, reviewer: f.reviewer.value, synth: f.synth.value,
        debate_rounds: f.debate_rounds.value, max_review: f.max_review.value,
        claude: { model: f.claude_model.value, effort: f.claude_effort.value },
        codex: { model: f.codex_model.value, effort: f.codex_effort.value },
        test_command: f.test_command.value, block_severity: f.block_severity.value,
        stall_rounds: f.stall_rounds.value, require_tests_pass: f.require_tests_pass.checked,
      } }) }, '저장')));

    // ---------------- 원격 머신
    const ed = this.editing || {};
    const mf = {
      id: h('input', { type: 'text', value: ed.id || '', placeholder: 'lab', spellcheck: 'false', readonly: ed.id ? true : null }),
      name: h('input', { type: 'text', value: ed.name || '', placeholder: '연구실 서버' }),
      ssh: h('input', { type: 'text', value: ed.ssh || '', placeholder: 'me@lab.example.com', spellcheck: 'false' }),
      port: h('input', { type: 'number', value: ed.port || 22, min: 1, max: 65535 }),
      workspace_root: h('input', { type: 'text', value: ed.workspace_root || '', placeholder: '~/duet-projects', spellcheck: 'false' }),
    };
    const machineRows = s.machines.map(m => h('tr', null,
      h('td', null, h('b', null, m.name || m.id), h('div', { class: 'mono small faint' }, m.id)),
      h('td', { class: 'mono small' }, `${m.ssh}${m.port && m.port !== 22 ? ':' + m.port : ''}`),
      h('td', { class: 'mono small' }, m.workspace_root || '-'),
      h('td', { class: 'mono small' }, m.python || '미확인'),
      h('td', null, h('div', { class: 'actions' },
        h('a', { class: 'btn btn-sm btn-primary', href: `#/setup?m=${enc(m.id)}` }, '연결·배포'),
        h('button', { class: 'btn btn-sm', type: 'button', onclick: () => { this.editing = m; this.render(v); } }, '수정'),
        h('button', { class: 'btn btn-sm btn-danger', type: 'button', onclick: () => this.removeMachine(m) }, '삭제')))));
    const machinesCard = h('div', { class: 'card section-card' },
      h('h2', null, '원격 머신'),
      h('p', { class: 'desc' }, '다른 머신에서 duet 를 돌립니다. 이 머신에서 비밀번호 없이 SSH 접속이 되어야 합니다(키 등록: ssh-copy-id user@host). 원격에는 Python 3.11+ 만 있으면 되고 duet 는 UI 가 복사합니다.'),
      s.machines.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'plain' },
        h('thead', null, h('tr', null, ['머신', 'SSH', '작업 폴더 위치', 'Python', ''].map(t => h('th', null, t)))),
        h('tbody', null, machineRows))) : null,
      h('div', { class: 'form-grid' }, field('id (영문 소문자)', mf.id), field('이름', mf.name), field('SSH 대상', mf.ssh),
        field('포트', mf.port), field('작업 폴더 위치', mf.workspace_root)),
      h('div', { class: 'actions' },
        h('button', { class: 'btn btn-primary', type: 'button', onclick: () => this.saveMachine(mf) }, ed.id ? '수정 저장' : '머신 추가'),
        ed.id ? h('button', { class: 'btn', type: 'button', onclick: () => { this.editing = null; this.render(v); } }, '취소') : null));

    const sv = app.server || {};
    const serverCard = h('div', { class: 'card section-card' },
      h('h2', null, 'UI 서버'),
      h('p', { class: 'desc' }, 'duet 코드를 바꾸거나 업데이트한 뒤에는 다시 시작해야 반영됩니다. 같은 주소로 다시 뜨고, 진행 중인 실행은 그대로 돕니다.'),
      h('div', { class: 'chips' },
        h('span', { class: 'chip' }, '버전 ', h('b', null, sv.version || '?')),
        h('span', { class: 'chip' }, '실행 중 코드 ', h('b', { class: 'mono' }, sv.loaded || '?')),
        h('span', { class: 'chip' }, '설치된 코드 ', h('b', { class: 'mono' }, sv.current || '?')),
        sv.uptime_sec != null ? h('span', { class: 'chip' }, `켜진 지 ${fmtDur(sv.uptime_sec)}`) : null,
        sv.stale ? h('span', { class: 'badge s-done_unapproved' }, '다시 시작 필요') : h('span', { class: 'badge s-ok' }, '최신')),
      h('div', { class: 'actions' }, h('button', { class: 'btn', type: 'button', onclick: restartServer }, 'UI 다시 시작')));
    this.main.replaceChildren(h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', null, h('h1', null, '설정'), h('div', { class: 'muted' }, '~/.duet/settings.json 에 저장됩니다.'))),
      v.error ? errorBox({ message: v.error }) : null, rootsCard, defaultsCard, machinesCard, serverCard));
  }
  async save(body) {
    try { app.settings = await api('/api/settings', { method: 'POST', body }); toast('저장했습니다.'); this.render(app.settings); }
    catch (e) { toast(e.message, true); }
  }
  async saveMachine(mf) {
    const body = { id: mf.id.value.trim(), name: mf.name.value.trim(), ssh: mf.ssh.value.trim(), port: mf.port.value, workspace_root: mf.workspace_root.value.trim() };
    try {
      app.settings = await api('/api/machines', { method: 'POST', body });
      this.editing = null;
      toast('저장했습니다. ‘연결·배포’에서 연결을 확인하세요.');
      await loadGroups();
      this.render(app.settings);
    } catch (e) { toast(e.message, true); }
  }
  async removeMachine(m) {
    if (!confirm(`${m.name || m.id} 머신을 목록에서 지울까요? 원격의 파일은 그대로 둡니다.`)) return;
    try { app.settings = await api('/api/machines', { method: 'DELETE', query: { id: m.id } }); await loadGroups(); this.render(app.settings); }
    catch (e) { toast(e.message, true); }
  }
}

// =================================================================== new run dialog
const dlg = $('#run-dialog');
const form = $('#run-form');
const formError = $('#run-form-error');
const CUSTOM = '__custom__';
let dlgState = { fixedProject: null };

function rootsFor(machine) {
  if (machine === LOCAL) return (app.settings && app.settings.settings.workspace_roots) || [];
  const m = app.settings && app.settings.settings.machines.find(x => x.id === machine);
  return m && m.workspace_root ? [m.workspace_root] : [];
}
function fillRoots() {
  const f = form.elements;
  const roots = rootsFor(f.machine.value);
  f.root.replaceChildren(...roots.map(r => h('option', { value: r }, r)), h('option', { value: CUSTOM }, '직접 입력'));
  f.root.value = roots.length && !dlgState.fixedProject ? roots[0] : CUSTOM;
  updatePath();
}
function computedPath() {
  const f = form.elements;
  return f.root.value === CUSTOM ? f.project.value.trim() : (f.name.value.trim() ? joinPath(f.root.value, f.name.value.trim()) : '');
}
function updatePath() {
  const f = form.elements;
  const custom = f.root.value === CUSTOM;
  $('#custom-field').hidden = !custom;
  $('#name-field').hidden = custom;
  const p = computedPath();
  $('#path-preview').textContent = !custom && p ? `→ ${p}` : '';
}
function setEffortOptions(agent, value) {
  const f = form.elements;
  const sugg = app.settings.suggestions;
  const ne = effortSelect(`${agent}_effort`, agent, value, sugg, agent === 'codex' ? f.codex_model.value : null);
  f[`${agent}_effort`].replaceChildren(...ne.childNodes);
  f[`${agent}_effort`].value = value || '';
}

async function openRunDialog({ machine = LOCAL, project = '', defaults = null, hasDesign = true } = {}) {
  try { await loadSettings(); if (!app.groups.length) await loadGroups(); }
  catch (e) { toast(e.message, true); return; }
  form.reset();
  formError.hidden = true;
  dlgState = { fixedProject: project || null };
  const f = form.elements;
  modelDatalists(app.settings.suggestions);
  f.machine.replaceChildren(...app.groups.map(g => h('option', { value: g.id }, g.local ? '이 머신' : g.name)));
  f.machine.value = machine;
  f.machine.disabled = !!project;
  fillRoots();
  f.project.value = project;
  f.project.readOnly = !!project;
  f.root.disabled = !!project;
  const eff = defaults && !defaults.error ? defaults : app.settings.effective;
  f.implementer.value = eff.implementer;
  f.reviewer.value = eff.reviewer;
  f.synth.value = '';
  f.debate_rounds.value = eff.debate_rounds;
  f.max_review.value = eff.max_review;
  f.block_severity.value = eff.block_severity || 'P2';
  f.stall_rounds.value = eff.stall_rounds ?? 2;
  f.test_command.value = '';
  f.test_command.placeholder = eff.test_command && eff.test_command !== 'auto' ? `설정값: ${eff.test_command}` : '자동 감지 (예: python3 -m pytest -q)';
  f.claude_model.value = (eff.claude || {}).model || '';
  f.codex_model.value = (eff.codex || {}).model || '';
  setEffortOptions('claude', (eff.claude || {}).effort);
  setEffortOptions('codex', (eff.codex || {}).effort);
  f.skip_design.disabled = project ? !hasDesign : false;
  f.skip_design.parentElement.title = project && !hasDesign ? 'DESIGN.md 가 없어서 고를 수 없습니다' : '';
  $('#run-cost-note').hidden = false;
  updatePath();
  dlg.showModal();
  (project ? f.task : (f.root.value === CUSTOM ? f.project : f.name)).focus();
}
$('#sidebar-new-run').addEventListener('click', () => {
  const r = parseHash();
  if (r.project) {
    const g = app.groups.find(x => x.id === (r.machine || LOCAL));
    const p = g && g.projects.find(x => x.path === r.project);
    if (p) return openRunDialog({ machine: g.id, project: p.path });
  }
  openRunDialog({ machine: r.machine && r.machine !== LOCAL ? r.machine : LOCAL });
});
dlg.addEventListener('click', ev => { if (ev.target.closest('[data-close]')) dlg.close(); });
form.elements.machine.addEventListener('change', fillRoots);
form.elements.root.addEventListener('change', updatePath);
form.elements.name.addEventListener('input', updatePath);
form.elements.codex_model.addEventListener('change', () => setEffortOptions('codex', form.elements.codex_effort.value));
form.elements.design_only.addEventListener('change', () => { if (form.elements.design_only.checked) form.elements.skip_design.checked = false; });
form.elements.skip_design.addEventListener('change', () => { if (form.elements.skip_design.checked) form.elements.design_only.checked = false; });
form.elements.mock.addEventListener('change', () => { $('#run-cost-note').hidden = form.elements.mock.checked; });

form.addEventListener('submit', async ev => {
  ev.preventDefault();
  const f = form.elements;
  const machine = f.machine.value;
  const body = {
    project: computedPath(), task: f.task.value,
    implementer: f.implementer.value, reviewer: f.reviewer.value, synth: f.synth.value || undefined,
    debate_rounds: f.debate_rounds.value, max_review: f.max_review.value,
    claude_model: f.claude_model.value.trim(), claude_effort: f.claude_effort.value,
    codex_model: f.codex_model.value.trim(), codex_effort: f.codex_effort.value,
    test_command: f.test_command.value.trim(), block_severity: f.block_severity.value, stall_rounds: f.stall_rounds.value,
    design_only: f.design_only.checked, skip_design: f.skip_design.checked, mock: f.mock.checked, force: f.force.checked,
  };
  const problem = !body.project ? (f.root.value === CUSTOM ? '작업 폴더 경로를 입력하세요.' : '폴더 이름을 입력하세요.')
    : !/^[\/~]/.test(body.project) ? '작업 폴더는 / 또는 ~ 로 시작하는 절대 경로여야 합니다.'
    : !body.task.trim() ? '과제를 입력하세요.'
    : body.implementer === body.reviewer ? '구현 담당과 리뷰 담당은 달라야 합니다.' : '';
  if (problem) { formError.textContent = problem; formError.hidden = false; return; }
  const btn = $('#run-submit');
  btn.disabled = true;
  formError.hidden = true;
  try {
    const job = await api('/api/actions/run', { method: 'POST', body, machine });
    dlg.close();
    toast('실행을 시작했습니다.');
    await followNewRun(job, machine);
  } catch (e) {
    formError.textContent = e.message;
    formError.hidden = false;
  } finally { btn.disabled = false; }
});

// 시작한 실행의 run_id 가 잡히면 그 화면으로 이동. 바로 실패하면 로그를 보여준다.
async function followNewRun(job, machine) {
  const project = job.project;
  location.hash = hrefProject(machine, project);
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 800));
    let groups;
    try { groups = await loadGroups(); } catch { continue; }
    const g = groups.find(x => x.id === machine);
    if (!g) return;
    const p = g.projects.find(x => x.path === project);
    if (p && p.live && p.live.run_id) { location.hash = hrefRun(machine, p.path, p.live.run_id); return; }
    const j = (g.jobs || []).find(x => x.id === job.id);
    if (j && !j.running) {
      if (j.returncode === 0 && p && p.latest) location.hash = hrefRun(machine, p.path, p.latest.run_id);
      else if (j.returncode !== 0) toast(`실행이 바로 끝났습니다 (종료 코드 ${j.returncode}).\n${(j.log_tail || '').trim().split('\n').slice(-4).join('\n')}`, true);
      return;
    }
  }
}

// =================================================================== UI 서버 업데이트·다시 시작
async function checkServer() {
  try { app.server = await api('/api/server'); } catch { return; }
  $('#update-banner').hidden = !app.server.stale;
}
async function restartServer() {
  const running = (app.server && app.server.running_terms) || [];
  if (running.length) { toast(`진행 중인 터미널 작업이 있습니다: ${running.join(', ')}`, true); return; }
  if (!confirm('UI 를 다시 시작할까요? 같은 주소로 다시 뜨고, 진행 중인 실행은 그대로 돕니다.')) return;
  try { await api('/api/server/restart', { method: 'POST' }); }
  catch (e) { toast(e.message, true); return; }
  $('#restart-overlay').hidden = false;
  const before = app.server ? app.server.uptime_sec : null;
  const deadline = Date.now() + 30000;
  await new Promise(r => setTimeout(r, 800));
  while (Date.now() < deadline) {
    try {
      const s = await api('/api/server');
      if (before === null || s.uptime_sec < before || !s.stale) { location.reload(); return; }
    } catch { /* 아직 다시 뜨는 중 */ }
    await new Promise(r => setTimeout(r, 500));
  }
  $('#restart-overlay').hidden = true;
  toast('UI 가 다시 뜨지 않았습니다. duet ui 를 실행한 터미널을 확인하세요.', true);
}
$('#restart-btn').addEventListener('click', restartServer);

// =================================================================== boot
window.addEventListener('hashchange', route);
checkServer();
setInterval(checkServer, 20000);
api('/api/setup/actions').then(a => { app.actions = a.actions; }).catch(() => {});
route();
