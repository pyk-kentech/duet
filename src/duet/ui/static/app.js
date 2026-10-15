/* duet 관리자 UI — 의존성 없음. 모델 출력은 innerHTML 을 쓰지 않고 DOM 노드로만 그린다. */
'use strict';

const TOKEN = document.querySelector('meta[name="duet-token"]').content;
const $ = (sel, root = document) => root.querySelector(sel);

// =================================================================== DOM helpers
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
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
  review: '리뷰', base: '기준 커밋', design_only: '설계만', approved: '승인', unapproved: '미승인',
};
const PHASE = { init: '준비', debate: '설계 토론', build: '구현·리뷰', done: '끝' };

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
function fmtDur(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  if (sec < 60) return `${sec}초`;
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m < 60) return s ? `${m}분 ${s}초` : `${m}분`;
  const hh = Math.floor(m / 60);
  return `${hh}시간 ${m % 60}분`;
}
function fmtWhen(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return '방금';
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function oneLine(s, n = 120) {
  s = String(s || '').replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
function baseName(p) { return String(p).split('/').filter(Boolean).pop() || p; }

// =================================================================== api
class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
async function api(path, { method = 'GET', body, query } = {}) {
  const url = new URL(path, location.origin);
  if (query) for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
  const opts = { method, headers: { 'X-Duet-Token': TOKEN } };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
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
const hrefProject = (p, tab) => '#/p/' + encodeURIComponent(p) + (tab ? '?tab=' + tab : '');
const hrefRun = (p, r, tab) => '#/p/' + encodeURIComponent(p) + '/r/' + encodeURIComponent(r) + (tab ? '?tab=' + tab : '');

function parseHash() {
  const raw = location.hash.replace(/^#/, '') || '/';
  const [pathPart, qs] = raw.split('?');
  const parts = pathPart.split('/').filter(Boolean);
  const q = new URLSearchParams(qs || '');
  try {
    if (parts[0] === 'p' && parts[1]) {
      const project = decodeURIComponent(parts[1]);
      if (parts[2] === 'r' && parts[3]) return { name: 'run', project, run: decodeURIComponent(parts[3]), tab: q.get('tab') || 'talk' };
      return { name: 'project', project, tab: q.get('tab') || 'runs' };
    }
  } catch { /* 잘못된 인코딩 */ }
  return { name: 'home' };
}

let currentView = null;
let pollTimer = null;
const app = { projects: [], jobs: [], connected: true };

async function route() {
  clearTimeout(pollTimer);
  if (currentView && currentView.destroy) currentView.destroy();
  const r = parseHash();
  const main = $('#main');
  const prev = currentView;
  if (prev && r.name === 'run' && prev instanceof RunView && prev.r.project === r.project && prev.r.run === r.run) {
    // 같은 실행에서 탭만 바뀜 → 다시 만들지 않음
    prev.switchTab(r.tab);
    currentView = prev;
    schedule(prev, 0);
    return;
  }
  main.replaceChildren(h('div', { class: 'loading' }, '불러오는 중…'));
  currentView = r.name === 'run' ? new RunView(main, r) : r.name === 'project' ? new ProjectView(main, r) : new HomeView(main);
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
  if (view === currentView) schedule(view, document.hidden ? 15000 : view.interval());
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && currentView) schedule(currentView, 0); });

function setConnected(ok, msg) {
  app.connected = ok;
  const foot = $('#side-foot');
  foot.textContent = ok ? `연결됨 · ${new Date().toLocaleTimeString('ko-KR', { hour12: false })} 갱신` : (msg || '연결 끊김');
  foot.classList.toggle('bad', !ok);
}

async function refreshSidebar() {
  try {
    const d = await api('/api/projects');
    app.projects = d.projects;
    app.jobs = d.jobs;
  } catch { return; }
  const r = parseHash();
  const ul = $('#side-projects');
  if (!app.projects.length) { ul.replaceChildren(h('li', { class: 'empty' }, '없음')); return; }
  ul.replaceChildren(...app.projects.map(p => {
    const live = !!p.live;
    const st = p.latest ? statusKey(p.latest) : '';
    return h('li', null, h('a', {
      href: hrefProject(p.path), title: p.path,
      class: (r.project === p.path ? 'active' : null),
    }, h('span', { class: `dot s-${live ? 'running live' : st}` }), h('span', { class: 'name' }, p.name)));
  }));
}

function errorBox(e) {
  return h('div', { class: 'alert alert-bad' }, h('b', null, '오류'), h('span', null, e.message || String(e)));
}

// =================================================================== home
class HomeView {
  constructor(main) { this.main = main; this.addValue = ''; }
  interval() { return 4000; }
  showError(e) { this.main.replaceChildren(h('div', { class: 'page' }, errorBox(e))); }
  async load() {
    const d = await api('/api/projects');
    app.projects = d.projects; app.jobs = d.jobs;
    if (this.main.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return; // 입력 중엔 다시 그리지 않음
    this.render();
  }
  render() {
    const cards = app.projects.map(p => {
      const l = p.latest;
      return h('a', { class: 'card project-card', href: hrefProject(p.path) },
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
    const form = h('form', { class: 'add-form', onsubmit: ev => this.add(ev) },
      h('input', { type: 'text', name: 'path', placeholder: '/절대/경로/프로젝트 — 기존 작업 폴더를 목록에 추가', value: this.addValue, spellcheck: 'false', autocomplete: 'off' }),
      h('button', { class: 'btn', type: 'submit' }, '추가'));
    const jobs = app.jobs.filter(j => j.running || j.returncode !== 0).slice(0, 6);
    this.main.replaceChildren(h('div', { class: 'page' },
      h('div', { class: 'page-head' },
        h('div', null, h('h1', null, '프로젝트'), h('div', { class: 'muted' }, '두 모델이 설계를 토론하고 서로의 코드를 리뷰한 기록을 봅니다.')),
        h('span', { class: 'spacer' }),
        h('button', { class: 'btn btn-primary', type: 'button', onclick: () => openRunDialog({}) }, '새 실행')),
      cards.length ? h('div', { class: 'grid' }, cards) : h('div', { class: 'card empty-state' },
        h('h3', null, '아직 프로젝트가 없습니다'),
        h('p', null, '‘새 실행’으로 시작하거나, 터미널에서 duet run 을 한 폴더를 아래에 추가하세요.')),
      form,
      jobs.length ? h('div', { class: 'section-title' }, 'UI 에서 시작한 작업') : null,
      jobs.length ? h('div', { class: 'jobs' }, jobs.map(jobCard)) : null));
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
class ProjectView {
  constructor(main, r) { this.main = main; this.r = r; this.designText = undefined; }
  interval() { return this.data && this.data.live ? 2500 : 5000; }
  showError(e) {
    this.main.replaceChildren(h('div', { class: 'page' },
      h('div', { class: 'crumbs' }, h('a', { href: '#/' }, '프로젝트')), errorBox(e)));
  }
  async load() {
    this.data = await api('/api/runs', { query: { project: this.r.project } });
    if (this.r.tab === 'design' && this.designText === undefined) {
      const d = await api('/api/design', { query: { project: this.r.project } });
      this.designText = d.text;
    }
    this.render();
  }
  render() {
    const d = this.data;
    const live = d.live;
    const liveRun = live ? d.runs.find(x => x.run_id === live.run_id) : null;
    const head = h('div', { class: 'page-head' },
      h('div', null,
        h('div', { class: 'crumbs' }, h('a', { href: '#/' }, '프로젝트'), h('span', { class: 'sep' }, '/')),
        h('h1', null, baseName(d.project)),
        h('div', { class: 'sub' }, d.project)),
      h('span', { class: 'spacer' }),
      h('div', { class: 'actions' },
        live ? h('button', { class: 'btn btn-danger', type: 'button', onclick: () => stopRun(d.project) }, '중지') : null,
        h('button', { class: 'btn', type: 'button', onclick: () => this.remove() }, '목록에서 제거'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: live ? true : null,
          title: live ? '이 폴더에서 이미 실행 중입니다' : null,
          onclick: () => openRunDialog({ project: d.project, defaults: d.defaults, hasDesign: d.has_design }) }, '새 실행')));
    const banner = live ? h('div', { class: 'alert alert-info' },
      h('span', { class: 'spinner' }),
      h('span', null, '실행 중: ', liveRun ? h('a', { href: hrefRun(d.project, live.run_id) }, live.run_id) : (live.run_id || '시작하는 중'),
        ` · pid ${live.pid}`, liveRun ? ` · ${PHASE[liveRun.phase] || liveRun.phase} / ${STEP[liveRun.step] || liveRun.step}` : '')) : null;
    const tabs = h('nav', { class: 'tabs' },
      h('a', { href: hrefProject(d.project, 'runs'), class: this.r.tab === 'runs' ? 'active' : null }, '실행 기록', h('span', { class: 'count' }, d.runs.length)),
      h('a', { href: hrefProject(d.project, 'design'), class: this.r.tab === 'design' ? 'active' : null }, '설계 문서'));
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
        h('tbody', null, d.runs.map(run => h('tr', { onclick: () => { location.hash = hrefRun(d.project, run.run_id); } },
          h('td', { class: 'id' }, h('a', { href: hrefRun(d.project, run.run_id) }, run.run_id)),
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
      await api('/api/projects', { method: 'DELETE', query: { project: this.r.project } });
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
    this.commits = null; this.designText = undefined; this.designWhich = 'current';
    this.built = false;
  }
  interval() { return this.data && this.data.live ? 2000 : 6000; }
  showError(e) {
    if (!this.built) {
      this.main.replaceChildren(h('div', { class: 'page' },
        h('div', { class: 'crumbs' }, h('a', { href: '#/' }, '프로젝트'), h('span', { class: 'sep' }, '/'),
          h('a', { href: hrefProject(this.r.project) }, baseName(this.r.project))), errorBox(e)));
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
      h('div', { class: 'crumbs' }, h('a', { href: '#/' }, '프로젝트'), h('span', { class: 'sep' }, '/'),
        h('a', { href: hrefProject(this.r.project) }, baseName(this.r.project)), h('span', { class: 'sep' }, '/'),
        h('span', null, this.r.run)),
      this.headSlot, this.errorSlot, this.tabsSlot, this.panelSlot));
    this.built = true;
  }
  switchTab(tab) {
    this.r.tab = tab;
    if (this.built) { this.renderTabs(); this.panelBuilt = null; this.renderPanel(true); }
  }
  async load() {
    const q = { project: this.r.project, run: this.r.run };
    const d = await api('/api/run', { query: q });
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
    const chips = h('div', { class: 'chips' },
      c.skip_design ? h('span', { class: 'chip' }, '설계 생략') : h('span', { class: 'chip' }, '종합 ', h('b', null, c.synth), ` · 토론 ${c.debate_rounds}라운드`),
      c.design_only ? h('span', { class: 'chip' }, '설계만') : h('span', { class: 'chip' }, '구현 ', h('b', null, c.implementer), ' · 리뷰 ', h('b', null, c.reviewer), ` · 최대 ${c.max_review}회`),
      c.mock ? h('span', { class: 'chip' }, 'mock') : null,
      st.base_commit ? h('span', { class: 'chip' }, '기준 ', h('b', { class: 'mono' }, st.base_commit)) : null,
      h('span', { class: 'chip' }, `호출 ${st.calls.length}회 · ${fmtDur(totalSec)}`));

    const alerts = [];
    if (d.stale) alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '멈춤'),
      h('span', null, '상태는 ‘실행 중’인데 duet 프로세스가 없습니다. 터미널이 닫혔거나 비정상 종료된 것 같습니다. 이어하기로 계속할 수 있습니다.')));
    if (st.error && !d.live) alerts.push(h('div', { class: `alert ${st.status === 'failed' ? 'alert-bad' : 'alert-warn'}` },
      h('b', null, STATUS[st.status] || st.status), h('span', null, st.error)));

    this.headSlot.replaceChildren(h('div', { class: 'card card-pad run-head' },
      h('div', { class: 'title' },
        h('h1', null, st.run_id), statusBadge(run, d.live),
        h('span', { class: 'muted' }, pos),
        h('span', { class: 'spacer' }),
        this.actions()),
      chips,
      this.roundsSummary(),
      st.task.length > 200
        ? h('details', null, h('summary', { class: 'muted small' }, '과제: ' + oneLine(st.task, 100)), h('div', { class: 'task-box' }, st.task))
        : h('div', { class: 'task-box' }, st.task),
      alerts));
  }
  actions() {
    const d = this.data, hint = d.resume || {};
    const box = h('div', { class: 'actions' });
    if (d.live) {
      box.append(h('button', { class: 'btn btn-danger', type: 'button', onclick: () => stopRun(d.project) }, '중지'));
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
          await api('/api/actions/resume', { method: 'POST', body: { project: d.project, run: d.state.run_id, max_review: input ? Number(input.value) : undefined } });
          toast('이어하기를 시작했습니다. 잠시 뒤 진행 상황이 보입니다.');
          schedule(this, 1200);
        } catch (e) { toast(e.message, true); ev.target.disabled = false; }
      } }, hint.needs_max_review ? '리뷰 계속하기' : '이어하기'));
    }
    return box;
  }
  roundsSummary() {
    const entries = this.data.entries.filter(e => e.meta.ok !== 'false' && !e.label.endsWith('_failed'));
    const items = [];
    for (const e of entries) {
      const s = e.meta.step;
      if (s === 'implement' || s === 'fix') items.push(h('span', { class: 'chip' }, `${e.meta.round}회차 ${STEP[s]}`));
      else if (s === 'review') {
        items.push(h('span', { class: 'arrow' }, '→'));
        items.push(h('span', { class: 'chip' }, '리뷰 ', verdictTag(e.verdict)));
      }
    }
    if (!items.length) return null;
    return h('div', { class: 'rounds' }, h('span', { class: 'faint small' }, '리뷰 이력'), items);
  }

  // ---------------------------------------------------------------- tabs
  renderTabs() {
    const d = this.data, t = this.r.tab;
    const mk = (key, label, count) => h('a', { href: hrefRun(this.r.project, this.r.run, key), class: t === key ? 'active' : null },
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
    // 처음엔 가장 최근 성공 기록을 연다
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
      const failed = m.ok === 'false' || e.label.endsWith('_failed');
      const roundTxt = m.round && m.round !== '0' ? `${m.round}회차` : '';
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
          verdictTag(e.verdict)))));
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
        entry = await api('/api/entry', { query: { project: this.r.project, run: this.r.run, file: name } });
        this.entryCache.set(name, entry);
      } catch (e) { this.viewerEl.replaceChildren(errorBox(e)); return; }
    }
    if (this.selected !== name) return;
    const m = entry.meta;
    const listed = this.data.entries.find(x => x.name === name);
    this.viewerEl.replaceChildren(
      h('div', { class: 'viewer-head' },
        agentTag(m.agent), h('b', null, STEP[m.step] || m.step || ''),
        m.round && m.round !== '0' ? h('span', { class: 'muted' }, `${m.round}회차`) : null,
        listed ? verdictTag(listed.verdict) : null,
        h('span', { class: 'spacer' }),
        h('span', { class: 'muted small' }, [m.mode === 'write' ? '쓰기' : m.mode === 'read' ? '읽기 전용' : '', m.duration_sec ? fmtDur(m.duration_sec) : '', m.timestamp ? m.timestamp.replace('T', ' ') : ''].filter(Boolean).join(' · ')),
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
    const c = await api('/api/console', { query: { project: this.r.project, run: this.r.run, offset: this.consoleOffset } });
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
      const c = await api('/api/commits', { query: { project: this.r.project, run: this.r.run } });
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
      h('b', null, '기준 대비 전체'), h('span', { class: 'sha' }, '리뷰어가 보는 diff'))) ];
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
        d = await api('/api/diff', { query: { project: this.r.project, run: this.r.run, commit: key || undefined } });
        if (key) this.diffCache.set(key, d); else this.diffCache.set('', d);
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
      const d = await api('/api/design', { query: { project: this.r.project, run: this.r.run, which: this.designWhich } });
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

