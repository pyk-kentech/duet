import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity } from "../data";
import { api, RunEvent, subscribeEvents } from "../lib/api";
import { baseName, fmtDur, fmtTok, oneLine } from "../lib/format";
import { Diff, Markdown } from "../lib/markdown";
import { ACTIVITY, OUTCOME, PHASE, STATUS, STEP } from "../lib/labels";
import { hrefProject, hrefRun } from "../lib/router";
import { AgentTag, ErrorBox, Modal, StateDot, StatusBadge, TestTag, useUi, Verdict } from "../ui";
import { DraftsPanel } from "./Drafts";
import { MergePanel, Tree, TREE_STATUS } from "./Merge";
import { Note, NotedDiff } from "./NotedDiff";

interface Entry { name: string; seq: number; label: string; meta: Record<string, string>; verdict?: { status: string; must_fix?: number } | null; draft?: string }
interface RunData {
  project: string; run_dir: string; state: any; entries: Entry[]; live: boolean; live_pid: number | null; stale: boolean;
  console_size: number; current_call: { agent: string; step: string; started: string; elapsed_sec: number; retry?: number } | null;
  resume: { possible: boolean; needs_max_review: boolean; current_max_review: number; reason: string };
  now: string; activity: Activity; last_seq: number;
  code_dir?: string; worktree?: Tree | null; notes_open?: number;
}
const LIVE = "__live__";
const TABS: [string, string][] = [["talk", "대화"], ["drafts", "초안 비교"], ["issues", "지적"], ["console", "콘솔"], ["changes", "변경 사항"], ["design", "설계 문서"]];

export default function RunView({ route, onSeen }: { route: { machine: string; project: string; run: string; tab: string }; onSeen: () => void }) {
  const m = route.machine;
  const tab = route.tab === "timeline" ? "talk" : route.tab;
  const { toast, confirm } = useUi();
  const [data, setData] = useState<RunData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const q = useMemo(() => ({ project: route.project, run: route.run }), [route.project, route.run]);
  const seenOnce = useRef(false);

  const load = useCallback(async () => {
    try {
      const d = await api<RunData>("/api/run", { query: q, machine: m });
      setData(d);
      setError(null);
      if (!d.live && d.activity?.state === "done-unseen" && !seenOnce.current) {   // 끝난 실행을 열었다 → 받은편지함에서 빠짐
        seenOnce.current = true;
        api("/api/runs/seen", { method: "POST", body: q, machine: m }).then(onSeen).catch(() => {});
      }
    } catch (e) { setError(e); }
  }, [q, m, onSeen]);

  useEffect(() => { load(); }, [load]);
  // 실시간: 이벤트가 오면 다시 읽는다(진행 중일 때만 연결). 이벤트 자체는 '최근 활동'에 쓴다.
  useEffect(() => {
    if (!data?.live) return;
    let timer = 0;
    const off = subscribeEvents(m, route.project, route.run, Math.max(0, (data.last_seq || 0) - 40), (evs) => {
      setEvents((prev) => [...prev, ...evs].slice(-200));
      if (evs.some((e) => e.kind !== "log")) { window.clearTimeout(timer); timer = window.setTimeout(load, 300); }
    }, () => load());
    const poll = window.setInterval(() => { if (!document.hidden) load(); }, 8000);   // 이벤트가 끊겨도 따라가게
    return () => { off(); window.clearInterval(poll); window.clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.live, m, route.project, route.run]);

  if (!data) {
    return (
      <div className="page">
        <Crumbs m={m} project={route.project} run={route.run} />
        {error ? <ErrorBox error={error} /> : <div className="empty"><span className="spinner" /></div>}
      </div>
    );
  }
  const st = data.state;
  const stop = async () => {
    if (!(await confirm("진행 중인 실행을 멈춥니다. 나중에 이어하기로 계속할 수 있습니다.", { ok: "중지", danger: true }))) return;
    try { await api("/api/actions/stop", { method: "POST", body: { project: data.project, run: st.run_id }, machine: m }); toast("중지 요청을 보냈습니다."); }
    catch (e) { toast((e as Error).message, true); }
  };
  return (
    <div className="page">
      <Crumbs m={m} project={route.project} run={route.run} />
      {error ? <ErrorBox error={error} /> : null}
      <Head data={data} m={m} onStop={stop} onReload={load} />
      <ResultCard data={data} m={m} q={q} onReload={load} />
      {data.worktree ? <MergePanel m={m} q={q} tree={data.worktree} st={st} live={data.live} onReload={load} /> : null}
      <nav className="tabs">
        {TABS.filter(([k]) => (k !== "issues" || hasFindings(st)) && (k !== "drafts" || st.race)).map(([k, label]) => (
          <a key={k} href={hrefRun(m, route.project, route.run, k)} className={tab === k ? "active" : undefined}>
            {label}{k === "talk" ? <span className="count">{data.entries.length}</span> : k === "issues" && (st.issues || []).length ? <span className="count">{st.issues.length}</span>
              : k === "changes" && data.notes_open ? <span className="count" title="보내지 않은 줄 메모">메모 {data.notes_open}</span> : null}
          </a>
        ))}
      </nav>
      {tab === "drafts" && st.race ? <DraftsPanel m={m} q={q} race={st.race} roles={roleAgents(st)} onReload={load}
                                                  canPick={!data.live && ["done_approved", "done_unapproved"].includes(st.status) && (!data.worktree || data.worktree.status === "open")} />
        : tab === "issues" ? <Issues st={st} /> : tab === "console" ? <ConsolePanel m={m} q={q} live={data.live} />
        : tab === "changes" ? <Changes m={m} q={q} live={data.live} finished={["done_approved", "done_unapproved", "done_design"].includes(st.status)}
                                       editable={!data.worktree || data.worktree.status === "open"} onReload={load} />
        : tab === "design" ? <DesignPanel m={m} q={q} />
        : <Talk data={data} m={m} q={q} events={events} />}
    </div>
  );
}

function Crumbs({ m, project, run }: { m: string; project: string; run: string }) {
  return (
    <div className="crumbs">
      <a href="#/">받은편지함</a><span className="sep">/</span>
      <a href={hrefProject(m, project)}>{baseName(project)}</a><span className="sep">/</span><span className="mono">{run}</span>
    </div>
  );
}

function roleAgents(s: any): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, r] of Object.entries<any>(s.workflow?.roles || {})) out[name] = r.agent || name;
  return out;
}

