/* duet 관리자 UI — 의존성 없음. 모델 출력은 innerHTML 을 쓰지 않고 DOM 노드로만 그린다. */
'use strict';

const TOKEN = document.querySelector('meta[name="duet-token"]').content;
// 토큰은 쿠키로 기억하므로 주소창에서는 지운다 (화면 공유·복사 때 새지 않게, DESIGN.md 28.1)
if (/[?&]t=/.test(location.search)) history.replaceState(null, '', location.pathname + location.hash);
const $ = (sel, root = document) => root.querySelector(sel);
const LOCAL = 'local';
const LIVE = '__live__';   // 타임라인의 '진행 중' 항목

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
const SVG_NS = 'http://www.w3.org/2000/svg';
function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, String(v));
  for (const c of children.flat(Infinity)) if (c) el.append(c);
  return el;
}
// Claude·Codex 표시. 각 회사의 공식 로고 파일을 옮긴 것이 아니라, 알아볼 수 있게 단순화해 그린 아이콘이다.
function agentLogo(agent, size = 16) {
  const base = String(agent || '').replace(/^mock-/, '');
  const box = { viewBox: '0 0 24 24', width: size, height: size, 'aria-hidden': 'true' };
  if (base === 'claude') {        // 주황색 햇살: 길이가 번갈아 다른 12갈래
    const rays = [];
    for (let i = 0; i < 12; i++) {
      const a = i * Math.PI / 6 + 0.12, r1 = 2.4, r2 = i % 2 ? 7.4 : 10;
      rays.push(svg('line', { x1: (12 + r1 * Math.cos(a)).toFixed(2), y1: (12 + r1 * Math.sin(a)).toFixed(2),
        x2: (12 + r2 * Math.cos(a)).toFixed(2), y2: (12 + r2 * Math.sin(a)).toFixed(2) }));
    }
    return svg('svg', { ...box, class: 'logo logo-claude' }, svg('g', { stroke: 'currentColor', 'stroke-width': 2.5, 'stroke-linecap': 'round' }, rays));
  }
  if (base === 'codex') {         // 여섯 겹 고리
    const petals = [];
    for (let i = 0; i < 6; i++) petals.push(svg('ellipse', { cx: 12, cy: 7.7, rx: 3.3, ry: 5.3, transform: `rotate(${i * 60} 12 12)` }));
    return svg('svg', { ...box, class: 'logo logo-codex' }, svg('g', { fill: 'none', stroke: 'currentColor', 'stroke-width': 1.7 }, petals));
  }
  return svg('svg', { ...box, class: 'logo' }, svg('circle', { cx: 12, cy: 12, r: 6, fill: 'currentColor', opacity: .4 }));
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
  review: '리뷰', explore: '사전 조사', audit: '감사', arbitrate: '중재', test: '테스트', repro: '재현 테스트', testguard: '테스트 변경 감지', dedup: '중복 확인', base: '기준 커밋', stalled: '수렴 안 됨', design_only: '설계만', approved: '승인', unapproved: '미승인',
};
const PHASE = { init: '준비', explore: '사전 조사', debate: '설계 토론', build: '구현·리뷰', audit: '감사', done: '끝' };
const CHECK_STATUS = { ok: '정상', warn: '확인 필요', missing: '없음', error: '오류' };

