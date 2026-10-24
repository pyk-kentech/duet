// 환경·로그인: tenure 가 쓰는 도구의 설치·로그인 상태(doctor)를 보고, 없으면 여기서 설치·로그인한다.
// 설치·로그인은 서버의 '터미널 작업'으로 돌고, 출력은 /api/term 을 offset 으로 이어 받아 보여준다.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Group } from "../data";
import { api, LOCAL } from "../lib/api";
import { fmtWhen } from "../lib/format";
import { ErrorBox, useUi } from "../ui";
import { Help, ProbeInfo } from "./Settings";
import "./setup.css";

interface ActionDef { title: string; interactive: boolean; note: string; command: string; local_command: string | null; local_available: boolean }
interface Check {
  id: string; name: string; status: "ok" | "warn" | "missing" | "error" | string;
  version: string; path: string; detail: string; actions: string[]; extra: Record<string, any>;
}
interface Doctor { checks: Check[]; ready: boolean }
interface TermSnap {
  id: string; title: string; machine: string; note: string; mode: "pty" | "pipe" | "console" | string;
  started_at: string; running: boolean; returncode: number | null; text: string; offset: number; urls: string[];
}
interface TermSummary { id: string; title: string; machine: string; running: boolean; returncode: number | null; started_at: string }

const CHECK_STATUS: Record<string, string> = { ok: "정상", warn: "확인 필요", missing: "없음", error: "오류" };
const CHECK_TONE: Record<string, string> = { ok: "ok", warn: "warn", missing: "bad", error: "bad" };
const TIPS: Record<string, string> = {
  "tool.tenure": "tenure 자체와, 그걸 돌리는 Python 입니다.",
  "tool.git": "코드 변경 이력을 저장하는 프로그램입니다. tenure 가 라운드마다 저장(커밋)합니다. 꼭 필요합니다.",
  "tool.curl": "인터넷에서 설치 파일을 받는 프로그램입니다. Claude·Codex·uv 를 설치할 때 필요합니다.",
  "tool.uv": "Python 도구 설치 프로그램입니다. 다른 컴퓨터에 Python 을 설치할 때 씁니다. 없어도 됩니다.",
  "tool.claude": "Claude 를 터미널에서 쓰는 공식 프로그램입니다. Claude 구독 계정으로 로그인해야 합니다.",
  "tool.codex": "ChatGPT(Codex)를 터미널에서 쓰는 공식 프로그램입니다. ChatGPT 계정으로 로그인해야 합니다.",
  "tool.api_keys": "이 변수가 있으면 Claude·Codex 가 구독 대신 API 요금으로 계산할 수 있습니다. tenure 는 기본으로 빼고 넘깁니다.",
  "tool.sandbox": "Claude 구현자의 명령을 OS 샌드박스에서 돌리는 설정입니다. Linux 는 bubblewrap·socat 이 필요합니다.",
  recheck: "설치·로그인 상태를 다시 확인합니다.",
  term_input: "로그인 코드나 질문의 답을 여기에 붙여 넣고 Enter 를 누르세요.",
  term_secret: "비밀번호처럼 화면에 보이면 안 되는 값을 입력할 때 켜세요.",
  term_kill: "진행 중인 설치·로그인을 멈춥니다.",
  deploy: "이 컴퓨터의 tenure 를 원격 머신에 복사합니다. tenure 를 업데이트한 뒤에도 누르세요.",
  "remote.ssh": "이 컴퓨터에서 원격 머신으로 접속되는지 봅니다. 비밀번호 없이 접속되게 미리 ssh-copy-id 를 해 두어야 합니다.",
  "remote.python": "원격 머신에 Python 3.11 이상이 있는지 봅니다. tenure 를 돌리는 데 필요합니다.",
  "remote.tenure": "원격 머신에 tenure 가 복사되어 있고 최신인지 봅니다.",
};
const TERM_MAX_CHARS = 400_000;

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function SetupView({ machine, groups }: { machine: string; groups: Group[] | null }) {
  const { toast, confirm } = useUi();
  const m = machine || LOCAL;
  const local = m === LOCAL;
  const [actions, setActions] = useState<Record<string, ActionDef>>({});
  const [remote, setRemote] = useState<ProbeInfo | null>(null);
  const [doctor, setDoctor] = useState<Doctor | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [term, setTerm] = useState<{ id: string; title: string; machine: string; note: string } | null>(null);
  const [recent, setRecent] = useState<TermSummary[]>([]);
  const [deploying, setDeploying] = useState(false);
  const req = useRef(0);
  const termSlot = useRef<HTMLDivElement>(null);

  const machineName = useCallback((id: string) => {
    if (!id || id === LOCAL) return "이 머신";
    return (groups || []).find((g) => g.id === id)?.name || id;
  }, [groups]);

  const loadTerms = useCallback(async () => {
    try {
      const r = await api<{ terms: TermSummary[] }>("/api/terms");
      setRecent(r.terms || []);
    } catch { /* 목록은 없어도 된다 */ }
  }, []);

  const load = useCallback(async () => {
    const id = ++req.current;
    setLoading(true);
    setError(null);
    try {
      if (!local) {
        const info = await api<ProbeInfo>("/api/machines/probe", { method: "POST", machine: m });
        if (id !== req.current) return;
        setRemote(info);
        if (!(info.reachable && info.deployed && info.up_to_date)) { setDoctor(null); return; }
      } else {
        setRemote(null);
      }
      const d = await api<Doctor>("/api/doctor", { machine: m });
      if (id !== req.current) return;
      setDoctor(d);
    } catch (e) {
      if (id === req.current) setError(e);
    } finally {
      if (id === req.current) setLoading(false);
    }
  }, [m, local]);

  useEffect(() => {
    setRemote(null);
    setDoctor(null);
    load();
    loadTerms();
  }, [load, loadTerms]);
  useEffect(() => {
    api<{ actions: Record<string, ActionDef> }>("/api/setup/actions").then((a) => setActions(a.actions || {})).catch(() => {});
  }, []);

  // 이 머신이면 이 OS 의 명령(Windows 는 PowerShell), 원격이면 POSIX 셸 명령 (DESIGN.md 27.5)
  const actCommand = (a: ActionDef | undefined): string => {
    if (!a) return "";
    return local ? (a.local_available === false ? "(이 OS 에서는 직접 설치)" : a.local_command || "") : a.command;
  };

  const runAction = async (id: string) => {
    const a = actions[id];
    if (id.startsWith("install") && !(await confirm(`${a?.title || id}\n\n다음 명령을 실행합니다:\n${actCommand(a)}`, { ok: "실행" }))) return;
    try {
      const job = await api<TermSnap>("/api/setup/action", { method: "POST", body: { action: id }, machine: m });
      setTerm({ id: job.id, title: job.title, machine: job.machine, note: job.note });
      loadTerms();
      window.setTimeout(() => termSlot.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e) { toast(errMsg(e), true); }
  };

  const deploy = async () => {
    setDeploying(true);
    try {
      const r = await api<{ version: string }>("/api/machines/deploy", { method: "POST", machine: m });
      toast(`배포했습니다: ${r.version}`);
      await load();
    } catch (e) { toast(errMsg(e), true); }
    setDeploying(false);
  };

  const actBtn = (id: string, primary = false) => {
    const a = actions[id];
    const tip = a ? [a.note, `실행 명령: ${actCommand(a)}`].filter(Boolean).join(" · ") : undefined;
    const unavailable = local && a?.local_available === false;
    return (
      <button key={id} className={`btn btn-sm${primary ? " btn-primary" : ""}`} type="button" title={tip} disabled={unavailable}
              onClick={() => runAction(id)}>{a ? a.title : id}</button>
    );
  };

  const tabs = groups && groups.length ? groups : [{ id: LOCAL, name: "이 머신", local: true } as Group];
  const others = recent.filter((t) => t.id !== term?.id && t.machine === m);

  return (
    <div className="page setup-page">
      <div className="page-head">
        <div>
          <h1>환경·로그인</h1>
          <div className="muted">tenure 가 쓰는 도구의 설치와 로그인 상태를 확인하고, 없으면 여기서 설치·로그인합니다.</div>
        </div>
        <span className="spacer" />
        <button className="btn" type="button" title={TIPS.recheck} disabled={loading} onClick={() => { load(); loadTerms(); }}>
          {loading ? <span className="spinner" /> : null}다시 점검</button>
      </div>

      {tabs.length > 1 ? (
        <nav className="tabs" aria-label="머신">
          {tabs.map((g) => (
            <a key={g.id} href={`#/setup?m=${encodeURIComponent(g.id)}`} className={g.id === m ? "active" : undefined}
               aria-current={g.id === m ? "page" : undefined}>{g.local ? "이 머신" : g.name}</a>
          ))}
        </nav>
      ) : null}

      {error ? <ErrorBox error={error} /> : null}

      {!local && remote ? (
        <div className="card table-scroll">
          <table className="checks-table">
            <thead><tr><th>원격 머신: {machineName(m)}</th><th>상태</th><th>내용</th><th></th></tr></thead>
            <tbody>
              <tr>
                <td><b>SSH 연결</b><Help text={TIPS["remote.ssh"]} /></td>
                <td><StatusBadge status={remote.reachable ? "ok" : "error"} /></td>
                <td>{remote.reachable ? (remote.uname || "연결됨") : remote.error}
                  {remote.hint ? <div className="mono small">{remote.hint}</div> : null}</td>
                <td />
              </tr>
              {remote.reachable ? (
                <>
                  <tr>
                    <td><b>Python 3.11+</b><Help text={TIPS["remote.python"]} /></td>
                    <td><StatusBadge status={remote.python ? "ok" : "missing"} /></td>
                    <td>{remote.python ? <span className="mono small">{remote.python}</span> : "찾지 못했습니다. uv 를 설치한 뒤 Python 3.12 를 설치하세요."}</td>
                    <td>{remote.python ? null : <div className="acts">{actBtn("install_uv")}{actBtn("install_python")}</div>}</td>
                  </tr>
                  <tr>
                    <td><b>tenure 배포</b><Help text={TIPS["remote.tenure"]} /></td>
                    <td><StatusBadge status={remote.deployed ? (remote.up_to_date ? "ok" : "warn") : "missing"} /></td>
                    <td>{remote.deployed
                      ? (remote.up_to_date ? `최신 (${remote.remote_hash})` : `업데이트 필요 (원격 ${remote.remote_hash} · 이 머신 ${remote.local_hash})`)
                      : "아직 배포하지 않았습니다."}</td>
                    <td>{remote.python ? (
                      <div className="acts">
                        <button className="btn btn-sm btn-primary" type="button" title={TIPS.deploy} disabled={deploying} onClick={deploy}>
                          {deploying ? "배포 중…" : remote.deployed ? "업데이트" : "배포"}</button>
                      </div>) : null}</td>
                  </tr>
                </>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}

      {!doctor && loading ? <div className="card empty"><span className="spinner" /> 점검 중…</div> : null}
      {!local && remote && !(remote.reachable && remote.deployed && remote.up_to_date) && !loading ? (
        <div className="alert alert-info"><span>원격 머신에 연결되고 최신 tenure 가 배포되면 그 머신의 도구 점검이 여기에 나옵니다.</span></div>
      ) : null}

      {doctor ? (
        <>
          <div className={`alert ${doctor.ready ? "alert-info" : "alert-warn"}`}>
            <b>{doctor.ready ? "준비됨" : "준비 안 됨"}</b>
            <span>{doctor.ready ? "실제 Claude·Codex 로 실행할 수 있습니다." : "git, Claude Code, Codex CLI 가 모두 설치·로그인되어야 실제 실행이 됩니다."}</span>
          </div>
          <div className={`card table-scroll${loading ? " is-loading" : ""}`}>
            <table className="checks-table">
              <thead><tr><th>도구</th><th>상태</th><th>버전·내용</th><th></th></tr></thead>
              <tbody>
                {doctor.checks.map((c) => (
                  <tr key={c.id}>
                    <td><b>{c.name}</b><Help text={TIPS[`tool.${c.id}`]} />{c.path ? <div className="ver">{c.path}</div> : null}</td>
                    <td><StatusBadge status={c.status} /></td>
                    <td>
                      {c.version ? <div className="ver">{c.version.split(" (")[0]}</div> : null}
                      <div className="small">{c.detail}</div>
                      {c.extra?.account ? <div className="small faint">계정 {c.extra.account}</div> : null}
                    </td>
                    <td><div className="acts">{c.actions.map((a) => actBtn(a, c.status !== "ok" || a.startsWith("login")))}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      <div ref={termSlot}>
        {term ? <TermPanel key={term.id} job={term} machineName={machineName} onEnded={() => { load(); loadTerms(); }} /> : null}
      </div>

      {others.length ? (
        <section className="card">
          <div className="section-head" style={{ padding: "10px 14px 0" }}><h3>최근 설치·로그인 작업</h3>
            <span className="faint small">UI 서버가 켜져 있는 동안 남습니다</span></div>
          <table className="list term-recent">
            <tbody>
              {others.map((t) => (
                <tr key={t.id} onClick={() => setTerm({ id: t.id, title: t.title, machine: t.machine, note: "" })}>
                  <td><b>{t.title}</b></td>
                  <td>{t.running ? <span className="badge info"><span className="spinner" style={{ width: 10, height: 10 }} />실행 중</span>
                    : t.returncode === 0 ? <span className="badge ok">끝남</span> : <span className="badge bad">종료 코드 {t.returncode}</span>}</td>
                  <td className="faint small nowrap">{fmtWhen(t.started_at)}</td>
                  <td style={{ textAlign: "right" }}><button className="btn btn-sm" type="button">출력 보기</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${CHECK_TONE[status] || ""}`}>{CHECK_STATUS[status] || status}</span>;
}

// ---------------------------------------------------------------- 터미널 작업 출력
function TermPanel({ job, machineName, onEnded }: {
  job: { id: string; title: string; machine: string; note: string }; machineName: (id: string) => string; onEnded: () => void;
}) {
  const { toast } = useUi();
  const [text, setText] = useState("");
  const [snap, setSnap] = useState<TermSnap | null>(null);
  const [input, setInput] = useState("");
  const [secret, setSecret] = useState(false);
  const [lost, setLost] = useState<string | null>(null);
  const pre = useRef<HTMLPreElement>(null);
  const ended = useRef(onEnded);
  ended.current = onEnded;

  useEffect(() => {
    let alive = true;
    let timer = 0;
    let offset = 0;
    let wasRunning: boolean | null = null;
    const tick = async () => {
      if (!alive) return;
      let t: TermSnap;
      try {
        t = await api<TermSnap>("/api/term", { query: { id: job.id, offset } });
      } catch (e) {
        if (!alive) return;
        setLost(errMsg(e));
        return;
      }
      if (!alive) return;
      offset = t.offset;
      if (t.text) setText((x) => { const y = x + t.text; return y.length > TERM_MAX_CHARS ? y.slice(-TERM_MAX_CHARS) : y; });
      setSnap({ ...t, text: "" });
      if (t.running) {
        wasRunning = true;
        timer = window.setTimeout(tick, 700);
        return;
      }
      if (wasRunning) ended.current();   // 이 화면에서 지켜보던 작업이 끝났으면 상태를 다시 점검한다
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [job.id]);

  useEffect(() => {
    const el = pre.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [text]);

  const send = async () => {
    if (!input) return;
    try {
      await api("/api/term/input", { method: "POST", body: { id: job.id, text: input } });
      setInput("");
    } catch (e) { toast(errMsg(e), true); }
  };
  const kill = async () => {
    try { await api("/api/term/kill", { method: "POST", body: { id: job.id } }); }
    catch (e) { toast(errMsg(e), true); }
  };

  const running = snap ? snap.running : !lost;
  const note = snap?.note || job.note;
  const links = (snap?.urls || []).filter((u) => /^https?:\/\//.test(u));
  const consoleMode = snap?.mode === "console";
  return (
    <section className="card term" aria-label={`터미널: ${job.title}`}>
      <div className="term-head">
        <b>{job.title}</b>
        {running ? <span className="badge info"><span className="spinner" style={{ width: 10, height: 10 }} />실행 중</span>
          : lost ? <span className="badge warn">연결 끊김</span>
          : snap?.returncode === 0 ? <span className="badge ok">끝남</span>
          : <span className="badge bad">종료 코드 {snap?.returncode ?? "?"}</span>}
        {job.machine && job.machine !== LOCAL ? <span className="muted small">{machineName(job.machine)}</span> : null}
        <span className="spacer" />
        {note ? <span className="muted small term-note">{note}</span> : null}
      </div>
      <pre ref={pre} className="term-out" aria-live="polite">{text || (running ? "출력을 기다리는 중…" : "")}</pre>
      {lost ? <div className="alert alert-warn small" style={{ margin: "0 14px 10px" }}><span>출력을 더 받지 못했습니다: {lost}</span></div> : null}
      {links.length ? (
        <div className="term-links">
          <span className="muted small">링크:</span>
          {links.map((u) => <a key={u} href={u} target="_blank" rel="noopener noreferrer">{u}</a>)}
        </div>
      ) : null}
      {running && !lost ? (
        <form className="term-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
          {consoleMode ? (
            <span className="muted small">새 콘솔 창에서 실행 중입니다. 그 창에 직접 입력하세요.</span>
          ) : (
            <>
              <input type={secret ? "password" : "text"} value={input} onChange={(e) => setInput(e.target.value)} placeholder="코드나 답을 입력하고 Enter"
                     autoComplete="off" spellCheck={false} aria-label="터미널 입력" title={TIPS.term_input} />
              <span className="term-secret">
                <label><input type="checkbox" checked={secret} onChange={(e) => setSecret(e.target.checked)} />비밀번호(숨김)</label>
                <Help text={TIPS.term_secret} />
              </span>
              <button className="btn btn-sm" type="submit" disabled={!input}>보내기</button>
            </>
          )}
          <span className="spacer" />
          <button className="btn btn-sm btn-danger" type="button" title={TIPS.term_kill} onClick={kill}>중지</button>
        </form>
      ) : null}
    </section>
  );
}
