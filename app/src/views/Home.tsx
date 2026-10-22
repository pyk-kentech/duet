import { FormEvent, useState } from "react";
import { Group, InboxItem } from "../data";
import { hrefSession, SESSION_STATE, SessionInfo, sessionDot } from "../sessions";
import { api } from "../lib/api";
import { baseName, fmtWhen, oneLine } from "../lib/format";
import { ACTIVITY, PHASE, STEP } from "../lib/labels";
import { hrefProject, hrefRun } from "../lib/router";
import { AgentTag, ErrorBox, StateDot, StatusBadge, useUi, Verdict } from "../ui";
import type { NewRunInit } from "./NewRun";

const ORDER = ["blocked", "done-unseen", "working", "unverifiable", "failed"];

export default function Home({ groups, error, inbox, sessions, onNewRun, onChanged }: {
  groups: Group[] | null; error: unknown; inbox: InboxItem[]; sessions: SessionInfo[]; onNewRun: (i?: NewRunInit) => void; onChanged: () => void;
}) {
  const { toast } = useUi();
  const [path, setPath] = useState("");
  const add = async (ev: FormEvent) => {
    ev.preventDefault();
    try {
      const r = await api<{ path: string }>("/api/projects", { method: "POST", body: { path } });
      toast(`추가했습니다: ${r.path}`);
      setPath("");
      onChanged();
    } catch (e) { toast((e as Error).message, true); }
  };
  const byState = ORDER.map((s) => [s, inbox.filter((i) => i.activity.state === s)] as const).filter(([, xs]) => xs.length);
  const asking = sessions.filter((s) => s.status.attention);   // 승인·질문 카드 (36.19)
  const answer = async (s: SessionInfo, approve: boolean) => {
    try {
      await api("/api/session/answer", { method: "POST", body: { id: s.id, approve } });
      toast(approve ? "승인을 보냈습니다." : "거절을 보냈습니다.");
      onChanged();
    } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>받은편지함</h1>
          <div className="muted">나를 기다리는 것부터. 끝난 실행은 열어 보면 여기서 빠집니다.</div>
        </div>
        <span className="spacer" />
        <button className="btn btn-primary" type="button" onClick={() => onNewRun({})}>새 실행</button>
      </div>
      {error ? <ErrorBox error={error} /> : null}

      {asking.length ? (
        <section className="card">
          <div className="section-head" style={{ padding: "10px 14px 0" }}><b>세션</b><span className="faint small">{asking.length}</span></div>
          {asking.map((s) => (
            <div key={s.id} className="inbox-item session-card">
              <StateDot state={sessionDot(s)} />
              <div style={{ minWidth: 0 }}>
                <div className="title ellipsis"><AgentTag name={s.agent} /> {s.status.attention === "blocked" ? SESSION_STATE.blocked : "턴이 끝남 · 안 봄"}</div>
                <div className="reason ellipsis" title={s.status.reason}>{baseName(s.cwd)} · {s.status.reason}</div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                {s.status.attention === "blocked" ? <>
                  <button className="btn btn-sm btn-primary" type="button" onClick={() => answer(s, true)}>승인</button>
                  <button className="btn btn-sm" type="button" onClick={() => answer(s, false)}>거절</button>
                </> : null}
                <a className="btn btn-sm" href={hrefSession(s.id)}>터미널 열기</a>
              </div>
            </div>
          ))}
        </section>
      ) : null}

      <section className="card">
        {byState.length === 0 ? (
          <div className="empty">기다리는 일이 없습니다. 진행 중이거나 새로 끝난 실행이 생기면 여기에 보입니다.</div>
        ) : byState.map(([state, xs]) => (
          <div key={state} className="inbox-group">
            <div className="section-head" style={{ padding: "10px 14px 0" }}>
              <StateDot state={state} /><b>{ACTIVITY[state]}</b><span className="faint small">{xs.length}</span>
            </div>
            {xs.map((it) => (
              <a key={`${it.machine}|${it.project}|${it.run_id}`} className="inbox-item" href={hrefRun(it.machine, it.project, it.run_id)}>
                <StateDot state={it.activity.state} />
                <div style={{ minWidth: 0 }}>
                  <div className="title ellipsis">{oneLine(it.task, 120) || it.run_id}</div>
                  <div className="reason ellipsis">{baseName(it.project)} · {it.activity.reason || ACTIVITY[it.activity.state]}</div>
                </div>
                <span className="faint small nowrap">{fmtWhen(it.updated_at)}</span>
              </a>
            ))}
          </div>
        ))}
      </section>

      {(groups || []).map((g) => {
        const projects = g.projects.filter((p) => !p.bench);
        return (
          <section key={g.id} className="col">
            <div className="section-head">
              <h2>{g.local ? "프로젝트" : `${g.name} 의 프로젝트`}</h2>
              {g.ssh ? <span className="mono faint">{g.ssh}</span> : null}
              {g.error ? <span className="badge bad">연결 안 됨</span> : null}
              <span className="spacer" />
              <button className="btn btn-sm" type="button" onClick={() => onNewRun({ machine: g.id })}>이 머신에서 새 실행</button>
            </div>
            {g.error ? <div className="alert alert-warn"><span>{g.error}</span></div> : null}
            {projects.length === 0 && !g.error ? <div className="card empty">아직 프로젝트가 없습니다. ‘새 실행’으로 시작하세요.</div> : (
              <div className="grid">
                {projects.map((p) => {
                  const l = p.latest;
                  return (
                    <a key={p.path} className="card proj-card" href={hrefProject(g.id, p.path)}>
                      <div className="row">
                        <h3 className="ellipsis">{p.display || p.name}</h3>
                        <span className="spacer" />
                        {p.live ? <StatusBadge status="running" live /> : l ? <StatusBadge status={l.status} stale={l.stale} /> : <span className="badge">기록 없음</span>}
                      </div>
                      <div className="path">{p.path}</div>
                      {l ? <div className="ellipsis small">{oneLine(l.task, 140)}</div> : null}
                      <div className="row faint small" style={{ flexWrap: "wrap" }}>
                        <span>실행 {p.run_count}개</span>
                        {l ? <span>{PHASE[l.phase] || l.phase} · {STEP[l.step] || l.step || "-"}</span> : null}
                        {l?.last_verdict ? <Verdict v={{ status: l.last_verdict }} /> : null}
                        {l ? <span>{fmtWhen(l.updated_at)}</span> : null}
                        {!p.exists ? <span className="badge bad">폴더 없음</span> : null}
                      </div>
                    </a>
                  );
                })}
              </div>
            )}
          </section>
        );
      })}

      <form className="row" onSubmit={add}>
        <input type="text" value={path} onChange={(e) => setPath(e.target.value)} spellCheck={false} autoComplete="off"
               placeholder="기존 작업 폴더를 목록에 추가 (절대 경로)" aria-label="추가할 폴더 경로" />
        <button className="btn" type="submit" disabled={!path.trim()}>추가</button>
      </form>
    </div>
  );
}