function statusKey(run) { return run.stale ? 'stale' : run.status; }
function statusBadge(run, live) {
  const key = statusKey(run);
  return withTip(h('span', { class: `badge s-${key}${live ? ' live' : ''}` }, live ? '실행 중' : (STATUS[key] || key)), `status.${live ? 'running' : key}`);
}
function agentTag(name, role) {
  if (!name) return null;
  const base = String(name).replace(/^mock-/, '');
  // 워크플로 역할이 있으면 역할 이름을 보이고, 색은 CLI 기준 (DESIGN.md 19.1)
  return h('span', { class: `agent agent-${base === 'claude' ? 'claude' : base === 'codex' ? 'codex' : 'x'}`, title: role ? `${role} (${name})` : null },
    agentLogo(base, 12), role || name);
}
function verdictTag(v) {
  if (!v) return null;
  const label = v.status === 'APPROVED' ? '승인' : '반려';
  const extra = v.must_fix ? ` ${v.must_fix}` : '';
  const title = v.parse_failed ? '판정 블록이 없어 반려로 간주' : v.contradiction ? 'APPROVED 인데 must_fix>0 → 반려' : '';
  const base = v.status === 'APPROVED' ? TIPS.approved : TIPS.rejected_n;
  return h('span', { class: `verdict v-${v.status}`, 'data-tip': title ? `${base} (${title})` : base }, label + extra + (v.parse_failed || v.contradiction ? ' ?' : ''));
}
const TEST_STATUS = { passed: '통과', failed: '실패', error: '실행 불가', timeout: '시간 초과' };
function testTag(status) {
  if (!status) return null;
  return withTip(h('span', { class: `verdict t-${status}` }, `테스트 ${TEST_STATUS[status] || status}`), `test.${status}`);
}
const REPRO_LABEL = { failed: '재현됨', passed: '재현 안 됨', not_run: '실행 안 함', error: '실행 불가', timeout: '시간 초과' };
function reproTag(status) {
  if (!status || status === 'none') return null;
  const cls = status === 'failed' ? 'v-CHANGES_REQUESTED' : status === 'passed' ? 'v-APPROVED' : 't-error';
  return withTip(h('span', { class: `verdict ${cls}` }, REPRO_LABEL[status] || status), `repro.${status}`);
}
function decisionTag(hst) {
  if (!hst) return null;
  const why = (hst.reasons || []).join(' · ');
  const tip = (t) => why ? `${t} (${why})` : t;
  if (hst.approved) return h('span', { class: 'verdict v-APPROVED', 'data-tip': tip(hst.reviewer_status !== 'APPROVED' ? TIPS.approved_star : TIPS.approved) }, '승인' + (hst.reviewer_status !== 'APPROVED' ? ' *' : ''));
  return h('span', { class: 'verdict v-CHANGES_REQUESTED', 'data-tip': tip(TIPS.rejected_n) }, '반려' + (hst.blocking != null ? ` ${hst.blocking}` : ''));
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
function baseName(p) { return String(p).split(/[\\/]/).filter(Boolean).pop() || p; }  // Windows 경로도 (DESIGN.md 27)
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
// 확인 창. 브라우저의 confirm() 은 일부 내장 브라우저(앱 안 미리보기 등)에서 창을 띄우지 않고 바로 '취소'를
// 돌려줘서, 확인이 필요한 버튼(다시 시작·중지·목록에서 지우기·설치)이 아무 일도 안 하는 것처럼 보였다.
function askConfirm(message, { ok = '확인', danger = false } = {}) {
  return new Promise(resolve => {
    const box = h('dialog', { class: 'dialog confirm-dialog', 'aria-label': '확인' },
      h('div', { class: 'dialog-body' }, h('p', { class: 'confirm-text' }, message)),
      h('footer', { class: 'dialog-foot' },
        h('button', { class: 'btn', type: 'button', onclick: () => done(false) }, '취소'),
        h('button', { class: `btn ${danger ? 'btn-danger' : 'btn-primary'}`, type: 'button', 'data-ok': '', onclick: () => done(true) }, ok)));
    let settled = false;
    function done(v) {
      if (settled) return;
      settled = true;
      if (box.open) box.close();
      box.remove();
      resolve(v);
    }
    box.addEventListener('cancel', ev => { ev.preventDefault(); done(false); });   // Esc
    document.body.append(box);
    box.showModal();
    box.querySelector('[data-ok]').focus();
  });
}

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
// =================================================================== 쉬운 설명 (마우스를 올리면 뜨는 상자)
const TIPS = {
  // 메뉴
  'nav.home': '모든 프로젝트와 실행 기록을 봅니다.',
  'nav.setup': 'duet 가 쓰는 프로그램(Claude, Codex 등)이 설치·로그인되어 있는지 확인하고, 없으면 여기서 바로 설치·로그인합니다.',
  'nav.usage': '구독을 얼마나 썼는지 봅니다. 컴퓨터에 남은 기록만 읽어서, 이 화면을 본다고 사용량이 줄지는 않습니다.',
  'nav.settings': '자주 쓰는 폴더, 기본 모델, 다른 컴퓨터(원격 머신) 같은 기본값을 저장합니다.',
  new_run: '두 AI 에게 새 과제를 맡깁니다. 설계 토론 → 구현 → 서로 리뷰 순서로 알아서 진행됩니다.',
  // 새 실행 창
  machine: '어느 컴퓨터에서 돌릴지 고릅니다. 다른 컴퓨터는 설정 > 원격 머신에서 추가할 수 있습니다.',
  root: '프로젝트 폴더를 만들 상위 폴더입니다. 자주 쓰는 위치는 설정에 저장해 두면 여기에 나옵니다.',
  name: '새로 만들 프로젝트 폴더 이름입니다. "위치 / 이름"이 작업 폴더가 됩니다.',
  project: '프로젝트 폴더의 전체 경로입니다. 없는 폴더면 새로 만듭니다.',
  task: '무엇을 만들지 평소 말로 적으세요. 원하는 기능과 제약을 자세히 쓸수록 설계가 정확해집니다.',
  implementer: '코드를 직접 작성하고, 리뷰를 받으면 고치는 AI 입니다.',
  workflow: '미리 정해 둔 역할군과 단계 순서입니다. classic 은 아래의 구현·리뷰·종합 설정을 그대로 씁니다. 다른 워크플로는 역할을 템플릿에서 정합니다(duet workflows 로 목록 확인).',
  reviewer: '작성된 코드를 읽고 검사해서 승인하거나 반려하는 AI 입니다. 파일은 고칠 수 없습니다.',
  synth: '두 AI 의 설계안을 하나의 최종 설계(DESIGN.md)로 합치는 AI 입니다. 기본은 리뷰 담당이 합칩니다.',
  claude_model: 'Claude 의 어떤 모델을 쓸지 정합니다. 비워 두면 Claude 가 평소 쓰는 기본 모델입니다.',
  codex_model: 'Codex(ChatGPT)의 어떤 모델을 쓸지 정합니다. 비워 두면 기본 모델입니다.',
  effort: 'AI 가 얼마나 깊게 생각할지입니다. 높을수록 꼼꼼하지만 느리고 사용량을 더 씁니다. 단계별 기본은 단계마다 정해진 강도를 씁니다(Codex: 설계 종합·첫 리뷰 high, 나머지 medium). 값을 고르면 모든 단계에 그 값을 씁니다.',
  debate_rounds: '두 AI 가 서로의 설계안을 비판하고 고치는 횟수입니다. 0 이면 비판 없이 바로 합칩니다. 1 늘릴 때마다 AI 호출이 2번 늘어납니다.',
  max_review: '"구현 → 리뷰"를 최대 몇 번 반복할지입니다. 그 전에 승인되면 바로 끝납니다.',
  stall_rounds: '리뷰에서 고칠 것이 이 횟수만큼 연속으로 줄지 않으면 멈추고 사람에게 넘깁니다. 끝없이 반려만 반복되는 걸 막습니다. 0 이면 이 기능을 끕니다.',
  block_severity: '어느 정도 문제까지 반려할지입니다. P1 = 동작 안 함·보안 문제, P2 = 설계와 다름·흔한 입력에서 오류, P3 = 드문 입력·사소한 개선. 기본(P1·P2)은 사소한 것만 남으면 승인합니다.',
  test_command: '구현이 끝날 때마다 duet 가 직접 돌릴 테스트 명령입니다. 비우면 프로젝트를 보고 알아서 찾습니다. none 이라고 쓰면 테스트를 하지 않습니다.',
  design_only: '설계 토론까지만 하고 멈춥니다. 코드를 만들기 전에 설계를 먼저 읽어 보고 싶을 때 좋습니다.',
  skip_design: '이미 있는 DESIGN.md 로 바로 구현을 시작합니다. 설계를 직접 고친 뒤에 씁니다.',
  mock: '진짜 AI 를 부르지 않고 흉내만 냅니다. 화면과 흐름을 시험해 볼 때 씁니다. 사용량이 들지 않습니다.',
  force: '폴더에 아직 저장(커밋)하지 않은 변경이 있어도 시작합니다. 그 변경도 duet 의 첫 커밋에 같이 들어갑니다.',
  // 상태
  'status.running': '지금 진행 중입니다.',
  'status.done_approved': '리뷰에서 승인받고 끝났습니다.',
  'status.done_unapproved': '정한 횟수 안에 승인받지 못했거나, 고칠 것이 줄지 않아 멈췄습니다. 이어하기로 계속할 수 있습니다.',
  'status.done_design': '설계까지만 하고 끝났습니다. 구현하려면 새 실행에서 "설계 생략"을 고르세요.',
  'status.stopped_rate_limit': '구독 사용 한도에 걸려 멈췄습니다. 한도가 초기화된 뒤 이어하기를 누르세요.',
  'status.stopped_user': '중지 버튼(또는 Ctrl-C)으로 멈췄습니다. 이어하기를 누르면 멈춘 단계부터 다시 합니다.',
  'status.failed': 'AI 호출이나 git 작업이 반복해서 실패했습니다. 콘솔 탭에서 이유를 보고 이어하기를 누르세요.',
  'status.stale': '"진행 중"으로 기록돼 있는데 프로그램은 꺼져 있습니다(터미널을 닫았거나 컴퓨터가 꺼짐). 이어하기로 계속하세요.',
  'status.broken': '기록 파일(run.json)을 읽을 수 없습니다.',
  // 실행 화면
  resume: '멈춘 지점부터 이어서 진행합니다. 이미 끝난 단계는 다시 하지 않습니다.',
  resume_more: '리뷰 횟수 한도를 늘리고, 마지막 리뷰를 반영해 고치는 단계부터 이어갑니다.',
  stop: '지금 하던 AI 호출을 버리고 멈춥니다. 나중에 이어하기로 그 단계부터 다시 할 수 있습니다.',
  remove_project: '목록에서만 뺍니다. 폴더와 파일은 지우지 않습니다.',
  'tab.talk': '두 AI 가 주고받은 글을 순서대로 봅니다. 왼쪽에서 고르면 오른쪽에 내용이 나옵니다.',
  'tab.console': '진행 로그입니다. 터미널에 찍히는 것과 같습니다.',
  'tab.changes': '라운드마다 바뀐 코드입니다. 초록 줄은 추가, 빨강 줄은 삭제입니다.',
  'tab.design': '최종 설계 문서(DESIGN.md)입니다.',
  'step.propose': '각 AI 가 처음 내놓은 설계안입니다.',
  'step.critique': '상대 설계안의 약점을 지적하고, 배울 점을 반영해 자기 안을 고친 것입니다.',
  'step.synthesize': '두 안을 합친 최종 설계입니다. DESIGN.md 로 저장됩니다.',
  'step.implement': '설계대로 처음 코드를 작성한 AI 의 요약입니다.',
  'step.fix': '리뷰 지적을 반영해 고친 내용의 요약입니다.',
  'step.test': 'duet 가 직접 돌린 테스트 결과입니다. 실패하면 리뷰어가 승인해도 승인되지 않습니다.',
  'step.dedup': '작은 모델이 새 지적이 이미 해결·기각된 지적의 반복인지 확인한 결과입니다. 기각된 지적의 재제기는 P3 로 낮추고, 해결된 지적의 재발은 표시만 합니다.',
  'nav.bench': '벤치마크 결과(워크플로별 승인률·숨은 테스트 통과율·비용)를 봅니다.',
  prune: '목록(~/.duet/projects.json)에서만 지웁니다. 폴더와 파일은 건드리지 않습니다.',
  'tab.issues': '지적 원장(리뷰어별 지적의 흐름), 중재 결정, 관문 강등, 중복 확인, 테스트 변경·되돌림 경고를 한곳에서 봅니다.',
  arbiter: '리뷰가 수렴하지 않거나 상한에 닿았을 때 한 번 열린 지적을 유지·완화·기각으로 정리한 결과입니다.',
  'step.testguard': '구현자가 테스트를 지우거나 약하게 바꾼 흔적입니다(테스트·단언 수 감소, skip 추가, 설정 변경). 막지는 않고 리뷰어에게 경고로 보여 줍니다.',
  'step.review': '상대 AI 의 코드 리뷰와 판정입니다.',
  'step.pending': '지금 이 AI 가 일하는 중입니다. 누르면 무슨 파일을 읽고 고치는지, 어떤 명령을 돌리는지 실시간으로 봅니다.',
  'step.repro': '리뷰어가 지적을 글 대신 "실패하는 테스트"로 낸 것입니다. duet 가 저장해서 정말 실패하는지 돌려 봅니다.',
  'repro.failed': '재현됨: 지금 코드에서 실제로 실패합니다. 리뷰어의 지적이 맞고, 구현자가 이 테스트를 통과시켜야 합니다.',
  'repro.passed': '재현 안 됨: 지금 코드에서도 통과합니다. 지적이 틀렸거나 테스트가 문제를 못 짚었습니다.',
  'repro.not_run': '테스트 명령이 없어 재현 테스트를 돌리지 못했습니다.',
  'repro.error': '재현 테스트를 실행하지 못했습니다(환경 문제일 수 있음).',
  'repro.timeout': '재현 테스트가 시간 안에 끝나지 않았습니다.',
  live_view: '에이전트가 남기는 기록을 읽어 2초마다 보여줍니다. 읽기 = 파일을 열어 봄, 수정 = 파일을 고침, 명령 = 터미널 명령 실행.',
  review_diff: '켜 두면 2번째 리뷰부터 지난 리뷰 이후 바뀐 부분만 리뷰어에게 보여줍니다. 리뷰 한 번에 드는 토큰이 크게 줄어듭니다.',
  repro_tests: '켜 두면 리뷰어가 지적을 "실패하는 테스트"로 낼 수 있습니다. duet 가 저장해 돌려 보고, 구현자는 그 테스트를 통과시켜야 합니다.',
  approved_star: '리뷰어는 반려했지만, 남은 지적이 반려 기준보다 가벼워서 duet 가 승인했습니다.',
  approved: '승인되었습니다.',
  rejected_n: '반려되었습니다. 숫자는 반려 기준에 걸린 "반드시 고칠 것"의 개수입니다.',
  'test.passed': 'duet 가 돌린 테스트가 모두 통과했습니다.',
  'test.failed': 'duet 가 돌린 테스트가 실패했습니다. 이 라운드는 승인되지 않습니다.',
  'test.error': '테스트 명령을 실행하지 못했습니다(명령이 없거나 테스트가 0개). 코드 문제가 아닐 수 있어 승인을 막지는 않습니다.',
  'test.timeout': '테스트가 시간 안에 끝나지 않았습니다. 승인되지 않습니다.',
  base: '구현을 시작하기 직전의 저장 지점(git 커밋)입니다. 변경 사항은 이 지점과 비교합니다.',
  usage_cost: '같은 양을 API 로 썼다면 드는 요금의 추정치입니다. 실제로 내는 구독 요금과는 별개입니다.',
  tokens: '토큰은 AI 가 글을 세는 단위(글자 조각)입니다. 입력은 AI 가 읽은 양, 출력은 AI 가 쓴 양입니다.',
  rounds: '라운드마다 구현 → 테스트 → 리뷰가 어떻게 됐는지 한 줄로 봅니다.',
  // 환경·로그인
  'tool.duet': 'duet 자체와, 그걸 돌리는 Python 입니다.',
  'tool.git': '코드 변경 이력을 저장하는 프로그램입니다. duet 가 라운드마다 저장(커밋)합니다. 꼭 필요합니다.',
  'tool.curl': '인터넷에서 설치 파일을 받는 프로그램입니다. Claude·Codex·uv 를 설치할 때 필요합니다.',
  'tool.uv': 'Python 도구 설치 프로그램입니다. 다른 컴퓨터에 Python 을 설치할 때 씁니다. 없어도 됩니다.',
  'tool.claude': 'Claude 를 터미널에서 쓰는 공식 프로그램입니다. Claude 구독 계정으로 로그인해야 합니다.',
  'tool.codex': 'ChatGPT(Codex)를 터미널에서 쓰는 공식 프로그램입니다. ChatGPT 계정으로 로그인해야 합니다.',
  'tool.api_keys': '이 변수가 있으면 Claude·Codex 가 구독 대신 API 요금으로 계산할 수 있습니다. duet 는 기본으로 빼고 넘깁니다.',
  recheck: '설치·로그인 상태를 다시 확인합니다.',
  term_input: '로그인 코드나 질문의 답을 여기에 붙여 넣고 Enter 를 누르세요.',
  term_secret: '비밀번호처럼 화면에 보이면 안 되는 값을 입력할 때 켜세요.',
  term_kill: '진행 중인 설치·로그인을 멈춥니다.',
  deploy: '이 컴퓨터의 duet 를 원격 머신에 복사합니다. duet 를 업데이트한 뒤에도 누르세요.',
  'remote.ssh': '이 컴퓨터에서 원격 머신으로 접속되는지 봅니다. 비밀번호 없이 접속되게 미리 ssh-copy-id 를 해 두어야 합니다.',
  'remote.python': '원격 머신에 Python 3.11 이상이 있는지 봅니다. duet 를 돌리는 데 필요합니다.',
  'remote.duet': '원격 머신에 duet 가 복사되어 있고 최신인지 봅니다.',
  // 사용량
  codex_limit: 'ChatGPT 구독의 Codex 사용 한도 중 얼마나 썼는지입니다. 100% 가 되면 초기화 시각까지 Codex 를 못 씁니다.',
  claude_tokens: 'Claude 는 남은 한도를 알려주지 않아서, 이 컴퓨터에서 쓴 양(토큰)을 대신 보여줍니다. 남은 한도는 claude 를 켜고 /usage 로 볼 수 있습니다.',
  duet_usage: 'duet 실행이 쓴 양만 따로 모았습니다.',
  // 설정
  roots: '새 실행에서 고를 수 있는 상위 폴더 목록입니다. 첫 번째가 기본으로 선택됩니다.',
  'machine.id': '이 머신을 부를 짧은 영문 이름입니다(예: lab). 나중에 바꿀 수 없습니다.',
  'machine.name': '화면에 보일 이름입니다(예: 연구실 서버).',
  'machine.ssh': '접속 주소입니다. 사용자@호스트 형식(예: me@lab.example.com). 비밀번호 없이 접속되게 미리 ssh-copy-id 를 해 두세요.',
  'machine.port': 'SSH 포트입니다. 보통 22 입니다.',
  'machine.root': '원격 머신에서 프로젝트 폴더를 만들 위치입니다(예: ~/duet-projects).',
  require_tests: '켜 두면 테스트가 실패했을 때 리뷰어가 승인해도 승인하지 않습니다.',
  restart: 'UI 서버를 다시 켭니다. 같은 주소로 다시 뜨고, 진행 중인 실행은 영향이 없습니다.',
  update: 'duet 프로그램이 바뀌었습니다. 다시 시작해야 새 기능이 화면에 나옵니다.',
};

function tipText(key) { return TIPS[key] || null; }
function withTip(el, key) {
  const t = TIPS[key] || (key && key.length > 30 ? key : null);
  if (t && el) el.setAttribute('data-tip', t);
  return el;
}
function help(key) {
  const t = TIPS[key];
  if (!t) return null;
  return h('span', { class: 'help', 'data-tip': t, tabindex: '0', role: 'button', 'aria-label': `도움말: ${t}` }, '?');
}

// 툴팁 상자 하나를 띄우고 옮긴다. 모달 창(dialog) 안에서는 그 안에 붙여야 위에 보인다.
const tipEl = document.createElement('div');
tipEl.className = 'tooltip';
tipEl.setAttribute('role', 'tooltip');
tipEl.hidden = true;
let tipTimer = null, tipTarget = null, tipPinned = false;
function showTip(target) {
  const text = target.getAttribute('data-tip');
  if (!text) return;
  const host = target.closest('dialog[open]') || document.body;
  if (tipEl.parentNode !== host) host.append(tipEl);
  tipTarget = target;
  tipEl.textContent = text;
  tipEl.hidden = false;
  const r = target.getBoundingClientRect();
  const tw = tipEl.offsetWidth, th = tipEl.offsetHeight;
  let left = r.left + r.width / 2 - tw / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));
  let top = r.top - th - 8;
  if (top < 8) top = r.bottom + 8;
  tipEl.style.left = `${left}px`;
  tipEl.style.top = `${top}px`;
}
function hideTip() {
  clearTimeout(tipTimer);
  tipTimer = null;
  tipTarget = null;
  tipPinned = false;
  tipEl.hidden = true;
}
document.addEventListener('mouseover', ev => {
  const t = ev.target.closest && ev.target.closest('[data-tip]');
  if (t === tipTarget) return;
  clearTimeout(tipTimer);
  if (!t) { if (tipTarget && !tipPinned) hideTip(); return; }
  if (tipPinned) return;
  tipTimer = setTimeout(() => showTip(t), t.classList.contains('help') ? 0 : 350);
});
document.addEventListener('focusin', ev => { const t = ev.target.closest && ev.target.closest('[data-tip]'); if (t) showTip(t); });
document.addEventListener('focusout', () => { if (!tipPinned) hideTip(); });
document.addEventListener('scroll', () => hideTip(), true);
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') hideTip(); });
// "?" 는 눌러도 뜬다(휴대폰). label 안에 있어도 체크박스가 바뀌지 않게 막는다.
document.addEventListener('click', ev => {
  const t = ev.target.closest && ev.target.closest('.help');
  if (!t) { if (tipPinned) hideTip(); return; }
  // 누르면 항상 띄우고 고정한다(휴대폰은 마우스 올림이 없음). 다른 곳을 누르면 닫힌다.
  ev.preventDefault();
  ev.stopPropagation();
  clearTimeout(tipTimer);
  showTip(t);
  tipPinned = true;
}, true);
// HTML 에 data-help="키" 로 표시한 곳에 "?" 를 붙인다
function decorateHelp(root = document) {
  root.querySelectorAll('[data-help]').forEach(el => {
    if (el.querySelector(':scope > .help')) return;
    const node = help(el.getAttribute('data-help'));
    if (node) el.append(' ', node);
  });
  root.querySelectorAll('[data-nav]').forEach(a => withTip(a, `nav.${a.getAttribute('data-nav')}`));
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
    if (parts[0] === 'bench') return { name: 'bench', machine: q.get('m') || LOCAL, dir: q.get('dir') || '' };
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
  const V = { run: RunView, project: ProjectView, setup: SetupView, usage: UsageView, settings: SettingsView, bench: BenchView }[r.name] || HomeView;
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

// =================================================================== 목록 필터 (DESIGN.md 28.2)
const listFilter = (() => {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('duet.listFilter') || '{}'); } catch { saved = {}; }
  return { query: '', bench: !!saved.bench, missing: !!saved.missing };
})();
function saveListFilter() {
  try { localStorage.setItem('duet.listFilter', JSON.stringify({ bench: listFilter.bench, missing: listFilter.missing })); } catch { /* 사생활 보호 모드 등 */ }
}
function projectVisible(p) {
  if (!listFilter.missing && !p.exists) return false;
  if (!listFilter.bench && p.bench) return false;
  const q = listFilter.query.trim().toLowerCase();
  return !q || `${p.display || p.name} ${p.path}`.toLowerCase().includes(q);
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
    h('div', { class: 'side-title' }, g.local ? '이 머신' : g.name, g.error ? h('span', { class: 'warn-dot', 'data-tip': g.error }) : null),
    h('ul', null, g.projects.filter(projectVisible).length ? g.projects.filter(projectVisible).map(p => {
      const st = p.latest ? statusKey(p.latest) : '';
      return h('li', null, h('a', {
        href: hrefProject(g.id, p.path), 'data-tip': p.path,
        class: (r.project === p.path && (r.machine || LOCAL) === g.id ? 'active' : null),
      }, h('span', { class: `dot s-${p.live ? 'running live' : st}` }), h('span', { class: 'name' }, p.display || p.name)));
    }) : h('li', { class: 'empty' }, g.error ? h('a', { href: `#/setup?m=${enc(g.id)}`, 'data-tip': g.error }, '확인 필요 → 환경·로그인') : '없음')))));
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
    const allProjects = app.groups.flatMap(g => g.projects);
    const nBench = allProjects.filter(p => p.bench).length;
    const nMissing = allProjects.filter(p => !p.exists).length;
    const search = h('input', { type: 'search', placeholder: '이름·경로로 찾기', value: listFilter.query, spellcheck: 'false',
      oninput: ev => {
        listFilter.query = ev.target.value;
        const pos = ev.target.selectionStart;
        this.render(); refreshSidebar();
        const el = this.main.querySelector('.list-tools input[type=search]');
        if (el) { el.focus(); el.setSelectionRange(pos, pos); }
      } });
    const toggle = (key, label, n) => n ? h('label', { class: 'toggle' }, h('input', { type: 'checkbox', checked: listFilter[key] ? true : null,
      onchange: ev => { listFilter[key] = ev.target.checked; saveListFilter(); this.render(); refreshSidebar(); } }), `${label} ${n}개 보기`) : null;
    const tools = h('div', { class: 'list-tools' }, search,
      toggle('bench', '벤치마크 실행', nBench), toggle('missing', '폴더 없는 프로젝트', nMissing),
      nBench ? h('a', { class: 'btn btn-sm', href: '#/bench' }, '벤치마크 결과') : null);
    const sections = app.groups.map(g => {
      const hiddenMissing = g.projects.filter(p => !p.exists).length;
      const cards = g.projects.filter(projectVisible).map(p => {
        const l = p.latest;
        return h('a', { class: 'card project-card', href: hrefProject(g.id, p.path) },
          h('div', { class: 'row' }, h('h3', null, p.display || p.name), h('span', { class: 'spacer' }),
            p.live ? statusBadge({ status: 'running' }, true) : l ? statusBadge(l) : h('span', { class: 'badge plain' }, '기록 없음')),
          h('div', { class: 'path' }, p.path),
          l ? h('div', { class: 'task' }, oneLine(l.task, 160)) : null,
          h('div', { class: 'meta' },
            h('span', null, `실행 ${p.run_count}개`),
            l ? h('span', null, `${PHASE[l.phase] || l.phase} · ${STEP[l.step] || l.step || '-'}`) : null,
            l && l.last_verdict ? verdictTag({ status: l.last_verdict }) : null,
            l ? h('span', null, fmtWhen(l.updated_at)) : null,
            p.bench ? h('span', { class: 'badge plain' }, '벤치마크') : null,
            p.exists ? null : h('span', { class: 'badge s-failed' }, '폴더 없음')));
      });
      const jobs = (g.jobs || []).filter(j => j.running || j.returncode !== 0).slice(0, 4);
      return h('section', { class: 'machine-section' },
        h('div', { class: 'machine-head' },
          h('h2', null, g.local ? '이 머신' : g.name),
          g.local ? null : h('span', { class: 'mono' }, g.ssh),
          g.error ? h('span', { class: 'badge s-failed' }, '연결 안 됨') : null,
          h('span', { class: 'spacer' }),
          hiddenMissing ? withTip(h('button', { class: 'btn btn-sm', type: 'button', onclick: () => this.prune(g) },
            `없는 폴더 ${hiddenMissing}개 목록에서 지우기`), 'prune') : null,
          h('a', { class: 'btn btn-sm', href: `#/setup?m=${enc(g.id)}` }, '환경·로그인'),
          withTip(h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: () => openRunDialog({ machine: g.id }) }, '새 실행'), 'new_run')),
        g.error ? h('div', { class: 'alert alert-warn' }, h('span', null, g.error)) : null,
        cards.length ? h('div', { class: 'grid' }, cards)
          : g.error ? null : h('div', { class: 'card empty-state small' },
            g.projects.length ? '조건에 맞는 프로젝트가 없습니다. 검색어나 위의 보기 설정을 바꿔 보세요.' : '아직 프로젝트가 없습니다. ‘새 실행’으로 시작하세요.'),
        jobs.length ? h('div', { class: 'jobs' }, jobs.map(jobCard)) : null);
    });
    const form = h('form', { class: 'add-form', onsubmit: ev => this.add(ev) },
      h('input', { type: 'text', name: 'path', placeholder: '절대 경로 (/home/me/proj, C:\\work\\proj) — 이 머신의 기존 작업 폴더를 목록에 추가', value: this.addValue, spellcheck: 'false', autocomplete: 'off' }),
      h('button', { class: 'btn', type: 'submit' }, '추가'));
    const noRemote = app.groups.length === 1;
    this.main.replaceChildren(h('div', { class: 'page' },
      h('div', { class: 'page-head' },
        h('div', null, h('h1', null, '프로젝트'), h('div', { class: 'muted' }, '두 모델이 설계를 토론하고 서로의 코드를 리뷰한 기록을 봅니다.')),
        h('span', { class: 'spacer' }),
        h('button', { class: 'btn btn-primary', type: 'button', onclick: () => openRunDialog({}) }, '새 실행')),
      allProjects.length ? tools : null, sections, form,
      noRemote ? h('p', { class: 'muted small' }, '다른 머신에서도 돌리려면 ', h('a', { href: '#/settings' }, '설정 > 원격 머신'), '에서 SSH 머신을 추가하세요.') : null));
  }
  async prune(g) {
    const n = g.projects.filter(p => !p.exists).length;
    if (!(await askConfirm(`폴더가 없는 프로젝트 ${n}개를 목록에서 지웁니다. 파일은 건드리지 않습니다.`, { ok: '목록에서 지우기' }))) return;
    try {
      const r = await api('/api/projects/prune', { method: 'POST', machine: g.id });
      toast(`${r.removed.length}개를 목록에서 지웠습니다.`);
      schedule(this, 0);
    } catch (e) { toast(e.message, true); }
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
        live ? withTip(h('button', { class: 'btn btn-danger', type: 'button', onclick: () => stopRun(m, d.project) }, '중지'), 'stop') : null,
        withTip(h('button', { class: 'btn', type: 'button', onclick: () => this.remove() }, '목록에서 제거'), 'remove_project'),
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
          h('td', { class: 'task-cell' }, h('div', { class: 'ellipsis', 'data-tip': run.task }, oneLine(run.task, 90))),
          h('td', { class: 'nowrap small' }, `${PHASE[run.phase] || run.phase || '-'} · ${STEP[run.step] || run.step || '-'}${run.round ? ` · ${run.round}회차` : ''}`),
          h('td', null, verdictTag(run.last_verdict ? { status: run.last_verdict } : null)),
          h('td', { class: 'nowrap small' }, `${run.calls}회 · ${fmtDur(run.total_sec)}`),
          h('td', { class: 'nowrap small muted' }, fmtWhen(run.updated_at)))))));
    }
    this.main.replaceChildren(h('div', { class: 'page' }, head, banner, tabs, body));
  }
  async remove() {
    if (!(await askConfirm(`목록에서만 제거합니다. 파일은 지우지 않습니다.\n\n${this.r.project}`, { ok: '목록에서 제거' }))) return;
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
  roleChips(st, c) {
    const wf = st.workflow;
    if (!wf) {
      return [
        c.skip_design ? h('span', { class: 'chip' }, '설계 생략') : h('span', { class: 'chip' }, '종합 ', h('b', null, c.synth), ` · 토론 ${c.debate_rounds}라운드`),
        c.design_only ? h('span', { class: 'chip' }, '설계만') : h('span', { class: 'chip' }, '구현 ', h('b', null, c.implementer), ' · 리뷰 ', h('b', null, c.reviewer), ` · 최대 ${c.max_review}회`),
      ];
    }
    const roleOf = n => { const r = (wf.roles || {})[n] || {}; return `${n}(${r.agent || '?'}${r.model ? ' ' + r.model : ''})`; };
    const chips = [withTip(h('span', { class: 'chip' }, '워크플로 ', h('b', null, wf.name)), 'workflow')];
    for (const s of wf.steps || []) {
      if (s.kind === 'explore') chips.push(h('span', { class: 'chip' }, '조사 ', h('b', null, roleOf(s.role))));
      if (s.kind === 'debate') chips.push(h('span', { class: 'chip' }, c.skip_design ? '설계 생략' : `설계 ${(s.proposers || []).map(roleOf).join(', ')}${s.synth ? ' → ' + s.synth : ''}`));
      if (s.kind === 'build' && !c.design_only) chips.push(h('span', { class: 'chip' }, '구현 ', h('b', null, roleOf(s.implementer)), ' · 리뷰 ', h('b', null, (s.reviewers || []).map(roleOf).join(', ')), ` · 최대 ${c.max_review}회`));
      if (s.kind === 'audit' && !c.design_only) chips.push(h('span', { class: 'chip' }, '감사 ', h('b', null, (s.roles || []).map(roleOf).join(', '))));
    }
    return chips;
  }

  renderHead() {
    const d = this.data, st = d.state, c = st.config || {};
    const run = { status: st.status, stale: d.stale };
    const pos = `${PHASE[st.phase] || st.phase} · ${STEP[st.step] || st.step || '-'}${st.round ? ` · ${st.round}회차` : ''}`;
    const totalSec = st.calls.reduce((a, x) => a + (x.sec || 0), 0);
    const modelOf = a => (c[`${a}.model`] || '기본') + (c[`${a}.effort`] ? ` · ${c[`${a}.effort`]}` : '');
    const chips = h('div', { class: 'chips' },
      this.m !== LOCAL ? h('span', { class: 'chip' }, '머신 ', h('b', null, machineName(this.m))) : null,
      ...this.roleChips(st, c),
      h('span', { class: 'chip' }, 'claude ', h('b', null, modelOf('claude'))),
      h('span', { class: 'chip' }, 'codex ', h('b', null, modelOf('codex'))),
      c.mock ? h('span', { class: 'chip' }, 'mock') : null,
      c.block_severity ? h('span', { class: 'chip' }, '반려 기준 ', h('b', null, { P1: 'P1', P2: 'P1·P2', P3: 'P1·P2·P3' }[c.block_severity] || c.block_severity)) : null,
      c.test_command ? h('span', { class: 'chip' }, '테스트 ', h('b', null, c.test_command === 'auto' ? '자동' : c.test_command)) : null,
      st.base_commit ? withTip(h('span', { class: 'chip' }, '기준 ', h('b', { class: 'mono' }, st.base_commit)), 'base') : null,
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
      h('span', { class: 'faint small' }, '사용량', help('tokens')),
      Object.entries(totals).map(([a, t]) => withTip(h('span', { class: 'chip tok' }, agentTag(a), ' ', usageLine(t)), t.cost_usd ? 'usage_cost' : 'tokens'))) : null;

    const alerts = [];
    if (d.stale) alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '멈춤'),
      h('span', null, '상태는 ‘실행 중’인데 duet 프로세스가 없습니다. 터미널이 닫혔거나 비정상 종료된 것 같습니다. 이어하기로 계속할 수 있습니다.')));
    if (st.error && !d.live) alerts.push(h('div', { class: `alert ${st.status === 'failed' ? 'alert-bad' : 'alert-warn'}` },
      h('b', null, STATUS[st.status] || st.status), h('span', null, st.error)));
    if (st.stop_reason === 'stalled' && !d.live) alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '수렴 안 됨'),
      h('span', null, `막는 지적 수가 ${c.stall_rounds || 2}라운드 연속 줄지 않아 멈췄습니다 (${(st.review_history || []).map(x => x.blocking ?? '?').join(' → ')}). 마지막 리뷰를 읽고 직접 판단하거나, 이어하기로 계속할 수 있습니다.`)));
    const arb = st.arbiter || {};
    if (st.stop_reason === 'arbiter') alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '중재로 승인'),
      h('span', null, `리뷰가 수렴하지 않아 중재자가 열린 지적을 정리했고, 막는 지적이 남지 않아 승인했습니다 (완화 ${(arb.downgraded || []).join(', ') || '-'}, 기각 ${(arb.rejected || []).join(', ') || '-'}). 중재 결과(${arb.file || ''})를 확인하세요.`)));
    if ((st.stop_reason === 'arbiter_upheld' || st.stop_reason === 'arbiter_final') && !d.live) alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '중재 뒤에도 미승인'),
      h('span', null, `중재자가 유지한 지적(${(arb.upheld || []).join(', ') || '테스트 실패'})이 해결되지 않았습니다. 중재 결과와 마지막 리뷰를 보고 직접 판단하세요.`)));
    if (st.limit_wait && d.live) alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '한도 대기 중'),
      h('span', null, `${st.limit_wait.role || st.limit_wait.agent} 의 구독 한도에 걸려 ${String(st.limit_wait.until || '').replace('T', ' ').slice(5, 16)} 에 다시 시도합니다 (${st.limit_wait.reason || ''}). 지금 멈추려면 중지를 누르세요.`)));
    const guards = Object.entries(st.test_guard || {}).filter(([, g]) => (g.signals || []).length);
    if (guards.length) alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '테스트 변경 감지'),
      h('span', null, `구현자가 테스트를 지우거나 약하게 바꾼 흔적이 있습니다 (${guards.map(([r, g]) => `${r}라운드 ${g.signals.length}건`).join(', ')}). 리뷰어에게 경고로 전달했습니다. 기록(${guards.map(([, g]) => g.file).join(', ')})을 확인하세요.`)));
    const reverts = Object.entries(st.reverts || {}).filter(([, g]) => (g.reverts || []).length);
    if (reverts.length) alerts.push(h('div', { class: 'alert alert-warn' }, h('b', null, '되돌림 감지'),
      h('span', null, `구현자가 해결됐던 지적의 코드를 되살린 흔적이 있습니다 (${reverts.map(([r, g]) => `${r}라운드: ${g.reverts.map(x => x.file).join(', ')}`).join(' / ')}). 리뷰어에게 경고로 전달했습니다.`)));
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
      box.append(withTip(h('button', { class: 'btn btn-danger', type: 'button', onclick: () => stopRun(this.m, d.project) }, '중지'), 'stop'));
      return box;
    }
    if (hint.possible) {
      let input = null;
      if (hint.needs_max_review) {
        input = h('input', { type: 'number', min: hint.current_max_review + 1, max: 10, value: Math.min(hint.current_max_review + 1, 10), 'aria-label': '리뷰 최대 횟수' });
        box.append(h('label', null, '리뷰 최대', input, '회까지', help('max_review')));
      }
      box.append(h('button', { class: 'btn btn-primary', type: 'button', onclick: async ev => {
        ev.target.disabled = true;
        try {
          await api('/api/actions/resume', { method: 'POST', machine: this.m,
            body: { project: d.project, run: d.state.run_id, max_review: input ? Number(input.value) : undefined } });
          toast('이어하기를 시작했습니다. 잠시 뒤 진행 상황이 보입니다.');
          schedule(this, 1200);
        } catch (e) { toast(e.message, true); ev.target.disabled = false; }
      }, 'data-tip': hint.needs_max_review ? TIPS.resume_more : TIPS.resume }, hint.needs_max_review ? '리뷰 계속하기' : '이어하기'));
    }
    return box;
  }
  roundsSummary() {
    const st = this.data.state;
    // 리뷰어가 여럿이면 리뷰 파일마다 그 리뷰어의 판정을 보인다 (합산 판정은 review_history 의 바깥 필드)
    const hist = {};
    for (const x of st.review_history || []) {
      if (x.reviewers) for (const r of x.reviewers) hist[r.file] = r;
      else hist[x.file] = x;
    }
    const entries = this.data.entries.filter(e => e.meta.step === 'test' || e.meta.step === 'repro' || (e.meta.ok !== 'false' && !e.label.endsWith('_failed')));
    const items = [];
    for (const e of entries) {
      const s = e.meta.step;
      if (s === 'implement' || s === 'fix') items.push(h('span', { class: 'chip' }, `${e.meta.round}회차 ${STEP[s]}`));
      else if (s === 'test') items.push(h('span', { class: 'arrow' }, '→'), testTag(e.meta.test_status));
      else if (s === 'repro') items.push(h('span', { class: 'arrow' }, '→'), withTip(h('span', { class: 'chip' }, `재현 테스트 ${e.meta.repro_files || 0}개 `, reproTag(e.meta.repro_status)), 'step.repro'));
      else if (s === 'review') {
        items.push(h('span', { class: 'arrow' }, '→'));
        items.push(h('span', { class: 'chip' }, e.meta.role ? `리뷰(${e.meta.role}) ` : '리뷰 ', hist[e.name] ? decisionTag(hist[e.name]) : verdictTag(e.verdict)));
      }
    }
    if (!items.length) return null;
    return h('div', { class: 'rounds' }, h('span', { class: 'faint small' }, '리뷰 이력', help('rounds')), items);
  }

  // ---------------------------------------------------------------- tabs
  renderTabs() {
    const d = this.data, t = this.r.tab;
    const mk = (key, label, count) => h('a', { href: hrefRun(this.m, this.r.project, this.r.run, key), class: t === key ? 'active' : null,
      'data-tip': TIPS[`tab.${key}`] }, label, count !== undefined ? h('span', { class: 'count' }, count) : null);
    const s = d.state;
    const nIssues = (s.issues || []).length;
    this.tabsSlot.replaceChildren(
      mk('talk', '대화', d.entries.length),
      this.hasFindings() ? mk('issues', '지적', nIssues || undefined) : null,
      mk('console', '콘솔'), mk('changes', '변경 사항'), mk('design', '설계 문서'));
  }
  hasFindings() {
    const s = this.data.state;
    return !!((s.issues || []).length || s.arbiter || Object.keys(s.test_guard || {}).length
      || Object.keys(s.reverts || {}).length || Object.keys(s.dedup || {}).length);
  }
  async renderPanel(force) {
    const t = this.r.tab;
    if (t === 'issues' && this.hasFindings()) return this.renderIssues();
    if (t === 'console') return this.renderConsole(force);
    if (t === 'changes') return this.renderChanges(force);
    if (t === 'design') return this.renderDesign(force);
    return this.renderTalk(force);
  }

  // ---------------------------------------------------------------- issues (DESIGN.md 28.5)
  renderIssues() {
    const s = this.data.state;
    const ST = { open: '열림', resolved: '해결', rejected: '기각' };
    const STC = { open: 's-done_unapproved', resolved: 's-done_approved', rejected: 's-stopped_user' };
    const BASIS = { requirement: '요구 위반', correctness: '정확성', security: '보안', preference: '취향' };
    const DOWN = { evidence: '근거 없음', scope: '범위 밖', spec: '요구 근거', repeat: '재제기', arbiter: '중재 후' };
    const issues = s.issues || [];
    const table = issues.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'plain issues' },
      h('thead', null, h('tr', null, ['ID', '리뷰어', '심각도', '지적', '근거 종류', '상태', '라운드', '메모'].map(t => h('th', null, t)))),
      h('tbody', null, issues.map(x => h('tr', { class: x.status !== 'open' ? 'closed' : null },
        h('td', { class: 'mono' }, x.id),
        h('td', null, agentTag(this.cliOf(x.role), x.role)),
        h('td', null, h('span', { class: `sev sev-${x.severity}` }, x.severity)),
        h('td', null, h('div', null, x.title), x.file ? h('div', { class: 'mono small faint' }, x.file) : null,
          x.requirement ? h('div', { class: 'small quote' }, `«${x.requirement}»`) : null),
        h('td', { class: 'small' }, BASIS[x.basis] || '-'),
        h('td', null, h('span', { class: `badge ${STC[x.status] || ''}` }, ST[x.status] || x.status)),
        h('td', { class: 'mono small' }, `${x.round} → ${x.closed_round ?? '…'}`),
        h('td', { class: 'small' }, x.note || '')))))) : null;

    const a = s.arbiter;
    const arbiterCard = a ? h('div', { class: 'card card-pad' },
      h('h3', null, '중재', help('arbiter')),
      h('div', { class: 'chips' },
        h('span', { class: 'chip' }, `${a.round}라운드 · ${a.reason === 'stalled' ? '수렴 실패' : '리뷰 상한'}`),
        h('span', { class: 'chip' }, '결과 ', h('b', null, { approved: '승인', continue: '마지막 라운드', stop: '멈춤', unreadable: '읽지 못함' }[a.result] || a.result || '?')),
        h('span', { class: 'chip' }, `유지 ${(a.upheld || []).join(', ') || '-'}`),
        h('span', { class: 'chip' }, `완화 ${(a.downgraded || []).join(', ') || '-'}`),
        h('span', { class: 'chip' }, `기각 ${(a.rejected || []).join(', ') || '-'}`),
        a.file ? h('a', { class: 'chip', href: hrefRun(this.m, this.r.project, this.r.run, 'talk'), onclick: () => { this.selected = a.file; } }, '중재 기록 보기') : null)) : null;

    const rounds = (s.review_history || []).map(hst => {
      const items = [];
      const down = { ...(hst.downgraded || {}) };
      for (const rv of hst.reviewers || []) for (const [k, n] of Object.entries(rv.downgraded || {})) down[k] = (down[k] || 0) + n;
      const downs = Object.entries(down).filter(([, n]) => n);
      if (downs.length) items.push(h('div', null, h('b', null, '관문 강등 '), downs.map(([k, n]) => h('span', { class: 'chip' }, `${DOWN[k] || k} ${n}`))));
      for (const [key, dd] of Object.entries(s.dedup || {})) {
        if (!key.startsWith(`${hst.round}:`)) continue;
        const m = Object.entries(dd.matches || {});
        items.push(h('div', null, h('b', null, `중복 확인(${key.split(':')[1]}) `),
          dd.result ? h('span', { class: 'chip' }, dd.result === 'failed' ? '실패(건너뜀)' : '읽지 못함')
            : m.length ? m.map(([n, x]) => h('span', { class: 'chip', 'data-tip': x.reason }, `${n} → ${x.old_id}`)) : h('span', { class: 'chip' }, '반복 없음')));
      }
      const g = (s.test_guard || {})[hst.round];
      if (g && (g.signals || []).length) items.push(h('div', null, h('b', null, '테스트 변경 경고 '),
        g.signals.map(x => h('span', { class: 'chip warn', 'data-tip': x.detail }, `${x.file}`))));
      const rv = (s.reverts || {})[hst.round];
      if (rv && (rv.reverts || []).length) items.push(h('div', null, h('b', null, '되돌림 경고 '),
        rv.reverts.map(x => h('span', { class: 'chip warn' }, `${x.file} (${x.issues.join(', ')})`))));
      if (!items.length) return null;
      return h('div', { class: 'round-findings' }, h('h4', null, `${hst.round}라운드`, ' ', decisionTag(hst)), items);
    }).filter(Boolean);

    this.panelSlot.replaceChildren(h('div', { class: 'issues-panel' },
      arbiterCard,
      table || h('p', { class: 'muted' }, '지적 원장이 없습니다 (JSON 판정을 끈 실행이거나 막는 지적이 없었습니다).'),
      rounds.length ? h('div', { class: 'card card-pad' }, h('h3', null, '라운드별'), rounds) : null));
    this.panelBuilt = 'issues';
  }
  cliOf(role) {
    const wf = this.data.state.workflow;
    return (wf && wf.roles && wf.roles[role] && wf.roles[role].agent) || role;
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
    if (d.live && (!this.selected || this.autoLive)) { this.selected = LIVE; this.autoLive = true; }
    if (!d.live && this.selected === LIVE) this.selected = null;
    if (!this.selected && d.entries.length) this.selected = d.entries[d.entries.length - 1].name;
    this.renderTimeline();
    const changed = d.entries.length !== this.lastEntryCount;
    this.lastEntryCount = d.entries.length;
    if (force || changed || this.selected === LIVE || !this.viewerEl.childNodes.length) await this.renderViewer();
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
      if (m.step === 'repro' && m.repro_files === undefined) m.repro_files = '?';
      const failed = !isTest && (m.ok === 'false' || e.label.endsWith('_failed'));
      const roundTxt = m.round && m.round !== '0' ? `${m.round}회차` : '';
      const hst = (d.state.review_history || []).find(x => x.file === e.name);
      items.push(h('li', { class: failed ? 'failed' : null }, h('button', {
        type: 'button', class: this.selected === e.name ? 'active' : null,
        onclick: () => { this.selected = e.name; this.autoLive = false; this.renderTimeline(); this.renderViewer(); },
      },
        h('span', { class: 'seq' }, String(e.seq).padStart(2, '0')),
        h('span', { class: 'what' }, agentTag(m.agent, m.role), withTip(h('span', { class: 'ellipsis' }, STEP[m.step] || m.step), `step.${m.step}`)),
        h('span', { class: 'dur' }, m.duration_sec ? fmtDur(m.duration_sec) : ''),
        h('span', { class: 'sub' },
          roundTxt ? h('span', null, roundTxt) : null,
          failed ? h('span', null, m.rate_limited === 'true' ? '한도 도달' : m.timed_out === 'true' ? '시간 초과' : `실패 (exit ${m.exit_code})`) : null,
          m.attempt && m.attempt !== '1' ? h('span', null, `재시도 ${Number(m.attempt) - 1}`) : null,
          m.tokens_out ? h('span', { class: 'tok', 'data-tip': `AI 가 쓴 양(출력 토큰). 읽은 양(입력)은 ${fmtTok(m.tokens_in || 0)} 토큰입니다.` }, `출력 ${fmtTok(m.tokens_out)}`) : null,
          isTest ? testTag(m.test_status) : m.step === 'repro' ? reproTag(m.repro_status) : hst ? decisionTag(hst) : verdictTag(e.verdict)))));
    }
    const cc = d.current_call;
    if (d.live) {
      const elapsed = cc ? cc.elapsed_sec + Math.round((Date.now() - this.loadedAt) / 1000) : null;
      items.push(h('li', { class: 'pending', 'data-tip': TIPS['step.pending'] }, h('button', {
        type: 'button', class: this.selected === LIVE ? 'active' : null,
        onclick: () => { this.selected = LIVE; this.autoLive = false; this.renderTimeline(); this.renderViewer(); } },
        h('span', { class: 'seq' }, h('span', { class: 'spinner' })),
        h('span', { class: 'what' }, cc ? agentTag(cc.agent) : null, h('span', null, cc ? `${STEP[cc.step] || cc.step} 진행 중` : '준비 중')),
        h('span', { class: 'dur' }, elapsed !== null ? fmtDur(elapsed) : ''),
        cc && cc.retry ? h('span', { class: 'sub' }, `재시도 ${cc.retry}`) : null)));
    }
    if (!items.length) items.push(h('li', { class: 'empty-state small' }, '아직 기록이 없습니다.'));
    this.timelineEl.replaceChildren(...items);
  }
  async renderLive() {
    let a;
    try { a = await api('/api/activity', { query: this.q(), machine: this.m }); }
    catch (e) { this.viewerEl.replaceChildren(errorBox(e)); return; }
    if (this.selected !== LIVE) return;
    const c = a.call;
    const KIND = { read: '읽기', edit: '수정', command: '명령', search: '검색', message: '메시지', tool: '도구' };
    const pad = n => String(n).padStart(2, '0');
    const fmtT = ts => { const d = ts ? new Date(ts) : null; return d && !isNaN(d) ? `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` : ''; };
    const root = String(this.data.project || this.r.project).replace(/\/+$/, '') + '/';
    const rel = t => String(t).split(root).join('');   // 작업 폴더 경로는 짧게
    const body = !c ? h('div', { class: 'empty-state' }, '다음 단계를 준비하고 있습니다.')
      : !a.events.length ? h('div', { class: 'empty-state' }, `${c.agent} 가 시작했습니다. 첫 동작을 기다리는 중…`)
      : h('ol', { class: 'activity' }, a.events.map(ev => h('li', { class: `act act-${ev.kind}` },
          h('span', { class: 'act-time' }, fmtT(ev.ts)),
          h('span', { class: `act-kind k-${ev.kind}` }, KIND[ev.kind] || ev.kind),
          h('span', { class: ev.kind === 'message' ? 'act-text' : 'act-text mono' }, rel(ev.text),
            ev.detail ? h('span', { class: 'act-detail' }, ` — ${ev.detail}`) : null))));
    const atBottom = this.viewerEl.scrollTop + this.viewerEl.clientHeight >= this.viewerEl.scrollHeight - 30;
    this.viewerEl.replaceChildren(
      h('div', { class: 'viewer-head' }, h('span', { class: 'spinner' }), c ? agentTag(c.agent) : null,
        h('b', null, c ? `${STEP[c.step] || c.step} 진행 중` : '준비 중'), help('live_view'),
        h('span', { class: 'spacer' }), c ? h('span', { class: 'muted small' }, `${c.started} 시작 · ${fmtDur(c.elapsed_sec)}`) : null),
      h('div', { class: 'viewer-body' }, body));
    const list = this.viewerEl.querySelector('.activity');
    if (list && (atBottom || this.firstLive !== false)) list.lastElementChild && list.lastElementChild.scrollIntoView({ block: 'nearest' });
    this.firstLive = false;
  }
  async renderViewer() {
    const name = this.selected;
    if (name === LIVE) return this.renderLive();
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
        agentTag(m.agent, m.role), h('b', null, STEP[m.step] || m.step || ''),
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
  if (!(await askConfirm('실행을 중지할까요?\n진행 중인 호출은 버리고, 나중에 이어하기로 그 단계부터 다시 할 수 있습니다.', { ok: '중지', danger: true }))) return;
  try {
    const r = await api('/api/actions/stop', { method: 'POST', body: { project }, machine });
    toast(`중지 신호를 보냈습니다 (pid ${r.stopped}).`);
    if (currentView) schedule(currentView, 800);
  } catch (e) { toast(e.message, true); }
}
// =================================================================== 공통: 머신 탭
// =================================================================== bench (DESIGN.md 28.3)
class BenchView {
  constructor(main, r) { this.main = main; this.r = r; }
  interval() { return 0; }
  showError(e) { this.main.replaceChildren(h('div', { class: 'page' }, h('h1', null, '벤치마크'), errorBox(e))); }
  async load() {
    const m = this.r.machine || LOCAL;
    if (this.r.dir) {
      const d = await api('/api/bench/result', { query: { dir: this.r.dir }, machine: m });
      return this.renderResult(d, m);
    }
    const d = await api('/api/bench', { machine: m });
    this.renderList(d.results, m);
  }
  renderList(results, m) {
    const href = r => `#/bench?dir=${enc(r.dir)}${m !== LOCAL ? `&m=${enc(m)}` : ''}`;
    const rows = results.map(r => h('tr', null,
      h('td', null, h('a', { href: href(r) }, r.name), r.mock ? h('span', { class: 'badge plain' }, 'mock') : null),
      h('td', null, r.suite || '-'), h('td', null, (r.workflows || []).join(', ')),
      h('td', { class: 'num' }, r.runs), h('td', { class: 'num' }, `${r.approved}/${r.runs}`),
      h('td', { class: 'num' }, `${r.all_passed}/${r.runs}`),
      h('td', { class: 'mono small faint' }, r.dir)));
    this.main.replaceChildren(h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', null, h('h1', null, '벤치마크'),
        h('div', { class: 'muted' }, '같은 과제 묶음을 워크플로별로 돌리고 숨은 수용 테스트로 채점한 결과입니다. `duet bench run` 으로 만듭니다.'))),
      machineTabs(m, id => `#/bench${id !== LOCAL ? `?m=${enc(id)}` : ''}`),
      results.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'plain' },
        h('thead', null, h('tr', null, ['결과', '묶음', '워크플로', '실행', '승인', '숨은 테스트 전부 통과', '폴더'].map(t => h('th', null, t)))),
        h('tbody', null, rows)))
        : h('div', { class: 'card empty-state small' }, '아직 벤치마크 결과가 없습니다. 예: duet bench run --suite hard --workflow classic --workflow lean --yes')));
  }
  renderResult(d, m) {
    const meta = d.meta || {};
    const stats = (d.stats || []).map(s => h('tr', null,
      h('td', null, h('b', null, s.workflow)), h('td', { class: 'num' }, `${s.approved}/${s.runs}`),
      h('td', { class: 'num' }, s.arbiter || '-'),
      h('td', { class: 'num' }, `${s.hidden_rate.toFixed(0)}%`), h('td', { class: 'num' }, `${s.all_passed}/${s.graded}`),
      h('td', { class: 'num' + (s.missed ? ' bad' : '') }, s.missed),
      h('td', { class: 'num' }, s.rounds.toFixed(1)), h('td', { class: 'num' }, fmtDur(s.seconds)),
      h('td', { class: 'num' }, s.calls.toFixed(1)),
      h('td', { class: 'num' }, `${fmtTok(s.input.claude)} / ${fmtTok(s.input.codex)}`), h('td', { class: 'num' }, fmtTok(s.output))));
    const rows = (d.rows || []).map(r => {
      const hd = r.hidden;
      const run = r.run_dir ? baseName(r.run_dir) : null;
      const link = r.has_runs && run ? hrefRun(m, r.workdir, run) : null;
      return h('tr', null,
        h('td', null, link ? h('a', { href: link }, r.task) : r.task), h('td', null, r.workflow), h('td', { class: 'num' }, r.rep),
        h('td', null, h('span', { class: `badge s-${r.approved ? 'done_approved' : r.status === 'unapproved' ? 'done_unapproved' : 'failed'}` },
          ({ approved: '승인', unapproved: '미승인', stopped: '중단', failed: '실패', error: '오류', design_only: '설계만' }[r.status] || r.status)
          + (r.arbiter === 'arbiter' ? ' (중재)' : ''))),
        h('td', { class: 'num' }, r.rounds || 0),
        h('td', { class: 'num' + (hd && !hd.all_passed ? ' bad' : '') }, hd ? `${hd.passed}/${hd.total}` : '-'),
        h('td', { class: 'num' }, fmtDur((r.seconds || 0) - (r.limit_wait_sec || 0))),
        h('td', { class: 'num' }, r.calls || 0));
    });
    this.main.replaceChildren(h('div', { class: 'page' },
      h('div', { class: 'crumbs' }, h('a', { href: '#/bench' + (m !== LOCAL ? `?m=${enc(m)}` : '') }, '벤치마크'), h('span', { class: 'sep' }, '/'), h('span', null, baseName(d.dir))),
      h('h1', null, baseName(d.dir)),
      h('div', { class: 'chips' },
        h('span', { class: 'chip' }, '묶음 ', h('b', null, meta.suite || '?')),
        h('span', { class: 'chip' }, `과제 ${(meta.tasks || []).length}개 × 워크플로 ${(meta.workflows || []).length}개 × ${meta.repeat || 1}회`),
        meta.mock ? h('span', { class: 'badge plain' }, 'mock') : null,
        meta.started ? h('span', { class: 'chip' }, fmtWhen(meta.started)) : null),
      h('h2', null, '워크플로별'),
      h('div', { class: 'card table-wrap' }, h('table', { class: 'plain' },
        h('thead', null, h('tr', null, ['워크플로', '승인', '중재 승인', '숨은 테스트', '전부 통과', '승인했는데 실패', '평균 라운드', '평균 시간', '평균 호출', '입력 토큰 (Claude / Codex)', '출력 토큰'].map(t => h('th', null, t)))),
        h('tbody', null, stats))),
      h('h2', null, '실행별'),
      h('div', { class: 'card table-wrap' }, h('table', { class: 'plain' },
        h('thead', null, h('tr', null, ['과제', '워크플로', '#', '결과', '라운드', '숨은 테스트', '시간', '호출'].map(t => h('th', null, t)))),
        h('tbody', null, rows))),
      h('p', { class: 'muted small' }, '숨은 테스트: 에이전트가 보지 못한 수용 테스트. 승인했는데 실패: 리뷰가 놓친 결함. 시간에서는 한도 대기 시간을 뺐습니다.')));
  }
}

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
      withTip(h('button', { class: 'btn', type: 'button', onclick: () => this.reload() }, '다시 점검'), 'recheck'));
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
    rows.push([['SSH 연결', help('remote.ssh')], info.reachable ? 'ok' : 'error', info.reachable ? (info.uname || '연결됨') : info.error,
      info.hint ? h('span', { class: 'mono small' }, info.hint) : null]);
    if (info.reachable) {
      rows.push([['Python 3.11+', help('remote.python')], info.python ? 'ok' : 'missing', info.python || '찾지 못했습니다. uv 를 설치한 뒤 Python 3.12 를 설치하세요.',
        info.python ? null : [this.actBtn('install_uv'), this.actBtn('install_python')]]);
      const dep = info.deployed ? (info.up_to_date ? 'ok' : 'warn') : 'missing';
      rows.push([['duet 배포', help('remote.duet')], dep, info.deployed ? (info.up_to_date ? `최신 (${info.remote_hash})` : `업데이트 필요 (원격 ${info.remote_hash} · 이 머신 ${info.local_hash})`) : '아직 배포하지 않았습니다.',
        info.python ? withTip(h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: ev => this.deploy(ev) }, info.deployed ? '업데이트' : '배포'), 'deploy') : null]);
    }
    return h('div', { class: 'card table-wrap' }, h('table', { class: 'checks-table' },
      h('thead', null, h('tr', null, h('th', null, `원격 머신: ${machineName(m)}`), h('th', null, '상태'), h('th', null, '내용'), h('th', null, ''))),
      h('tbody', null, rows.map(([name, st, detail, acts]) => h('tr', null,
        h('td', null, h('b', null, name)), h('td', null, h('span', { class: `badge s-${st}` }, CHECK_STATUS[st] || st)),
        h('td', null, detail), h('td', null, h('div', { class: 'acts' }, acts)))))));
  }
  checksCard(d) {
    const rows = d.checks.map(c => h('tr', null,
      h('td', null, h('b', null, c.name), help(`tool.${c.id}`), c.path ? h('div', { class: 'ver' }, c.path) : null),
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
  actCommand(a) {
    // 이 머신이면 이 OS 의 명령(Windows 는 PowerShell), 원격이면 POSIX 셸 명령 (DESIGN.md 27.5)
    const local = !this.r.machine || this.r.machine === LOCAL;
    return local ? (a.local_available === false ? '(이 OS 에서는 직접 설치)' : a.local_command) : a.command;
  }
  actBtn(id, cls = '') {
    const a = (app.actions || {})[id];
    const label = a ? a.title : id;
    const tip = a ? [a.note, `실행 명령: ${this.actCommand(a)}`].filter(Boolean).join(' · ') : null;
    return h('button', { class: `btn btn-sm ${cls}`, type: 'button', 'data-tip': tip, onclick: () => this.runAction(id) }, label);
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
    if (id.startsWith('install') && !(await askConfirm(`${a.title || id}\n\n다음 명령을 실행합니다:\n${this.actCommand(a) || ''}`, { ok: '실행' }))) return;
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
    const input = h('input', { type: 'text', placeholder: '코드나 답을 입력하고 Enter', autocomplete: 'off', spellcheck: 'false', 'data-tip': TIPS.term_input });
    const secret = h('input', { type: 'checkbox', onchange: () => { input.type = secret.checked ? 'password' : 'text'; } });
    const send = async () => {
      if (!input.value) return;
      try { await api('/api/term/input', { method: 'POST', body: { id: job.id, text: input.value } }); input.value = ''; }
      catch (e) { toast(e.message, true); }
    };
    input.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); send(); } });
    this.statusEl = h('span', { class: 'badge s-running live' }, '실행 중');
    this.inputRow = h('div', { class: 'term-input' }, input, h('label', null, secret, '비밀번호(숨김)', help('term_secret')),
      h('button', { class: 'btn btn-sm', type: 'button', onclick: send }, '보내기'),
      h('button', { class: 'btn btn-sm btn-danger', type: 'button', 'data-tip': TIPS.term_kill, onclick: () => api('/api/term/kill', { method: 'POST', body: { id: job.id } }).catch(e => toast(e.message, true)) }, '중지'));
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
      h('div', { class: 'row' }, h('h2', null, 'Codex 구독 한도', help('codex_limit')), cl && cl.plan_type ? h('span', { class: 'chip' }, cl.plan_type) : null,
        h('span', { class: 'spacer' }), cl && cl.as_of ? h('span', { class: 'muted small' }, `기준 ${fmtWhen(cl.as_of)}`) : null),
      cl ? [cl.primary ? meter('주 한도', cl.primary) : null, cl.secondary ? meter('보조 한도', cl.secondary) : null,
        cl.reached ? h('div', { class: 'alert alert-bad' }, h('b', null, '한도 도달'), h('span', null, cl.reached)) : null]
        : h('p', { class: 'muted' }, '최근 Codex 세션 기록이 없습니다. Codex 를 한 번 쓰면 보입니다.'),
      h('p', { class: 'desc' }, 'Codex 가 남긴 마지막 세션 기록 기준입니다(duet 밖에서 쓴 것 포함).'));
    const cw = u.claude_local.windows;
    const ck = u.claude_limits;
    const cwin = ck && ck.limits ? ck.limits : null;
    const claudeCard = h('div', { class: 'card section-card' },
      h('div', { class: 'row' }, h('h2', null, 'Claude Code 사용량', help('claude_tokens')), h('span', { class: 'spacer' }),
        ck && ck.as_of ? h('span', { class: 'muted small' }, `한도 기준 ${fmtWhen(ck.as_of)}`) : null),
      cwin ? [cwin.five_hour ? meter('5시간 한도', cwin.five_hour) : null, cwin.seven_day ? meter('7일 한도', cwin.seven_day) : null,
        cwin.status === 'rejected' ? h('div', { class: 'alert alert-bad' }, h('b', null, '한도 도달'), h('span', null, cwin.type || '')) : null] : null,
      h('div', { class: 'stat-grid' }, Object.entries(cw).map(([name, w]) => h('div', { class: 'card stat' },
        h('span', { class: 'k' }, `최근 ${name}`), h('span', { class: 'v' }, `출력 ${fmtTok(w.output_tokens)}`),
        h('span', { class: 's' }, `입력 ${fmtTok(w.input_tokens)} · 응답 ${w.messages}개`)))),
      Object.keys(u.claude_local.output_by_model_7d || {}).length ? h('table', { class: 'plain' },
        h('thead', null, h('tr', null, h('th', null, '모델 (7일)'), h('th', { class: 'num' }, '출력 토큰'))),
        h('tbody', null, Object.entries(u.claude_local.output_by_model_7d).sort((a, b) => b[1] - a[1]).map(([m, n]) =>
          h('tr', null, h('td', null, m), h('td', { class: 'num' }, fmtTok(n)))))) : null,
      h('p', { class: 'desc' }, cwin ? '한도(%)는 duet 가 Claude 를 마지막으로 부를 때 받은 값입니다. 토큰은 이 머신의 Claude Code 기록(duet 밖 사용 포함)을 합산했습니다.'
        : '한도(%)는 duet 가 Claude 를 한 번 부르면 보입니다. 토큰은 이 머신의 Claude Code 기록에서 합산했습니다.'));
    const du = u.duet;
    const agentRows = Object.entries(du.by_agent).map(([a, t]) => h('tr', null, h('td', null, agentTag(a)),
      h('td', { class: 'num' }, t.calls || 0), h('td', { class: 'num' }, fmtTok(t.input_tokens)), h('td', { class: 'num' }, fmtTok(t.output_tokens)),
      h('td', { class: 'num' }, fmtUsd(t.cost_usd) || '-')));
    const dayRows = Object.entries(du.by_day).map(([day, agents]) => h('tr', null, h('td', null, day),
      ['claude', 'codex'].map(a => h('td', { class: 'num' }, agents[a] ? `${fmtTok(agents[a].output_tokens)} (${agents[a].calls}회)` : '-'))));
    const projRows = du.projects.map(p => h('tr', null, h('td', null, h('a', { href: hrefProject(this.r.machine, p.path) }, p.name)),
      ['claude', 'codex'].map(a => h('td', { class: 'num' }, p.by_agent[a] ? `${fmtTok(p.by_agent[a].output_tokens)} (${p.by_agent[a].calls}회)` : '-'))));
    const duetCard = h('div', { class: 'card section-card' },
      h('h2', null, 'duet 실행이 쓴 양', help('duet_usage')),
      agentRows.length ? [
        h('table', { class: 'plain' }, h('thead', null, h('tr', null, h('th', null, '에이전트'), h('th', { class: 'num' }, '호출'),
          h('th', { class: 'num' }, '입력 토큰', help('tokens')), h('th', { class: 'num' }, '출력 토큰'), h('th', { class: 'num' }, 'API 환산', help('usage_cost')))), h('tbody', null, agentRows)),
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
  const sel = h('select', { name }, h('option', { value: '' }, '단계별 기본'), levels.map(l => h('option', { value: l }, l)));
  if (value && !levels.includes(value)) sel.append(h('option', { value }, value));
  sel.value = value || '';
  return sel;
}
function modelDatalists(sugg) {
  $('#claude-models').replaceChildren(...sugg.claude.models.map(m => h('option', { value: m.id }, m.label)));
  $('#codex-models').replaceChildren(...sugg.codex.models.map(m => h('option', { value: m.id }, m.label)));
}

// =================================================================== 설정 항목 정의 (DESIGN.md 28.4)
function fmtOptValue(o, v) {
  if (v === true) return '켬';
  if (v === false) return '끔';
  return v === null || v === undefined || v === '' ? '없음' : String(v);
}
function optionInput(o, value) {
  // 비워 두면(기본값) 저장된 값·duet.toml·내장 기본값을 따른다
  const def = `기본값 (${fmtOptValue(o, o.effective)})`;
  let el;
  if (o.kind === 'bool') {
    el = h('select', null, h('option', { value: '' }, def), h('option', { value: 'true' }, '켬'), h('option', { value: 'false' }, '끔'));
    el.value = value === true ? 'true' : value === false ? 'false' : '';
  } else if (o.kind === 'choice') {
    el = h('select', null, h('option', { value: '' }, def), (o.choices || []).map(c => h('option', { value: c }, c)));
    el.value = value ?? '';
  } else {
    el = h('input', { type: o.kind === 'int' ? 'number' : 'text', min: o.min ?? null, max: o.max ?? null,
      value: value ?? '', placeholder: def, spellcheck: 'false', autocomplete: 'off' });
  }
  el.dataset.option = o.key;
  return el;
}
function optionFields(options, values, filter) {
  const groups = {};
  for (const o of options.filter(filter)) (groups[o.group_label] = groups[o.group_label] || []).push(o);
  return Object.entries(groups).map(([label, list]) => h('div', { class: 'opt-group' },
    h('h3', null, label),
    h('div', { class: 'form-grid' }, list.map(o => h('label', { class: 'field', 'data-tip': o.help },
      h('span', { class: 'field-label' }, o.label), optionInput(o, values[o.key]))))));
}
function collectOptions(root, keepEmpty) {
  const out = {};
  for (const el of root.querySelectorAll('[data-option]')) {
    const v = el.value.trim();
    if (v || keepEmpty) out[el.dataset.option] = v;
  }
  return out;
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
      h('h2', null, '작업 폴더 위치', help('roots')),
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
      review_diff: h('input', { type: 'checkbox', checked: ((d.review_diff ?? eff.review_diff) || 'incremental') === 'incremental' ? true : null }),
      repro_tests: h('input', { type: 'checkbox', checked: (d.repro_tests ?? eff.repro_tests ?? true) ? true : null }),
      claude_model: h('input', { type: 'text', list: 'claude-models', value: (d.claude || {}).model || '', placeholder: 'CLI 기본값', spellcheck: 'false' }),
      codex_model: h('input', { type: 'text', list: 'codex-models', value: (d.codex || {}).model || '', placeholder: 'CLI 기본값', spellcheck: 'false' }),
    };
    f.claude_effort = effortSelect('claude_effort', 'claude', (d.claude || {}).effort, sugg);
    f.codex_effort = effortSelect('codex_effort', 'codex', (d.codex || {}).effort, sugg, (d.codex || {}).model);
    f.codex_model.addEventListener('change', () => {
      const ne = effortSelect('codex_effort', 'codex', f.codex_effort.value, sugg, f.codex_model.value);
      f.codex_effort.replaceWith(ne); f.codex_effort = ne;
    });
    const field = (label, el, tipKey) => h('label', { class: 'field' }, h('span', { class: 'field-label' }, label, tipKey ? help(tipKey) : null), el);
    const defaultsCard = h('div', { class: 'card section-card' },
      h('h2', null, '기본 실행 설정'),
      h('p', { class: 'desc' }, 'CLI 와 UI 의 모든 실행에 적용됩니다. 작업 폴더의 duet.toml 이나 실행할 때 고른 값이 더 우선합니다.'),
      h('div', { class: 'form-grid' },
        field('구현', f.implementer, 'implementer'), field('리뷰', f.reviewer, 'reviewer'), field('설계 종합', f.synth, 'synth'),
        field('토론 라운드', f.debate_rounds, 'debate_rounds'), field('리뷰 최대', f.max_review, 'max_review')),
      h('div', { class: 'form-grid' },
        field('Claude 모델', f.claude_model, 'claude_model'), field('Claude 추론', f.claude_effort, 'effort'),
        field('Codex 모델', f.codex_model, 'codex_model'), field('Codex 추론', f.codex_effort, 'effort')),
      h('h3', null, '리뷰·테스트'),
      h('p', { class: 'desc' }, '반려 기준: 이 심각도 이상의 지적이 남아 있으면 반려합니다(P1 핵심 동작·보안, P2 설계 위반·일반 입력 오류, P3 드문 경계 사례). 수렴 판단: 막는 지적 수가 N 라운드 연속 줄지 않으면 멈춥니다(0=끔).'),
      h('div', { class: 'form-grid' },
        field('테스트 명령', f.test_command, 'test_command'), field('반려 기준', f.block_severity, 'block_severity'),
        field('수렴 판단 라운드', f.stall_rounds, 'stall_rounds'),
        h('label', { class: 'checkline' }, f.require_tests_pass, '테스트 실패 시 승인 안 함', help('require_tests')),
        h('label', { class: 'checkline' }, f.review_diff, '2번째 리뷰부터 바뀐 부분만', help('review_diff')),
        h('label', { class: 'checkline' }, f.repro_tests, '리뷰어의 재현 테스트 받기', help('repro_tests'))),
      h('div', { class: 'actions' }, h('button', { class: 'btn btn-primary', type: 'button', onclick: () => this.save({ defaults: {
        implementer: f.implementer.value, reviewer: f.reviewer.value, synth: f.synth.value,
        debate_rounds: f.debate_rounds.value, max_review: f.max_review.value,
        claude: { model: f.claude_model.value, effort: f.claude_effort.value },
        codex: { model: f.codex_model.value, effort: f.codex_effort.value },
        test_command: f.test_command.value, block_severity: f.block_severity.value,
        stall_rounds: f.stall_rounds.value, require_tests_pass: f.require_tests_pass.checked,
        review_diff: f.review_diff.checked ? 'incremental' : 'full', repro_tests: f.repro_tests.checked,
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
      h('div', { class: 'form-grid' }, field('id (영문 소문자)', mf.id, 'machine.id'), field('이름', mf.name, 'machine.name'),
        field('SSH 대상', mf.ssh, 'machine.ssh'), field('포트', mf.port, 'machine.port'), field('작업 폴더 위치', mf.workspace_root, 'machine.root')),
      h('div', { class: 'actions' },
        h('button', { class: 'btn btn-primary', type: 'button', onclick: () => this.saveMachine(mf) }, ed.id ? '수정 저장' : '머신 추가'),
        ed.id ? h('button', { class: 'btn', type: 'button', onclick: () => { this.editing = null; this.render(v); } }, '취소') : null));

    // ---------------- 고급 설정 (설정 항목 정의에서 만든다)
    const advBody = h('div', null, optionFields(v.options || [], d, () => true));
    const advancedCard = h('div', { class: 'card section-card' },
      h('h2', null, '고급 설정'),
      h('p', { class: 'desc' }, '리뷰 관문·중재자·중복 확인·안전장치·한도 대기 같은 설정입니다. 비워 두면 기본값을 씁니다. 항목에 마우스를 올리면 설명이 나옵니다.'),
      advBody,
      h('div', { class: 'actions' }, h('button', { class: 'btn btn-primary', type: 'button', onclick: () => this.save({ options: collectOptions(advBody, true) }) }, '저장')));

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
      h('div', { class: 'actions' }, withTip(h('button', { class: 'btn', type: 'button', onclick: restartServer }, 'UI 다시 시작'), 'restart')));
    this.main.replaceChildren(h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', null, h('h1', null, '설정'), h('div', { class: 'muted' }, '~/.duet/settings.json 에 저장됩니다.'))),
      v.error ? errorBox({ message: v.error }) : null, rootsCard, defaultsCard, advancedCard, machinesCard, serverCard));
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
    if (!(await askConfirm(`${m.name || m.id} 머신을 목록에서 지울까요? 원격의 파일은 그대로 둡니다.`, { ok: '지우기', danger: true }))) return;
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
let dlgWorkflows = [];
function workflowPreview() {
  const f = form.elements;
  const w = dlgWorkflows.find(x => x.id === f.workflow.value);
  const classic = !w || w.id === 'classic';
  $('#classic-roles').hidden = !classic;
  const el = $('#workflow-preview');
  if (!w) { el.textContent = ''; scheduleWorkflowDiagram(); return; }
  if (w.source === 'error') { el.textContent = `오류: ${w.error}`; scheduleWorkflowDiagram(); return; }
  el.textContent = w.description || '';
  scheduleWorkflowDiagram();
}
async function fillWorkflows(machine, project, value) {
  const f = form.elements;
  let data = { workflows: [], default: 'classic' };
  try { data = await api('/api/workflows', { query: { project }, machine }); } catch (e) { /* 예전 원격 duet: classic 만 */ }
  dlgWorkflows = data.workflows && data.workflows.length ? data.workflows : [{ id: 'classic', name: 'classic', summary: '', roles: [], source: 'config', source_label: '기본' }];
  f.workflow.replaceChildren(...dlgWorkflows.map(w => h('option', { value: w.id, disabled: w.source === 'error' },
    `${w.id}${w.source_label ? ` · ${w.source_label}` : ''}${w.source === 'error' ? ' (오류)' : ''}`)));
  const want = value || data.default || 'classic';
  f.workflow.value = dlgWorkflows.some(w => w.id === want && w.source !== 'error') ? want : 'classic';
  workflowPreview();
}
// =================================================================== 워크플로 순서도 (새 실행 창)
// 고른 워크플로의 단계를 순서대로 그리고, 단계마다 누가(CLI·역할) 어떤 모델·추론 강도로 하는지 보인다.
// 창에서 역할·모델·강도·고급 설정을 바꾸면 바로 다시 그린다. 강도 계산은 config.effort_for·Role.agent_config 와 같은
// 규칙이다: 설정(+duet.toml) → 이 창에서 고른 값(강도만 고르면 단계별 강도는 비움, 18.1) → 워크플로 역할.
function dlgOption(key) {
  const o = ((app.settings && app.settings.options) || []).find(x => x.key === key);
  const el = document.querySelector(`#run-advanced-body [data-option="${key}"]`);
  const raw = el ? el.value.trim() : '';
  if (!raw) return o ? o.effective : undefined;
  if (o && o.kind === 'bool') return raw === 'true';
  if (o && o.kind === 'int') return Number(raw);
  return raw;
}
function agentSetting(agent) {
  const f = form.elements;
  const base = ((dlgState.eff || {})[agent]) || {};
  let model = base.model || '';
  let effort = base.effort_base ?? base.effort ?? '';
  let step = { ...(base.step_effort || {}) };
  const m = f[`${agent}_model`] ? f[`${agent}_model`].value.trim() : '';
  const e = f[`${agent}_effort`] ? f[`${agent}_effort`].value : '';
  if (m) model = m;
  if (e) { effort = e; step = {}; }
  return { model, effort, step };
}
function roleSetting(role) {
  const s = agentSetting(role.agent);
  let { model, effort, step } = s;
  if (role.model) model = role.model;
  if (role.effort) { effort = role.effort; step = { ...(role.step_effort || {}) }; }
  else if (role.step_effort) step = { ...role.step_effort };
  return { agent: role.agent, model, effort, step };
}
function workflowModel() {
  const f = form.elements;
  const w = dlgWorkflows.find(x => x.id === f.workflow.value);
  if (!w || w.source === 'error') return null;
  if (w.id === 'classic' || w.source === 'config') {
    const rev = f.reviewer.value;
    return {
      roles: { claude: { name: 'claude', agent: 'claude' }, codex: { name: 'codex', agent: 'codex' } },
      steps: [{ kind: 'debate', proposers: ['claude', 'codex'], synth: f.synth.value || rev },
        { kind: 'build', implementer: f.implementer.value, reviewers: [rev] }],
      classic: true,
    };
  }
  return { roles: Object.fromEntries((w.roles || []).map(r => [r.name, r])), steps: w.steps || [], classic: false };
}
const EFFORT_LEVEL = { minimal: 'low', low: 'low', medium: 'med', high: 'high', xhigh: 'max', max: 'max' };
function effortPill(v, label) {
  return h('span', { class: `wf-eff e-${EFFORT_LEVEL[v] || 'def'}`, title: '추론 강도' }, label ? h('small', null, label) : null, v || '기본');
}
function wfEffort(pairs) {
  // 단계별로 같으면 한 개, 다르면(예: 리뷰 1회차 high · 2회차부터 medium) 단계 이름을 붙여 여러 개
  const vals = pairs.map(([, v]) => v || '');
  if (vals.every(v => v === vals[0])) return [effortPill(vals[0])];
  return pairs.map(([label, v], i) => effortPill(v || '', i === 0 ? null : label));
}
function wfEffortText(pairs) {
  const vals = pairs.map(([, v]) => v || '기본');
  return vals.every(v => v === vals[0]) ? vals[0] : pairs.map(([label, v]) => `${label} ${v || '기본'}`).join(' · ');
}
function wfCard(label, agent, roleName, model, pairs, opts = {}) {
  const base = agent === 'claude' || agent === 'codex' ? agent : 'x';
  const effs = wfEffort(pairs);
  const many = effs.length > 1;          // 단계별로 다르면 칸이 좁아지지 않게 아래 줄에
  return h('div', { class: `wf-node wf-${base}${opts.small ? ' small' : ''}`, 'data-key': opts.key || `${label}:${roleName}` },
    h('div', { class: 'wf-node-head' },
      h('span', { class: `wf-avatar wf-avatar-${base}` }, agentLogo(agent, 18)),
      h('div', { class: 'wf-who' }, h('span', { class: 'wf-step' }, label),
        h('span', { class: 'wf-name' }, roleName && roleName !== agent ? `${roleName} · ${agent}` : agent)),
      many ? null : h('div', { class: 'wf-effs' }, effs)),
    h('div', { class: 'wf-model' }, model || '기본 모델'),
    many ? h('div', { class: 'wf-effs wide' }, effs) : null,
    opts.note ? h('div', { class: 'wf-note' }, opts.note) : null);
}
function renderWorkflowDiagram() {
  const box = $('#workflow-diagram');
  if (!box) return;
  const m = workflowModel();
  if (!m) { box.replaceChildren(); box.hidden = true; return; }
  box.hidden = false;
  const f = form.elements;
  const R = name => m.roles[name] || { name, agent: name };
  const sig = {};
  const uses = { claude: [], codex: [] };                 // 에이전트 카드에 '이 워크플로에서 하는 일'
  const node = (label, roleName, keys, opts = {}) => {
    const r = R(roleName);
    const rs = roleSetting(r);
    const pairs = keys.map(([k, lbl]) => [lbl, rs.step[k] || rs.effort || '']);
    const key = `${label}:${roleName}`;
    sig[key] = `${r.agent}|${rs.model}|${wfEffortText(pairs)}`;
    if (uses[r.agent] && !uses[r.agent].includes(label)) uses[r.agent].push(label);
    return wfCard(label, r.agent, r.name, rs.model, pairs, { ...opts, key });
  };
  const arrow = (text) => h('div', { class: 'wf-arrow' }, text ? h('span', null, text) : null);
  const stages = [];
  const stage = (title, chips, ...body) => stages.push(h('section', { class: 'wf-stage', 'data-stage': title },
    h('span', { class: 'wf-num' }, String(stages.length + 1)),
    h('div', { class: 'wf-title' }, title, ...(chips || []).filter(Boolean).map(c => h('span', { class: 'wf-chip' }, c))),
    ...body));
  const rounds = n => (n === undefined || n === null || n === '') ? Number(f.debate_rounds.value || 0) : Number(n);
  let synthOfDebate = null;
  for (const st of m.steps) {
    if (st.kind === 'explore') {
      stage('사전 조사', ['기존 코드를 먼저 읽음'], h('div', { class: 'wf-row' }, node('조사', st.role, [['explore', '']])));
    } else if (st.kind === 'debate') {
      const props = st.proposers || [];
      const out = st.output === 'change' ? 'docs/changes/<실행>.md' : 'DESIGN.md';
      if (props.length <= 1) {
        stage('설계', ['혼자 설계, 토론 없음'],
          h('div', { class: 'wf-row' }, node('설계안', props[0], [['propose', '']])), arrow(), h('div', { class: 'wf-out' }, out));
      } else {
        const n = rounds(st.rounds);
        synthOfDebate = st.synth || null;
        stage('설계 토론', [n ? `비판 ${n}라운드` : '비판 없음'],
          h('div', { class: 'wf-row' }, props.map(p => node('설계안', p, n ? [['propose', '설계안'], ['critique', '비판']] : [['propose', '']]))),
          arrow(n ? `서로의 안을 비판하고 고침 ×${n}` : '바로 종합'),
          h('div', { class: 'wf-row' }, node('종합', st.synth, [['synthesize', '']], { note: '쟁점마다 결정' })),
          arrow(), h('div', { class: 'wf-out' }, out));
      }
    } else if (st.kind === 'build') {
      const maxR = st.max_review || Number(f.max_review.value || 3);
      const reviewers = st.reviewers || [];
      const arbiterOn = dlgOption('arbiter') !== false;
      const gatesOn = dlgOption('review_gates') !== false && dlgOption('review_json') !== false;
      const dedupOn = dlgOption('dedup') !== false && gatesOn;
      const arbiterRole = st.arbiter || (m.classic ? synthOfDebate : (synthOfDebate && synthOfDebate !== st.implementer ? synthOfDebate : reviewers[0]));
      const implNode = node('구현', st.implementer, [['implement', '처음'], ['fix', '수정']]);
      const reviewNodes = reviewers.map(rv => node('리뷰', rv, [['review', '1회차'], ['rereview', '2회차부터']]));
      const extras = [];
      if (arbiterOn && arbiterRole && gatesOn) extras.push(node('중재', arbiterRole, [['arbitrate', '']], { small: true, note: '수렴 실패·상한일 때 한 번' }));
      if (dedupOn) {
        const agent = dlgOption('dedup_agent') || 'claude';
        const model = dlgOption('dedup_model') || '';
        const effort = dlgOption('dedup_effort') || '';
        sig['중복 확인'] = `${agent}|${model}|${effort}`;
        extras.push(wfCard('중복 확인', agent, agent, model, [['', effort]],
          { small: true, key: '중복 확인', note: '해결·기각된 지적의 반복 확인 (작은 모델)' }));
      }
      const guards = [gatesOn ? '판정 관문' : null, gatesOn && dlgOption('spec_gate') !== false ? '요구 근거' : null,
        dlgOption('test_guard') !== false ? '테스트 변조 감지' : null, dlgOption('wait_on_limit') ? '한도 대기 후 재개' : null,
        dlgOption('claude_sandbox') ? 'Claude 샌드박스' : null].filter(Boolean);
      stage('구현 · 리뷰', [`최대 ${maxR}회`, reviewers.length > 1 ? `리뷰어 ${reviewers.length}명 모두 승인해야 통과` : null],
        h('div', { class: 'wf-row wf-flow' },
          implNode,
          h('div', { class: 'wf-link' }, '→'),
          h('div', { class: 'wf-pill', title: 'duet 가 직접 테스트를 돌린다' }, '테스트', h('small', null, 'duet')),
          h('div', { class: 'wf-link' }, '→'),
          // 리뷰어가 여럿이면 세로로 쌓아 '같은 diff 를 함께 본다'가 보이게
          h('div', { class: 'wf-col' }, reviewNodes)),
        h('div', { class: 'wf-loop' }, `반려되면 지적을 고쳐 다시 테스트·리뷰 (최대 ${maxR}회)`),
        extras.length ? h('div', { class: 'wf-row wf-extra' }, extras) : null,
        guards.length ? h('div', { class: 'wf-guards' }, guards.map(g => h('span', { class: 'wf-guard' }, g))) : null);
    } else if (st.kind === 'audit') {
      stage('감사', ['승인된 뒤, 참고용'], h('div', { class: 'wf-row' }, (st.roles || []).map(r => node('감사', r, [['audit', '']]))));
    }
  }
  for (const a of ['claude', 'codex']) {
    const el = document.getElementById(`ac-sub-${a}`);
    if (el) el.textContent = uses[a].length ? uses[a].join(' · ') : '이 워크플로에서는 쓰지 않음';
  }
  const prev = box._sig || {};
  box.replaceChildren(...stages, h('div', { class: 'wf-end' }, '✓ 승인'));
  // 바뀐 칸만 잠깐 빛나게 (창을 처음 열 때는 안 함)
  if (box._sig) for (const el of box.querySelectorAll('.wf-node[data-key]')) {
    const k = el.getAttribute('data-key');
    if (prev[k] !== undefined && prev[k] !== sig[k]) el.classList.add('wf-changed');
  }
  box._sig = sig;
}
let wfFrame = 0;
function scheduleWorkflowDiagram() {
  cancelAnimationFrame(wfFrame);
  wfFrame = requestAnimationFrame(renderWorkflowDiagram);
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
  dlgState.eff = eff;
  $('#workflow-diagram')._sig = null;
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
  await fillWorkflows(machine, project, eff.workflow);
  $('#run-advanced-body').replaceChildren(...optionFields(app.settings.options || [], {}, o => o.run_dialog));
  $('#run-advanced').open = false;
  renderWorkflowDiagram();
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
form.elements.machine.addEventListener('change', () => { fillRoots(); fillWorkflows(form.elements.machine.value, '', form.elements.workflow.value); });
form.elements.workflow.addEventListener('change', workflowPreview);
form.addEventListener('input', scheduleWorkflowDiagram);
form.addEventListener('change', scheduleWorkflowDiagram);
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
  const classic = f.workflow.value === 'classic' || !f.workflow.value;
  const body = {
    project: computedPath(), task: f.task.value,
    workflow: classic ? undefined : f.workflow.value,
    implementer: classic ? f.implementer.value : undefined, reviewer: classic ? f.reviewer.value : undefined,
    synth: classic ? (f.synth.value || undefined) : undefined,
    debate_rounds: f.debate_rounds.value, max_review: f.max_review.value,
    claude_model: f.claude_model.value.trim(), claude_effort: f.claude_effort.value,
    codex_model: f.codex_model.value.trim(), codex_effort: f.codex_effort.value,
    test_command: f.test_command.value.trim(), block_severity: f.block_severity.value, stall_rounds: f.stall_rounds.value,
    design_only: f.design_only.checked, skip_design: f.skip_design.checked, mock: f.mock.checked, force: f.force.checked,
    options: collectOptions($('#run-advanced-body'), false),
  };
  const problem = !body.project ? (f.root.value === CUSTOM ? '작업 폴더 경로를 입력하세요.' : '폴더 이름을 입력하세요.')
    : !/^([\/~]|[A-Za-z]:[\\/]|\\\\)/.test(body.project) ? '작업 폴더는 절대 경로여야 합니다 (/…, ~/…, C:\\…).'
    : !body.task.trim() ? '과제를 입력하세요.'
    : classic && body.implementer === body.reviewer ? '구현 담당과 리뷰 담당은 달라야 합니다.' : '';
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
  if (!(await askConfirm('UI 를 다시 시작할까요? 같은 주소로 다시 뜨고, 진행 중인 실행은 그대로 돕니다.', { ok: '다시 시작' }))) return;
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
document.querySelectorAll('[data-logo]').forEach(el => el.replaceChildren(agentLogo(el.getAttribute('data-logo'), 22)));
decorateHelp();
window.addEventListener('hashchange', route);
checkServer();
setInterval(checkServer, 20000);
api('/api/setup/actions').then(a => { app.actions = a.actions; }).catch(() => {});
route();
