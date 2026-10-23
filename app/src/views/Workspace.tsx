import { lazy, ReactNode, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../icons";
import { api, LOCAL } from "../lib/api";
import { baseName, oneLine } from "../lib/format";
import { Diff } from "../lib/markdown";
import { openSession, SESSION_STATE, SessionInfo, SessionStatus, sessionDot } from "../sessions";
import { ErrorBox, useUi } from "../ui";
import { hrefWs, parseTabKey, Tab, tabKey, useOpenTabs, usePref, WsRef, wsSessions } from "../ws";
import type { NewRunInit } from "./NewRun";
import ProjectView from "./Project";
import RightPanel, { RpKind } from "./RightPanel";
import { FlowTab, RunPanel, runPanels, useRunData } from "./Run";
import { Shape } from "./WorkList";

const Term = lazy(() => import("./Term"));          // xterm 은 무거워 터미널 탭을 열 때만

const PANEL_TITLE: Record<string, string> = { changes: "변경 · 줄 메모", drafts: "초안 비교", design: "설계 문서", console: "진행 로그", issues: "지적" };

/** 작업공간 (오르카 워크벤치, 36.22): 가운데 탭 묶음(둘로 나누기) + 오른쪽 판. */
export default function Workspace({ ws, tabParam, panelParam, sessions, rpWidth, onSeen, onSessions, onNewRun, onRpResize }: {
  ws: WsRef; tabParam: string | null; panelParam: string | null; sessions: SessionInfo[]; rpWidth: number;
  onSeen: () => void; onSessions: () => void; onNewRun: (i: NewRunInit) => void; onRpResize: (startX: number) => void;
}) {
  const { toast, confirm } = useUi();
  const { data: run, error: runError, events, q, load } = useRunData(ws.machine, ws.project, ws.run || "", onSeen);
  const mine = useMemo(() => wsSessions(ws, sessions), [ws, sessions]);
  const { open: opened, add, remove } = useOpenTabs(ws);
  const [split, setSplit] = useState<string | null>(null);
  const [menu, setMenu] = useState<null | { x: number; y: number }>(null);
  const [rpOpen, setRpOpen] = usePref("rpOpen", true);
  const [rpKind, setRpKind] = usePref<RpKind>("rpKind", "files");

  useEffect(() => { setSplit(null); setMenu(null); }, [ws.machine, ws.project, ws.run]);
  useEffect(() => { if (panelParam === "merge") { setRpKind("git"); setRpOpen(true); } }, [panelParam]);   // eslint-disable-line react-hooks/exhaustive-deps

  // 탭 목록: 고정 탭 · 세션(터미널) · 사용자가 연 탭
  const fixed: Tab = ws.run ? { kind: "flow" } : { kind: "overview" };
  const tabs: Tab[] = useMemo(() => {
    const list: Tab[] = [fixed, ...mine.map((s) => ({ kind: "session", id: s.id }) as Tab)];
    for (const k of opened) { const t = parseTabKey(k); if (t && t.kind !== "session" && t.kind !== fixed.kind) list.push(t); }
    return list;
  }, [mine, opened, fixed.kind]);   // eslint-disable-line react-hooks/exhaustive-deps
  const keys = tabs.map(tabKey);
  const wanted = parseTabKey(tabParam);
  const active = wanted && (keys.includes(tabKey(wanted)) || wanted.kind !== "session") ? tabKey(wanted) : tabKey(fixed);
  useEffect(() => {                                 // 주소로 연 파일·판 탭은 목록에 남긴다
    if (wanted && wanted.kind !== "session" && wanted.kind !== fixed.kind && !opened.includes(tabKey(wanted))) add(tabKey(wanted));
  }, [tabParam]);   // eslint-disable-line react-hooks/exhaustive-deps

  const go = (k: string) => { location.hash = hrefWs(ws, k); };
  const openTab = (t: Tab) => { const k = tabKey(t); if (t.kind !== "session") add(k); go(k); };
  const closeTab = async (k: string) => {
    const t = parseTabKey(k);
    if (!t || t.kind === fixed.kind) return;
    if (t.kind === "session") {
      const s = mine.find((x) => x.id === t.id);
      if (s?.live) {
        if (!(await confirm(`${s.agent === "shell" ? "터미널" : `${s.agent} 세션`}을 끝냅니다. 지금 하던 일은 멈춥니다.`, { ok: "끝내고 닫기", danger: true }))) return;
        await api("/api/session/kill", { method: "POST", body: { id: t.id } }).catch(() => {});
        await new Promise((r) => window.setTimeout(r, 400));
      }
      await api("/api/session/close", { method: "POST", body: { id: t.id } }).catch((e) => toast((e as Error).message, true));
      onSessions();
    } else remove(k);
    if (split === k) setSplit(null);
    if (active === k) { const i = keys.indexOf(k); go(keys[i - 1] || keys[0]); }
  };
  const newSession = async (agent: string) => {
    setMenu(null);
    try {
      const s = await openSession(agent, ws.project, ws.run || undefined);
      onSessions();
      window.setTimeout(() => go(`s:${s.id}`), 250);
    } catch (e) { toast((e as Error).message, true); }
  };

  const title = (t: Tab): ReactNode => {
    if (t.kind === "flow") return "흐름";
    if (t.kind === "overview") return "개요";
    if (t.kind === "session") { const s = mine.find((x) => x.id === t.id); return s ? (s.agent === "shell" ? "터미널" : s.title || (s.agent === "claude" ? "Claude" : "Codex")) : "세션"; }
    if (t.kind === "file" || t.kind === "diff") return baseName(t.path) + (t.kind === "diff" ? " (변경)" : "");
    return PANEL_TITLE[t.kind] || t.kind;
  };
  const icon = (t: Tab): ReactNode => {
    if (t.kind === "session") {
      const s = mine.find((x) => x.id === t.id);
      if (!s) return <Icon name="terminal" />;
      if (s.agent === "shell") return <Icon name="terminal" />;
      const st = sessionDot(s);
      return st === "idle" ? <img src={`/logos/${s.agent}.svg`} alt="" width={13} height={13} /> : <Shape state={st} />;
    }
    if (t.kind === "flow") return run ? <Shape state={run.live ? "working" : run.activity?.state || "idle"} /> : <Icon name="flow" />;
    if (t.kind === "overview") return <Icon name="folder" />;
    if (t.kind === "file") return <Icon name="doc" />;
    return <Icon name="diff" />;
  };

  const view = (k: string): ReactNode => {
    const t = parseTabKey(k);
    if (!t) return null;
    if (t.kind === "flow") return run ? <FlowTab data={run} m={ws.machine} q={q} events={events} onReload={load} />
      : runError ? <div className="page"><ErrorBox error={runError} /></div> : <div className="empty"><span className="spinner" /></div>;
    if (t.kind === "overview") return <ProjectView route={{ machine: ws.machine, project: ws.project, tab: "runs" }} onNewRun={onNewRun} onChanged={onSeen} onSession={onSessions} embedded />;
    if (t.kind === "file") return <FileView ws={ws} path={t.path} />;
    if (t.kind === "diff") return <DiffView ws={ws} path={t.path} />;
    if (t.kind === "session") return null;          // 터미널은 따로 (계속 붙어 있게)
    return run ? <RunPanel kind={t.kind} data={run} m={ws.machine} q={q} onReload={load} /> : <div className="empty">실행 작업공간에서만 볼 수 있습니다.</div>;
  };

  // 세션 탭은 모두 붙여 두고 보이는 것만 드러낸다 (탭을 바꿔도 터미널이 다시 그려지지 않게)
  const terms = (pane: "left" | "right") => mine.filter((s) => (pane === "right" ? split === `s:${s.id}` : split !== `s:${s.id}`)).map((s) => {
    const k = `s:${s.id}`;
    const shown = pane === "right" || active === k;
    return (
      <div key={k} className={`tab-view${shown ? "" : " hidden"}`}>
        <SessionPane s={s} active={shown} onChanged={onSessions} />
      </div>
    );
  });

  const actions = (): ReactNode => {
    if (run) {
      const st = run.state;
      return (
        <>
          {run.worktree?.status === "open" && !run.live && ["done_approved", "done_unapproved"].includes(st.status)
            ? <button type="button" className="btn btn-primary" onClick={() => { setRpKind("git"); setRpOpen(true); }}>합치기…</button> : null}
          {run.live ? <button type="button" className="btn btn-danger" onClick={() => go("flow")}>진행 중 · 중지는 흐름에서</button> : null}
        </>
      );
    }
    return <button type="button" className="btn btn-primary" onClick={() => onNewRun({ machine: ws.machine, project: ws.project })}>새 흐름 실행</button>;
  };

  const plusRef = useRef<HTMLButtonElement>(null);
  const openMenu = () => {
    const r = plusRef.current?.getBoundingClientRect();
    setMenu(menu ? null : { x: r ? r.left : 0, y: r ? r.bottom + 4 : 0 });
  };
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent && e.key !== "Escape") return;
      if (e instanceof MouseEvent && (e.target as HTMLElement).closest(".menu")) return;
      setMenu(null);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", close); };
  }, [menu]);

  const local = ws.machine === LOCAL;
  const leftKeys = keys.filter((k) => k !== split);
  return (
    <div className="ide-row" style={{ flex: 1, minWidth: 0 }}>
      <div className="ide-center">
        <div className="tg">
          <div className="tg-pane">
            <div className="tabbar" role="tablist" aria-label="탭">
              <div className="tabs-scroll">
                {tabs.filter((t) => tabKey(t) !== split).map((t) => {
                  const k = tabKey(t);
                  return (
                    <div key={k} role="tab" aria-selected={active === k} className={`tab${active === k ? " on" : ""}`} tabIndex={0}
                         onClick={() => go(k)} onKeyDown={(e) => { if (e.key === "Enter") go(k); }}
                         onAuxClick={(e) => { if (e.button === 1) closeTab(k); }} title={typeof title(t) === "string" ? String(title(t)) : undefined}>
                      {icon(t)}<span className="t">{title(t)}</span>
                      {t.kind !== fixed.kind ? <button type="button" className="x" aria-label="탭 닫기" onClick={(e) => { e.stopPropagation(); closeTab(k); }}>×</button> : null}
                    </div>
                  );
                })}
              </div>
              <button ref={plusRef} type="button" className="tb-icon" title="새 탭" aria-label="새 탭" onClick={openMenu}><Icon name="plus" /></button>
              <button type="button" className={`tb-icon${split ? " on" : ""}`} title={split ? "나누기 닫기" : "지금 탭을 옆에 나눠 보기"} aria-label="나누기"
                      onClick={() => {
                        if (split) { setSplit(null); return; }
                        const other = leftKeys.find((k) => k !== active);
                        if (!other) { toast("나눠 볼 다른 탭이 없습니다. + 로 탭을 더 여세요."); return; }
                        setSplit(active); go(other);
                      }}><Icon name="split" /></button>
              <div className="tb-actions">{actions()}</div>
            </div>
            <div className="tab-body">
              {terms("left")}
              {!active.startsWith("s:") ? <div className="tab-view">{view(active)}</div> : null}
            </div>
          </div>
          {split ? (
            <div className="tg-pane">
              <div className="tabbar">
                <div className="tab on" style={{ width: "auto", flex: 1 }}>{(() => { const t = parseTabKey(split); return t ? <>{icon(t)}<span className="t">{title(t)}</span></> : null; })()}
                  <button type="button" className="x" aria-label="나누기 닫기" onClick={() => setSplit(null)}>×</button></div>
              </div>
              <div className="tab-body">
                {terms("right")}
                {!split.startsWith("s:") ? <div className="tab-view">{view(split)}</div> : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>
      <div className={`resizer`} style={{ display: rpOpen ? undefined : "none" }}><span onMouseDown={(e) => { e.preventDefault(); onRpResize(e.clientX); }} /></div>
      <div style={{ ["--rp-w" as string]: `${rpWidth}px`, display: "flex" }}>
        <RightPanel ws={ws} run={run} kind={rpKind} open={rpOpen} onKind={setRpKind} onToggle={() => setRpOpen(!rpOpen)}
                    onOpen={openTab} onReload={load} activeFile={parseTabKey(active)?.kind === "file" ? (parseTabKey(active) as { path: string }).path : undefined} />
      </div>
      {menu ? (
        <div className="menu" style={{ left: menu.x, top: menu.y }} role="menu">
          <div className="menu-label">이 작업공간에서 열기 · {ws.run ? "worktree" : baseName(ws.project)}</div>
          {local ? <>
            <button type="button" className="menu-item" onClick={() => newSession("claude")}><img src="/logos/claude.svg" alt="" width={15} height={15} />Claude 대화형 세션</button>
            <button type="button" className="menu-item" onClick={() => newSession("codex")}><img src="/logos/codex.svg" alt="" width={15} height={15} />Codex 대화형 세션</button>
            <button type="button" className="menu-item" onClick={() => newSession("shell")}><Icon name="terminal" />터미널</button>
          </> : <div className="menu-label">원격 머신에서는 터미널을 아직 열 수 없습니다.</div>}
          <div className="menu-sep" />
          <button type="button" className="menu-item" onClick={() => { setMenu(null); onNewRun({ machine: ws.machine, project: ws.project }); }}><Icon name="flow" />새 흐름 실행 (빠른 · 경쟁 초안 · 토론)</button>
          {run ? <>
            <div className="menu-sep" />
            {runPanels(run).map(([k, label]) => (
              <button key={k} type="button" className="menu-item" onClick={() => { setMenu(null); openTab({ kind: k } as Tab); }}><Icon name={k === "changes" ? "diff" : k === "drafts" ? "drafts" : k === "console" ? "console" : k === "issues" ? "issue" : "doc"} />{label}</button>
            ))}
          </> : null}
        </div>
      ) : null}
    </div>
  );
}

/** 세션 탭: 터미널 + 아래 줄(상태 · 승인 · 메시지 · 끝내기). */
function SessionPane({ s, active, onChanged }: { s: SessionInfo; active: boolean; onChanged: () => void }) {
  const { toast, confirm } = useUi();
  const [status, setStatus] = useState<SessionStatus>(s.status);
  const [msg, setMsg] = useState("");
  useEffect(() => { setStatus(s.status); }, [s.status.state, s.status.reason]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {                                // 보고 있는 동안 '턴 끝(안 봄)'이면 본 것으로
    if (active && status.attention === "done-unseen" && !document.hidden) api("/api/session/seen", { method: "POST", body: { id: s.id } }).then(onChanged).catch(() => {});
  }, [active, status.attention, s.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  const post = async (path: string, body: Record<string, unknown>, ok?: string) => {
    try { await api(path, { method: "POST", body: { id: s.id, ...body } }); if (ok) toast(ok); onChanged(); return true; }
    catch (e) { toast((e as Error).message, true); return false; }
  };
  const live = s.live && status.state !== "ended";
  const shell = s.agent === "shell";
  const send = async () => {
    if (!msg.trim()) return;
    let force = false;
    if (status.state === "blocked") {
      if (!(await confirm("에이전트가 승인을 기다리는 중입니다. 그래도 보내면 질문의 답으로 들어갈 수 있습니다.", { ok: "그래도 보내기", danger: true }))) return;
      force = true;
    }
    if (await post("/api/session/send", { text: msg, force })) setMsg("");
  };
  return (
    <div className="term-wrap">
      {status.state === "blocked" && !shell ? (
        <div className="term-ask"><b>승인을 기다립니다</b><span className="ellipsis" style={{ flex: 1 }}>{status.reason}</span>
          <button type="button" className="btn btn-sm btn-primary" onClick={() => post("/api/session/answer", { approve: true }, "승인을 보냈습니다.")}>승인</button>
          <button type="button" className="btn btn-sm" onClick={() => post("/api/session/answer", { approve: false }, "거절을 보냈습니다.")}>거절</button>
        </div>
      ) : null}
      <Suspense fallback={<div className="empty"><span className="spinner" /></div>}>
        <Term id={s.id} active={active} live={live} fresh={Date.now() - Date.parse(s.created) < 8000} onStatus={setStatus} onEnd={onChanged} />
      </Suspense>
      <div className="term-strip">
        {shell ? <span className="faint">{oneLine(s.cwd, 80)}</span> : <><Shape state={sessionDot({ ...s, status })} /><span>{SESSION_STATE[status.state]}</span></>}
        {live && !shell ? (
          <form className="row" style={{ flex: 1, gap: 6 }} onSubmit={(e) => { e.preventDefault(); send(); }}>
            <input value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="메시지를 붙여넣어 보내기 (터미널에 바로 쳐도 됩니다)" aria-label="세션에 보낼 메시지" />
            <button type="submit" className="btn btn-primary" disabled={!msg.trim()}>보내기</button>
          </form>
        ) : <span className="spacer" />}
        {!live ? <span className="faint">끝남{s.returncode != null ? ` (종료 코드 ${s.returncode})` : ""}</span> : null}
        {live ? <button type="button" className="btn" onClick={async () => {
          if (await confirm(`${shell ? "터미널" : `${s.agent} 세션`}을 끝냅니다.`, { ok: "끝내기", danger: true })) post("/api/session/kill", {});
        }}>끝내기</button> : null}
      </div>
    </div>
  );
}

function FileView({ ws, path }: { ws: WsRef; path: string }) {
  const [f, setF] = useState<{ text: string; binary: boolean; truncated: boolean; size: number } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    setF(null); setErr(null);
    api("/api/ws/file", { query: { project: ws.project, run: ws.run || undefined, path }, machine: ws.machine }).then(setF).catch(setErr);
  }, [ws.machine, ws.project, ws.run, path]);
  if (err) return <div className="page"><ErrorBox error={err} /></div>;
  if (!f) return <div className="empty"><span className="spinner" /></div>;
  return (
    <>
      <div className="file-head"><span className="mono">{path}</span><span className="spacer" /><span className="faint">{(f.size / 1024).toFixed(1)} KB{f.truncated ? " · 앞부분만" : ""}</span></div>
      {f.binary ? <div className="empty">바이너리 파일이라 보여 줄 수 없습니다.</div>
        : <pre className="code-view">{f.text.replace(/\r\n/g, "\n").split("\n").map((ln, i) => <span key={i} className="ln">{ln || " "}</span>)}</pre>}
    </>
  );
}

function DiffView({ ws, path }: { ws: WsRef; path: string }) {
  const [d, setD] = useState<{ text: string; truncated: boolean } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    setD(null); setErr(null);
    api("/api/ws/diff", { query: { project: ws.project, run: ws.run || undefined, path }, machine: ws.machine }).then(setD).catch(setErr);
  }, [ws.machine, ws.project, ws.run, path]);
  if (err) return <div className="page"><ErrorBox error={err} /></div>;
  if (!d) return <div className="empty"><span className="spinner" /></div>;
  return (
    <>
      <div className="file-head"><span className="mono">{path}</span><span className="faint">HEAD 대비</span><span className="spacer" />{d.truncated ? <span className="badge warn">일부만</span> : null}</div>
      <div style={{ padding: 12 }}>{d.text ? <Diff text={d.text} /> : <div className="empty">차이가 없습니다.</div>}</div>
    </>
  );
}