function hasFindings(s: any) {
  return !!((s.issues || []).length || s.arbiter || Object.keys(s.test_guard || {}).length || Object.keys(s.reverts || {}).length || Object.keys(s.dedup || {}).length);
}

// ---------------------------------------------------------------- 머리
function Head({ data, m, onStop, onReload }: { data: RunData; m: string; onStop: () => void; onReload: () => void }) {
  const { toast } = useUi();
  const st = data.state, c = st.config || {};
  const [maxReview, setMaxReview] = useState<number>(Math.min((data.resume?.current_max_review || 0) + 1, 10));
  const totals: Record<string, { i: number; o: number; usd: number }> = {};
  for (const call of st.calls || []) {
    if (!call.usage) continue;
    const t = (totals[call.agent] ||= { i: 0, o: 0, usd: 0 });
    t.i += call.usage.input_tokens || 0; t.o += call.usage.output_tokens || 0; t.usd += call.usage.cost_usd || 0;
  }
  const totalSec = (st.calls || []).reduce((a: number, x: any) => a + (x.sec || 0), 0);
  const pos = `${PHASE[st.phase] || st.phase} · ${STEP[st.step] || st.step || "-"}${st.round ? ` · ${st.round}회차` : ""}`;
  const resume = async () => {
    try {
      await api("/api/actions/resume", { method: "POST", machine: m,
        body: { project: data.project, run: st.run_id, max_review: data.resume.needs_max_review ? maxReview : undefined } });
      toast("이어하기를 시작했습니다. 잠시 뒤 진행 상황이 보입니다.");
      window.setTimeout(onReload, 1200);
    } catch (e) { toast((e as Error).message, true); }
  };
  const wf = st.workflow;
  const alerts: ReactNode[] = [];
  if (data.stale) alerts.push(<div key="stale" className="alert alert-warn"><b>멈춤</b><span>상태는 ‘실행 중’인데 tenure 프로세스가 없습니다. 이어하기로 계속할 수 있습니다.</span></div>);
  if (st.error && !data.live) alerts.push(<div key="err" className={`alert ${st.status === "failed" ? "alert-bad" : "alert-warn"}`}><b>{STATUS[st.status] || st.status}</b><span>{st.error}</span></div>);
  if (st.limit_wait && data.live) alerts.push(<div key="lw" className="alert alert-warn"><b>한도 대기 중</b><span>{st.limit_wait.role || st.limit_wait.agent} 의 구독 한도에 걸려 {String(st.limit_wait.until || "").replace("T", " ").slice(5, 16)} 에 다시 시도합니다.</span></div>);
  if (st.stop_reason === "stalled" && !data.live) alerts.push(<div key="stall" className="alert alert-warn"><b>수렴 안 됨</b><span>막는 지적 수가 줄지 않아 멈췄습니다. 마지막 리뷰를 읽고 판단하거나 이어하기로 계속하세요.</span></div>);
  const guards = Object.entries(st.test_guard || {}).filter(([, g]: any) => (g.signals || []).length);
  if (guards.length) alerts.push(<div key="tg" className="alert alert-warn"><b>테스트 변경 감지</b><span>구현자가 테스트를 지우거나 약하게 바꾼 흔적이 있어 리뷰어에게 경고로 전달했습니다.</span></div>);

  return (
    <section className="card card-pad col" style={{ gap: 10 }}>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <StateDot state={data.live ? "working" : data.activity?.state} />
        <h1 className="mono" style={{ fontSize: 18 }}>{st.run_id}</h1>
        <StatusBadge status={st.status} live={data.live} stale={data.stale} />
        <span className="muted">{pos}</span>
        {data.activity?.reason ? <span className="faint small">· {data.activity.reason}</span> : null}
        <span className="spacer" />
        {data.live ? <button className="btn btn-danger" type="button" onClick={onStop}>중지</button> : data.resume?.possible ? (
          <div className="row">
            {data.resume.needs_max_review ? (
              <label className="row small">리뷰 최대
                <input type="number" min={data.resume.current_max_review + 1} max={10} value={maxReview} style={{ width: 64 }}
                       onChange={(e) => setMaxReview(Number(e.target.value))} aria-label="리뷰 최대 횟수" />회까지</label>
            ) : null}
            <button className="btn btn-primary" type="button" onClick={resume}>{data.resume.needs_max_review ? "리뷰 계속하기" : "이어하기"}</button>
          </div>
        ) : null}
      </div>
      <div className="chips">
        {m !== "local" ? <span className="chip">머신 <b>{m}</b></span> : null}
        {wf ? <span className="chip">워크플로 <b>{wf.name}</b></span> : <span className="chip">워크플로 <b>classic</b></span>}
        {st.route ? <span className="chip" title={st.route.reason}>자동 선택 · {st.route.source === "model" ? "모델 판단" : "규칙"}</span> : null}
        {!wf ? <span className="chip">구현 <b>{c.implementer}</b> · 리뷰 <b>{c.reviewer}</b> · 최대 {c.max_review}회</span> : null}
        {c.access ? <span className={`chip${c.access === "full" ? " warn" : ""}`}>권한 <b>{c.access}</b></span> : null}
        {c.web_search === "on" ? <span className="chip">웹 검색</span> : null}
        {(st.attachments || []).length ? <span className="chip" title={st.attachments.join("\n")}>첨부 {st.attachments.length}개</span> : null}
        {c.mock ? <span className="chip">mock</span> : null}
        {data.worktree ? <span className="chip" title={data.code_dir}>브랜치 <b className="mono">{data.worktree.branch}</b>
          <span className={`badge ${TREE_STATUS[data.worktree.status].cls}`} style={{ height: 18 }}>{TREE_STATUS[data.worktree.status].text}</span></span> : null}
        {st.base_commit ? <span className="chip">기준 <b className="mono">{st.base_commit}</b></span> : null}
        <span className="chip">호출 {(st.calls || []).length}회 · {fmtDur(totalSec)}</span>
        {Object.entries(totals).map(([a, t]) => (
          <span key={a} className="chip"><AgentTag name={a} /> 입력 {fmtTok(t.i)} · 출력 {fmtTok(t.o)}</span>
        ))}
      </div>
      <Rounds data={data} />
      {st.task.length > 240
        ? <details><summary className="muted small">과제: {oneLine(st.task, 110)}</summary><div className="task-box">{st.task}</div></details>
        : <div className="task-box">{st.task}</div>}
      {alerts}
    </section>
  );
}