// =================================================================== actions
async function stopRun(project) {
  if (!confirm('실행을 중지할까요?\n진행 중인 호출은 버리고, 나중에 이어하기로 그 단계부터 다시 할 수 있습니다.')) return;
  try {
    const r = await api('/api/actions/stop', { method: 'POST', body: { project } });
    toast(`중지 신호를 보냈습니다 (pid ${r.stopped}).`);
    if (currentView) schedule(currentView, 800);
  } catch (e) { toast(e.message, true); }
}

// =================================================================== new run dialog
const dlg = $('#run-dialog');
const form = $('#run-form');
const formError = $('#run-form-error');

function openRunDialog({ project = '', defaults = null, hasDesign = false } = {}) {
  form.reset();
  formError.hidden = true;
  const f = form.elements;
  f.project.value = project;
  if (defaults && !defaults.error) {
    f.implementer.value = defaults.implementer;
    f.reviewer.value = defaults.reviewer;
    f.synth.value = '';
    f.debate_rounds.value = defaults.debate_rounds;
    f.max_review.value = defaults.max_review;
  }
  f.skip_design.disabled = project ? !hasDesign : false;
  f.skip_design.parentElement.title = project && !hasDesign ? 'DESIGN.md 가 없어서 고를 수 없습니다' : '';
  dlg.showModal();
  (project ? f.task : f.project).focus();
}
$('#sidebar-new-run').addEventListener('click', () => {
  const r = parseHash();
  const p = r.project ? app.projects.find(x => x.path === r.project) : null;
  openRunDialog({ project: p ? p.path : '', hasDesign: true });
});
dlg.addEventListener('click', ev => { if (ev.target.closest('[data-close]')) dlg.close(); });
form.elements.design_only.addEventListener('change', () => { if (form.elements.design_only.checked) form.elements.skip_design.checked = false; });
form.elements.skip_design.addEventListener('change', () => { if (form.elements.skip_design.checked) form.elements.design_only.checked = false; });
form.elements.mock.addEventListener('change', () => { $('#run-cost-note').hidden = form.elements.mock.checked; });

