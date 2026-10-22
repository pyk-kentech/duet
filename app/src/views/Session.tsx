import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { baseName } from "../lib/format";
import { hrefProject, hrefRun } from "../lib/router";
import { SESSION_STATE, SessionInfo, SessionStatus } from "../sessions";
import { AgentTag, Modal, StateDot, useUi } from "../ui";

/** 대화형 터미널 세션 화면 (DESIGN.md 36.19). 키 입력은 그대로 넘기고, 출력은 SSE 로 받는다. */
export default function SessionView({ id, sessions, onChanged }: { id: string; sessions: SessionInfo[]; onChanged: () => void }) {
  const { toast, confirm } = useUi();
  const info = sessions.find((s) => s.id === id);
  const box = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const [status, setStatus] = useState<SessionStatus | null>(info?.status || null);
  const [msg, setMsg] = useState("");
  const [why, setWhy] = useState<any>(null);
  const live = info?.live && status?.state !== "ended";

  useEffect(() => { if (info) setStatus(info.status); }, [info?.status.state, info?.status.reason]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!box.current) return;
    const t = new Terminal({ fontFamily: getComputedStyle(document.body).getPropertyValue("--mono") || "monospace",
                             fontSize: 13, cursorBlink: true, scrollback: 5000, convertEol: false,
                             theme: matchMedia("(prefers-color-scheme: dark)").matches || document.documentElement.dataset.theme === "dark"
                               ? undefined : { background: "#1b1d23" } });
    const fit = new FitAddon();
    t.loadAddon(fit);
    t.open(box.current);
    term.current = t;
    let pending = "";
    let timer = 0;
    const flush = () => {                         // 키 입력을 잠깐 모아서 보낸다(붙여넣기·빠른 타자)
      const data = pending;
      pending = "";
      timer = 0;
      if (data) api("/api/session/input", { method: "POST", body: { id, data } }).catch((e) => toast((e as Error).message, true));
    };
    const sub = t.onData((d) => { pending += d; if (!timer) timer = window.setTimeout(flush, 15); });
    let lastSize = "";
    const resize = () => {
      try { fit.fit(); } catch { return; }
      const key = `${t.rows}x${t.cols}`;
      if (key !== lastSize) {
        lastSize = key;
        api("/api/session/resize", { method: "POST", body: { id, rows: t.rows, cols: t.cols } }).catch(() => {});
      }
    };
    const ro = new ResizeObserver(() => resize());
    ro.observe(box.current);
    resize();
    // 출력: SSE (끊기면 offset 으로 다시 붙음)
    let offset = 0;
    let closed = false;
    let es: EventSource | null = null;
    const connect = () => {
      if (closed) return;
      const u = new URL("/api/session/stream", location.origin);
      u.searchParams.set("id", id);
      u.searchParams.set("offset", String(offset));
      es = new EventSource(u.toString(), { withCredentials: true });
      es.addEventListener("out", (ev) => {
        const p = JSON.parse((ev as MessageEvent).data) as { data: string; offset: number; reset: boolean };
        if (p.reset) t.reset();
        t.write(p.data);
        offset = p.offset;
      });
      es.addEventListener("status", (ev) => setStatus(JSON.parse((ev as MessageEvent).data)));
      es.addEventListener("end", () => { es?.close(); onChanged(); });
      es.onerror = () => { es?.close(); if (!closed) window.setTimeout(connect, 1500); };
    };
    connect();
    t.focus();
    api("/api/session/seen", { method: "POST", body: { id } }).catch(() => {});
    return () => { closed = true; es?.close(); sub.dispose(); ro.disconnect(); if (timer) flush(); t.dispose(); term.current = null; };
  }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {                                // 보고 있는 동안 '턴 끝(안 봄)'이 생기면 바로 본 것으로
    if (status?.attention === "done-unseen" && !document.hidden) api("/api/session/seen", { method: "POST", body: { id } }).then(onChanged).catch(() => {});
  }, [status?.attention, id]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!info) return <div className="page"><div className="card empty">세션을 찾을 수 없습니다. 목록이 아직 안 불러졌거나 닫힌 세션입니다.</div></div>;

  const post = async (path: string, body: Record<string, unknown>, ok?: string) => {
    try { await api(path, { method: "POST", body: { id, ...body } }); if (ok) toast(ok); onChanged(); return true; }
    catch (e) { toast((e as Error).message, true); return false; }
  };
  const send = async () => {
    if (!msg.trim()) return;
    let force = false;
    if (status?.state === "blocked") {
      if (!(await confirm("에이전트가 승인을 기다리는 중입니다. 그래도 메시지를 보내면 질문에 대한 답으로 들어갈 수 있습니다.", { ok: "그래도 보내기", danger: true }))) return;
      force = true;
    }
    if (await post("/api/session/send", { text: msg, force })) setMsg("");
    term.current?.focus();
  };
  const kill = async () => {
    if (!(await confirm(`${info.agent} 세션을 끝냅니다. 지금 하던 일은 멈춥니다.`, { ok: "끝내기", danger: true }))) return;
    post("/api/session/kill", {});
  };
  const explain = async () => {
    try { setWhy(await api(`/api/session/explain`, { query: { id } })); } catch (e) { toast((e as Error).message, true); }
  };
  const st = status || info.status;
  return (
    <div className="page session-page">
      <div className="crumbs">
        <a href="#/">받은편지함</a><span className="sep">/</span>
        <a href={hrefProject("local", info.project)}>{baseName(info.project)}</a><span className="sep">/</span>
        {info.run_id ? <><a href={hrefRun("local", info.project, info.run_id)} className="mono">{info.run_id}</a><span className="sep">/</span></> : null}
        <span>세션</span>
      </div>
      <section className="card card-pad row" style={{ flexWrap: "wrap", gap: 10 }}>
        <StateDot state={st.state === "blocked" ? "blocked" : st.state === "working" ? "working" : st.state === "ended" ? "idle" : "done-unseen"} />
        <AgentTag name={info.agent} />
        <b>{SESSION_STATE[st.state]}</b>
        <span className="muted small ellipsis" style={{ maxWidth: 420 }} title={st.reason}>{st.reason}</span>
        <button className="btn btn-sm" type="button" onClick={explain}>왜 이 상태?</button>
        <span className="spacer" />
        <span className="mono faint small ellipsis" title={info.cwd} style={{ maxWidth: 360 }}>{info.cwd}</span>
        {st.state === "blocked" ? (
          <>
            <button className="btn btn-sm btn-primary" type="button" onClick={() => post("/api/session/answer", { approve: true }, "승인을 보냈습니다.")}>승인</button>
            <button className="btn btn-sm" type="button" onClick={() => post("/api/session/answer", { approve: false }, "거절을 보냈습니다.")}>거절</button>
          </>
        ) : null}
        {live ? <button className="btn btn-sm btn-danger" type="button" onClick={kill}>끝내기</button>
          : <button className="btn btn-sm" type="button" onClick={async () => { if (await post("/api/session/close", {})) location.hash = hrefProject("local", info.project); }}>목록에서 닫기</button>}
      </section>
      <div className="term-box" ref={box} onClick={() => term.current?.focus()} />
      {live ? (
        <form className="row" style={{ gap: 8 }} onSubmit={(e) => { e.preventDefault(); send(); }}>
          <textarea rows={2} value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="메시지 (붙여넣기로 보내고 Enter) — 터미널에 바로 쳐도 됩니다"
                    onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }} style={{ flex: 1, resize: "vertical" }} />
          <button className="btn btn-primary" type="submit" disabled={!msg.trim()}>보내기</button>
        </form>
      ) : <div className="muted small">세션이 끝났습니다{info.returncode != null ? ` (종료 코드 ${info.returncode})` : ""}. 위는 남은 출력 기록입니다.</div>}
      {why ? (
        <Modal label="왜 이 상태?" onClose={() => setWhy(null)} wide>
          <div className="dialog-head"><b>왜 이 상태?</b><span className="spacer" /><button className="btn btn-sm" type="button" onClick={() => setWhy(null)}>닫기</button></div>
          <div className="col card-pad" style={{ gap: 8 }}>
            <div><b>{SESSION_STATE[why.status.state]}</b> · 근거: {({ hook: "훅", screen: "화면 규칙", action: "화면에서 한 일", output: "출력 여부", process: "프로세스", "hook+screen": "훅 + 화면" } as Record<string, string>)[why.status.source] || why.status.source} · {why.status.reason}</div>
            {why.hook ? <div className="small">마지막 훅: <span className="mono">{why.hook.event}</span> ({String(why.hook.ts).slice(11, 19)}) → {why.hook.reason}</div> : <div className="small faint">받은 훅 없음</div>}
            {why.rule ? <div className="small">맞은 화면 규칙: <span className="mono">{why.rule.id}</span> ({why.rule.source}) <span className="mono faint">/{why.rule.regex}/</span></div> : <div className="small faint">맞은 화면 규칙 없음</div>}
            <div className="small faint">규칙: {why.rules.join(", ")} · 고치려면 ~/.tenure/screen_rules.toml</div>
            <pre className="diff" style={{ maxHeight: 260, padding: 10 }}>{why.tail || "(화면 끝부분 없음)"}</pre>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