function Rounds({ data }: { data: RunData }) {
  const st = data.state;
  const hist: Record<string, any> = {};
  for (const x of st.review_history || []) {
    if (x.reviewers) for (const r of x.reviewers) hist[r.file] = r; else hist[x.file] = x;
  }
  const items: ReactNode[] = [];
  for (const e of data.entries) {
    const s = e.meta.step;
    const failed = e.meta.ok === "false" || e.label.endsWith("_failed");
    if (failed && s !== "test") continue;
    if (s === "implement" || s === "fix") items.push(<span key={e.name} className="chip">{e.draft ? `초안 ${e.draft} · ` : ""}{e.meta.round}회차 {STEP[s]}</span>);
    else if (s === "test") items.push(<span key={e.name} className="row" style={{ gap: 4, display: "inline-flex" }}>→ <TestTag status={e.meta.test_status} /></span>);
    else if (s === "review") {
      const h = hist[e.name];
      items.push(<span key={e.name} className="row" style={{ gap: 4, display: "inline-flex" }}>→ <span className="chip">리뷰 {h ? (h.approved ? <span className="verdict v-APPROVED">승인</span> : <span className="verdict v-CHANGES_REQUESTED">반려{h.blocking != null ? ` ${h.blocking}` : ""}</span>) : <Verdict v={e.verdict} />}</span></span>);
    }
  }
  if (!items.length) return null;
  return <div className="row faint small" style={{ flexWrap: "wrap", gap: 6 }}><span>리뷰 이력</span>{items}</div>;
}