form.addEventListener('submit', async ev => {
  ev.preventDefault();
  const f = form.elements;
  const body = {
    project: f.project.value.trim(), task: f.task.value,
    implementer: f.implementer.value, reviewer: f.reviewer.value, synth: f.synth.value || undefined,
    debate_rounds: f.debate_rounds.value, max_review: f.max_review.value,
    design_only: f.design_only.checked, skip_design: f.skip_design.checked, mock: f.mock.checked, force: f.force.checked,
  };
  const problem = !body.project.startsWith('/') ? '작업 폴더는 / 로 시작하는 절대 경로여야 합니다.'
    : !body.task.trim() ? '과제를 입력하세요.'
    : body.implementer === body.reviewer ? '구현 담당과 리뷰 담당은 달라야 합니다.' : '';
  if (problem) { formError.textContent = problem; formError.hidden = false; return; }
  const btn = $('#run-submit');
  btn.disabled = true;
  formError.hidden = true;
  try {
    const job = await api('/api/actions/run', { method: 'POST', body });
    dlg.close();
    toast('실행을 시작했습니다.');
    await followNewRun(job, body.project);
  } catch (e) {
    formError.textContent = e.message;
    formError.hidden = false;
  } finally { btn.disabled = false; }
});

// 시작한 실행의 run_id 가 잡히면 그 화면으로 이동. 바로 실패하면 로그를 보여준다.
async function followNewRun(job, project) {
  location.hash = hrefProject(project);
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 700));
    let d;
    try { d = await api('/api/projects'); } catch { continue; }
    const p = d.projects.find(x => x.path === project || x.path.replace(/\/+$/, '') === project.replace(/\/+$/, ''));
    if (p && p.live && p.live.run_id) { location.hash = hrefRun(p.path, p.live.run_id); return; }
    const j = d.jobs.find(x => x.id === job.id);
    if (j && !j.running) {
      if (j.returncode === 0 && p && p.latest) location.hash = hrefRun(p.path, p.latest.run_id);
      else if (j.returncode !== 0) toast(`실행이 바로 끝났습니다 (종료 코드 ${j.returncode}).\n${(j.log_tail || '').trim().split('\n').slice(-4).join('\n')}`, true);
      return;
    }
  }
}

// =================================================================== boot
window.addEventListener('hashchange', route);
route();