// ---------------------------------------------------------------- 결과 요약 (32장)
function ResultCard({ data, m, q, onReload }: { data: RunData; m: string; q: Record<string, string>; onReload: () => void }) {
  const { toast } = useUi();
  const st = data.state;
  const [body, setBody] = useState<string | null>(null);
  const finished = st.status === "done_approved" || st.status === "done_unapproved";
  useEffect(() => {
    setBody(null);
    if (!finished || data.live || !st.report) return;
    api<{ body: string }>("/api/entry", { query: { ...q, file: st.report }, machine: m }).then((e) => setBody(e.body)).catch(() => {});
  }, [finished, data.live, st.report, m, q]);
  if (!finished || data.live) return null;
  const make = async () => {
    try {
      await api("/api/actions/report", { method: "POST", body: q, machine: m });
      toast("결과 요약을 만드는 중입니다. 끝나면 여기에 보입니다.");
      window.setTimeout(onReload, 4000);
    } catch (e) { toast((e as Error).message, true); }
  };
  return (
    <section className="card card-pad">
      <div className="row" style={{ marginBottom: 6 }}>
        <h2>결과 요약</h2><span className="faint small">무엇을 만들었고 어떻게 실행하는지</span><span className="spacer" />
        <button className="btn btn-sm" type="button" onClick={make}>{st.report ? "다시 만들기" : "결과 요약 만들기"}</button>
      </div>
      {st.report ? (body ? <div className="md"><Markdown text={body} /></div> : <div className="faint small">불러오는 중…</div>)
        : <div className="muted small">이 실행에는 아직 요약이 없습니다. 만들면 작은 모델을 한 번 부릅니다.</div>}
    </section>
  );
}

// ---------------------------------------------------------------- 대화 (타임라인 + 보기)
function Talk({ data, m, q, events }: { data: RunData; m: string; q: Record<string, string>; events: RunEvent[] }) {
  const [sel, setSel] = useState<string | null>(null);
  const [auto, setAuto] = useState(true);
  const [big, setBig] = useState<string | null>(null);
  const cache = useRef(new Map<string, any>());
  const selected = data.live && (auto || !sel) ? LIVE : sel || (data.entries.length ? data.entries[data.entries.length - 1].name : null);
  const pick = (name: string) => { setSel(name); setAuto(name === LIVE); };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 380px) 1fr", gap: 12, alignItems: "start" }}>
      <div className="card timeline" role="list">
        {data.entries.length === 0 && !data.live ? <div className="empty small">아직 기록이 없습니다.</div> : null}
        {data.entries.map((e) => {
          const meta = e.meta;
          const failed = meta.step !== "test" && (meta.ok === "false" || e.label.endsWith("_failed"));
          const outcome = meta.outcome;
          return (
            <div key={e.name} role="listitem" className={`tl-item clickable${selected === e.name ? " tl-live" : ""}`}
                 onClick={() => pick(e.name)} onDoubleClick={() => setBig(e.name)}>
              <span className="time">{String(e.seq).padStart(2, "0")}</span>
              <StateDot state={failed ? (outcome === "blocked" ? "blocked" : "failed") : "idle"} title={outcome ? OUTCOME[outcome] : undefined} />
              <div style={{ minWidth: 0 }}>
                <div className="row"><AgentTag name={meta.agent} role={meta.role} /><b className="ellipsis">{STEP[meta.step] || meta.step}</b>
                  {e.draft ? <span className="badge info" style={{ height: 18 }}>초안 {e.draft}</span> : null}</div>
                <div className="meta">
                  {meta.round && meta.round !== "0" ? `${meta.round}회차 · ` : ""}
                  {failed ? `${meta.reason || (meta.rate_limited === "true" ? "한도 도달" : meta.timed_out === "true" ? "시간 초과" : `실패 (exit ${meta.exit_code})`)} · ` : ""}
                  {meta.tokens_out ? `출력 ${fmtTok(Number(meta.tokens_out))}` : ""}
                </div>
              </div>
              <div className="col" style={{ gap: 4, alignItems: "flex-end" }}>
                <span className="faint small">{meta.duration_sec ? fmtDur(Number(meta.duration_sec)) : ""}</span>
                {meta.step === "test" ? <TestTag status={meta.test_status} /> : <Verdict v={e.verdict} />}
              </div>
            </div>
          );
        })}
        {data.live ? (
          <div role="listitem" className={`tl-item clickable${selected === LIVE ? " tl-live" : ""}`} onClick={() => pick(LIVE)}>
            <span className="time"><span className="spinner" /></span>
            <StateDot state="working" />
            <div><div className="row">{data.current_call ? <AgentTag name={data.current_call.agent} /> : null}
              <b>{data.current_call ? `${STEP[data.current_call.step] || data.current_call.step} 진행 중` : "준비 중"}</b></div>
              <div className="meta">{data.current_call?.retry ? `재시도 ${data.current_call.retry}` : ""}</div></div>
            <span className="faint small">{data.current_call ? fmtDur(data.current_call.elapsed_sec) : ""}</span>
          </div>
        ) : null}
      </div>
      <section className="card" style={{ minHeight: 320 }}>
        {selected === LIVE ? <LivePanel data={data} m={m} q={q} events={events} />
          : selected ? <EntryPanel name={selected} data={data} m={m} q={q} cache={cache.current} onBig={() => setBig(selected)} />
          : <div className="empty">왼쪽에서 기록을 고르세요.</div>}
      </section>
      {big ? <EntryModal name={big} data={data} m={m} q={q} cache={cache.current} onClose={() => setBig(null)} /> : null}
    </div>
  );
}

function useEntry(name: string, m: string, q: Record<string, string>, cache: Map<string, any>) {
  const [entry, setEntry] = useState<any>(cache.get(name) || null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let alive = true;
    if (cache.has(name)) { setEntry(cache.get(name)); return; }
    setEntry(null);
    api("/api/entry", { query: { ...q, file: name }, machine: m })
      .then((e) => { cache.set(name, e); if (alive) setEntry(e); })
      .catch((e) => { if (alive) setError(e); });
    return () => { alive = false; };
  }, [name, m, q, cache]);
  return { entry, error };
}

function EntryPanel({ name, data, m, q, cache, onBig }: { name: string; data: RunData; m: string; q: Record<string, string>; cache: Map<string, any>; onBig: () => void }) {
  const { entry, error } = useEntry(name, m, q, cache);
  const listed = data.entries.find((x) => x.name === name);
  if (error) return <div className="card-pad"><ErrorBox error={error} /></div>;
  if (!entry) return <div className="empty"><span className="spinner" /></div>;
  const meta = entry.meta || {};
  const info = [meta.model ? meta.model + (meta.effort ? `·${meta.effort}` : "") : "", meta.mode === "write" ? "쓰기" : meta.mode === "read" ? "읽기 전용" : "",
    meta.duration_sec ? fmtDur(Number(meta.duration_sec)) : "", meta.tokens_out ? `출력 ${fmtTok(Number(meta.tokens_out))} 토큰` : "",
    meta.timestamp ? String(meta.timestamp).replace("T", " ") : ""].filter(Boolean).join(" · ");
  return (
    <>
      <div className="dialog-head" style={{ flexWrap: "wrap" }}>
        <AgentTag name={meta.agent} role={meta.role} /><b>{STEP[meta.step] || meta.step}</b>
        {meta.round && meta.round !== "0" ? <span className="muted">{meta.round}회차</span> : null}
        {listed ? <Verdict v={listed.verdict} /> : null}
        <span className="spacer" /><span className="faint small">{info}</span>
        <button className="btn btn-sm" type="button" onClick={onBig}>크게 보기</button>
      </div>
      <div className="card-pad md"><Markdown text={entry.body} /></div>
    </>
  );
}

function EntryModal({ name, data, m, q, cache, onClose }: { name: string; data: RunData; m: string; q: Record<string, string>; cache: Map<string, any>; onClose: () => void }) {
  const { entry, error } = useEntry(name, m, q, cache);
  const meta = entry?.meta || {};
  return (
    <Modal onClose={onClose} label="기록 보기" wide>
      <div className="dialog-head">
        <AgentTag name={meta.agent} role={meta.role} /><b>{STEP[meta.step] || meta.step || ""}</b>
        <span className="spacer" /><span className="mono faint small">{name}</span>
        <button className="btn btn-sm" type="button" onClick={onClose}>닫기</button>
      </div>
      <div className="dialog-body md">{error ? <ErrorBox error={error} /> : entry ? <Markdown text={entry.body} /> : <span className="spinner" />}</div>
      {data ? null : null}
    </Modal>
  );
}

const KIND: Record<string, string> = { read: "읽기", edit: "수정", command: "명령", search: "검색", message: "메시지", tool: "도구" };

function LivePanel({ data, m, q, events }: { data: RunData; m: string; q: Record<string, string>; events: RunEvent[] }) {
  const [act, setAct] = useState<{ call: any; events: { ts: string; kind: string; text: string; detail?: string }[] } | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try { const a = await api("/api/activity", { query: q, machine: m }); if (alive) setAct(a); } catch { /* 다음에 */ }
    };
    tick();
    const id = window.setInterval(() => { if (!document.hidden) tick(); }, 2500);
    return () => { alive = false; window.clearInterval(id); };
  }, [m, q]);
  const root = String(data.project).replace(/[\\/]+$/, "");
  const rel = (t: string) => String(t).split(root + "/").join("").split(root + "\\").join("");
  const recent = events.filter((e) => e.kind !== "log").slice(-8);
  return (
    <>
      <div className="dialog-head">
        <span className="spinner" />{act?.call ? <AgentTag name={act.call.agent} /> : null}
        <b>{act?.call ? `${STEP[act.call.step] || act.call.step} 진행 중` : "준비 중"}</b>
        <span className="spacer" />{act?.call ? <span className="faint small">{act.call.started} 시작 · {fmtDur(act.call.elapsed_sec)}</span> : null}
      </div>
      <div className="card-pad">
        {!act?.call ? <div className="muted">다음 단계를 준비하고 있습니다.</div>
          : !act.events.length ? <div className="muted">{act.call.agent} 가 시작했습니다. 첫 동작을 기다리는 중…</div>
          : <div className="activity-list">{act.events.map((ev, n) => (
              <div key={n} className="act"><span className="k">{KIND[ev.kind] || ev.kind}</span>
                <span className={ev.kind === "message" ? "" : "mono"}>{rel(ev.text)}{ev.detail ? <span className="faint"> — {ev.detail}</span> : null}</span></div>
            ))}</div>}
        {recent.length ? (
          <div style={{ marginTop: 14 }}>
            <div className="faint small" style={{ marginBottom: 4 }}>최근 단계</div>
            <div className="activity-list">{recent.map((e) => (
              <div key={e.seq} className="act"><span className="k mono">{String(e.ts).slice(11, 19)}</span>
                <span>{e.kind === "step_start" ? `${e.role || e.agent} ← ${STEP[e.step] || e.step} 시작`
                  : e.kind === "step_end" ? `${e.role || e.agent} ← ${STEP[e.step] || e.step} ${OUTCOME[e.outcome] || e.outcome}${e.reason ? ` (${e.reason})` : ""}`
                  : e.kind === "state" ? `상태: ${STATUS[e.status] || e.status} · ${PHASE[e.phase] || e.phase}`
                  : e.kind === "attention" ? `확인 필요: ${e.reason}` : e.kind}</span></div>
            ))}</div>
          </div>
        ) : null}
        <div className="faint small" style={{ marginTop: 10 }}>{ACTIVITY[data.activity?.state] || ""}</div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- 지적
function Issues({ st }: { st: any }) {
  const ST: Record<string, string> = { open: "열림", resolved: "해결", rejected: "기각" };
  const TONE: Record<string, string> = { open: "warn", resolved: "ok", rejected: "" };
  const BASIS: Record<string, string> = { requirement: "요구 위반", correctness: "정확성", security: "보안", preference: "취향" };
  const issues = st.issues || [];
  return (
    <div className="col">
      {st.arbiter ? (
        <div className="card card-pad"><h3>중재</h3>
          <div className="chips" style={{ marginTop: 6 }}>
            <span className="chip">{st.arbiter.round}라운드</span>
            <span className="chip">유지 {(st.arbiter.upheld || []).join(", ") || "-"}</span>
            <span className="chip">완화 {(st.arbiter.downgraded || []).join(", ") || "-"}</span>
            <span className="chip">기각 {(st.arbiter.rejected || []).join(", ") || "-"}</span>
          </div></div>
      ) : null}
      {issues.length ? (
        <div className="card table-scroll"><table className="list">
          <thead><tr><th>ID</th><th>리뷰어</th><th>심각도</th><th>지적</th><th>근거</th><th>상태</th><th>라운드</th></tr></thead>
          <tbody>{issues.map((x: any) => (
            <tr key={x.id} style={{ cursor: "default" }}>
              <td className="mono">{x.id}</td><td>{x.role}</td><td><b>{x.severity}</b></td>
              <td><div>{x.title}</div>{x.file ? <div className="mono faint small">{x.file}</div> : null}</td>
              <td className="small">{BASIS[x.basis] || "-"}</td>
              <td><span className={`badge ${TONE[x.status] || ""}`}>{ST[x.status] || x.status}</span></td>
              <td className="mono small">{x.round} → {x.closed_round ?? "…"}</td>
            </tr>))}</tbody>
        </table></div>
      ) : <p className="muted">지적 원장이 없습니다.</p>}
    </div>
  );
}

// ---------------------------------------------------------------- 콘솔
function ConsolePanel({ m, q, live }: { m: string; q: Record<string, string>; live: boolean }) {
  const [text, setText] = useState("");
  const offset = useRef(0);
  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const c = await api<{ text: string; offset: number }>("/api/console", { query: { ...q, offset: offset.current }, machine: m });
        if (!alive) return;
        offset.current = c.offset;
        if (c.text) {
          const el = ref.current;
          const atBottom = !el || el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
          setText((t) => t + c.text);
          if (atBottom) requestAnimationFrame(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; });
        }
      } catch { /* 다음에 */ }
    };
    tick();
    const id = live ? window.setInterval(tick, 2000) : 0;
    return () => { alive = false; window.clearInterval(id); };
  }, [m, q, live]);
  return (
    <div className="card">
      <div className="dialog-head"><b>진행 로그</b><span className="mono faint small">console.log</span><span className="spacer" /><span className="faint small">터미널에 찍힌 것과 같습니다</span></div>
      <pre className="console" ref={ref}>{text || "(아직 로그가 없습니다.)"}</pre>
    </div>
  );
}

// ---------------------------------------------------------------- 변경 사항
function Changes({ m, q, live, finished, editable, onReload }: {
  m: string; q: Record<string, string>; live: boolean; finished: boolean; editable: boolean; onReload: () => void;
}) {
  const { toast, confirm } = useUi();
  const [commits, setCommits] = useState<{ base: string | null; commits: { sha: string; short: string; subject: string; date: string }[] } | null>(null);
  const [sel, setSel] = useState("");
  const [diff, setDiff] = useState<{ text: string; truncated: boolean; title: string } | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const loadNotes = useCallback(() => {
    api<{ notes: Note[] }>("/api/notes", { query: q, machine: m }).then((r) => setNotes(r.notes)).catch(() => {});
  }, [m, q]);
  useEffect(() => {
    let alive = true;
    const load = () => api("/api/commits", { query: q, machine: m }).then((c) => { if (alive) setCommits(c); }).catch(() => {});
    load();
    loadNotes();
    const id = live ? window.setInterval(load, 6000) : 0;
    return () => { alive = false; window.clearInterval(id); };
  }, [m, q, live, loadNotes]);
  useEffect(() => {
    setDiff(null);
    api("/api/diff", { query: { ...q, commit: sel || undefined }, machine: m }).then(setDiff).catch((e) => setDiff({ text: String(e.message), truncated: false, title: "오류" }));
  }, [m, q, sel, commits?.commits.length]);
  const add = async (n: { file: string; line: number; side: string; text: string }) => {
    try { await api("/api/notes", { method: "POST", body: { ...q, ...n }, machine: m }); loadNotes(); onReload(); return true; }
    catch (e) { toast((e as Error).message, true); return false; }
  };
  const del = async (id: string) => {
    try { await api("/api/notes", { method: "DELETE", query: { ...q, id }, machine: m }); loadNotes(); onReload(); }
    catch (e) { toast((e as Error).message, true); }
  };
  const open = notes.filter((n) => n.status === "open");
  const send = async () => {
    const stale = open.filter((n) => n.stale).length;
    const msg = `열린 메모 ${open.length}개를 구현 담당에게 보내 고치게 하고, 커밋·테스트를 돌립니다. 에이전트를 한 번 부릅니다.`
      + (stale ? `\n\n그중 ${stale}개는 메모를 단 뒤 줄이 바뀌었습니다(오래됨).` : "") + "\n다시 리뷰할지는 끝난 뒤 정합니다.";
    if (!(await confirm(msg, { ok: "보내기" }))) return;
    try {
      await api("/api/actions/notes", { method: "POST", body: q, machine: m });
      toast("메모를 보냈습니다. 잠시 뒤 진행 상황이 보입니다.");
      window.setTimeout(onReload, 1200);
    } catch (e) { toast((e as Error).message, true); }
  };
  const canNote = editable && !live && sel === "";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(240px, 320px) minmax(0, 1fr)", gap: 12, alignItems: "start" }}>
      <div className="col" style={{ gap: 12 }}>
        <div className="card timeline">
          <div className={`tl-item clickable${sel === "" ? " tl-live" : ""}`} style={{ gridTemplateColumns: "1fr" }} onClick={() => setSel("")}>
            <div><b>기준 대비 전체</b><div className="meta">리뷰어가 받는 diff · 줄을 눌러 메모</div></div></div>
          {(commits?.commits || []).map((c) => (
            <div key={c.sha} className={`tl-item clickable${sel === c.sha ? " tl-live" : ""}`} style={{ gridTemplateColumns: "64px 1fr" }} onClick={() => setSel(c.sha)}>
              <span className="time">{c.short}</span><div className="ellipsis" title={c.subject}>{c.subject}</div>
            </div>
          ))}
        </div>
        {notes.length ? (
          <div className="card card-pad col" style={{ gap: 8 }}>
            <div className="row"><b>줄 메모</b><span className="faint small">열림 {open.length} · 보냄 {notes.length - open.length}</span></div>
            {notes.map((n) => (
              <div key={n.id} className="small" style={{ opacity: n.status === "sent" ? 0.6 : 1 }}>
                <span className="mono">{n.file}:{n.line}</span>{n.side === "old" ? <span className="faint"> (바뀌기 전)</span> : null}
                {n.stale ? <span className="badge warn" style={{ marginLeft: 6, height: 18 }}>오래됨</span> : null}
                <div className="ellipsis" title={n.text}>{n.text}</div>
              </div>
            ))}
            <button className="btn btn-primary btn-sm btn-block" type="button" onClick={send} disabled={!open.length || live || !finished}
                    title={!finished ? "실행이 끝난 뒤 보낼 수 있습니다" : live ? "진행 중입니다" : undefined}>에이전트에게 보내기 ({open.length})</button>
          </div>
        ) : null}
      </div>
      <section className="card">
        <div className="dialog-head"><b className="ellipsis">{diff?.title || "불러오는 중…"}</b>{diff?.truncated ? <span className="badge warn">일부만</span> : null}</div>
        {!diff ? <div className="empty"><span className="spinner" /></div>
          : sel === "" ? <NotedDiff text={diff.text} notes={notes} canEdit={canNote} onAdd={add} onDelete={del} />
          : <Diff text={diff.text} />}
      </section>
    </div>
  );
}

function DesignPanel({ m, q }: { m: string; q: Record<string, string> }) {
  const [d, setD] = useState<{ text: string | null; path: string } | null>(null);
  useEffect(() => { api("/api/design", { query: q, machine: m }).then(setD).catch(() => setD({ text: null, path: "" })); }, [m, q]);
  return (
    <div className="card card-pad">
      {d === null ? <span className="spinner" /> : d.text ? <><div className="mono faint small" style={{ marginBottom: 8 }}>{d.path}</div><div className="md"><Markdown text={d.text} /></div></>
        : <div className="empty">설계 문서가 없습니다{d.path ? ` (${d.path})` : ""}.</div>}
    </div>
  );
}
