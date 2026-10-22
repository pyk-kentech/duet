import { useState } from "react";
import { RunSummary } from "../data";
import { api } from "../lib/api";
import { baseName, fmtDur, fmtWhen, oneLine } from "../lib/format";
import { Markdown } from "../lib/markdown";
import { PHASE, STEP } from "../lib/labels";
import { hrefProject, hrefRun } from "../lib/router";
import { ErrorBox, StateDot, StatusBadge, usePoll, useUi, Verdict } from "../ui";
import { TREE_STATUS } from "./Merge";
import type { NewRunInit } from "./NewRun";

interface RunsData {
  project: string; live: { pid: number; run_id: string; count?: number } | null; runs: RunSummary[];
  has_design: boolean; defaults: Record<string, any>;
}

export default function ProjectView({ route, onNewRun, onChanged }: {
  route: { machine: string; project: string; tab: string }; onNewRun: (i: NewRunInit) => void; onChanged: () => void;
}) {
  const { toast, confirm } = useUi();
  const [data, setData] = useState<RunsData | null>(null);
  const [design, setDesign] = useState<string | null | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const m = route.machine;
  usePoll(async () => {
    try {
      const d = await api<RunsData>("/api/runs", { query: { project: route.project }, machine: m });
      setData(d);
      setError(null);
      if (route.tab === "design" && design === undefined) {
        const r = await api<{ text: string | null }>("/api/design", { query: { project: route.project }, machine: m });
        setDesign(r.text);
      }
    } catch (e) { setError(e); }
  }, data?.live ? 2500 : 6000, [route.project, route.tab, m]);

  const remove = async () => {
    if (!(await confirm(`목록에서만 제거합니다. 파일은 지우지 않습니다.\n\n${route.project}`, { ok: "목록에서 제거" }))) return;
    try {
      await api("/api/projects", { method: "DELETE", query: { project: route.project }, machine: m });
      onChanged();
      location.hash = "#/";
    } catch (e) { toast((e as Error).message, true); }
  };
  const stop = async () => {
    if (!(await confirm("진행 중인 실행을 멈춥니다. 지금 하던 호출은 끊기고, 나중에 이어하기로 계속할 수 있습니다.", { ok: "중지", danger: true }))) return;
    try {
      await api("/api/actions/stop", { method: "POST", body: { project: route.project, run: data?.live?.run_id }, machine: m });
      toast("중지 요청을 보냈습니다.");
    } catch (e) { toast((e as Error).message, true); }
  };

  const live = data?.live;
  return (
    <div className="page">
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="crumbs"><a href="#/">받은편지함</a><span className="sep">/</span><span>{baseName(route.project)}</span></div>
          <h1>{baseName(route.project)}</h1>
          <div className="sub">{route.project}</div>
        </div>
        <span className="spacer" />
        <div className="row">
          {live ? <button className="btn btn-danger" type="button" onClick={stop}>중지</button> : null}
          <button className="btn" type="button" onClick={remove}>목록에서 제거</button>
          <button className="btn btn-primary" type="button" title={live ? "git 저장소면 작업마다 worktree 를 따로 만들어 동시에 돌릴 수 있습니다" : undefined}
                  onClick={() => onNewRun({ machine: m, project: route.project, defaults: data?.defaults, hasDesign: data?.has_design })}>새 실행</button>
        </div>
      </div>
      {error ? <ErrorBox error={error} /> : null}
      {live ? (
        <div className="alert alert-info"><span className="spinner" />
          <span>실행 중: <a href={hrefRun(m, route.project, live.run_id)}>{live.run_id}</a> · pid {live.pid}{live.count && live.count > 1 ? ` 외 ${live.count - 1}개` : ""}</span></div>
      ) : null}
      <nav className="tabs">
        <a href={hrefProject(m, route.project, "runs")} className={route.tab === "runs" ? "active" : undefined}>실행 기록<span className="count">{data?.runs.length ?? ""}</span></a>
        <a href={hrefProject(m, route.project, "design")} className={route.tab === "design" ? "active" : undefined}>설계 문서</a>
      </nav>
      {route.tab === "design" ? (
        <div className="card card-pad">{design ? <div className="md"><Markdown text={design} /></div> : <div className="empty">DESIGN.md 가 아직 없습니다.</div>}</div>
      ) : !data ? null : data.runs.length === 0 ? (
        <div className="card empty"><h3>실행 기록이 없습니다</h3><p>‘새 실행’으로 시작하세요.</p></div>
      ) : (
        <div className="card table-scroll">
          <table className="list">
            <thead><tr><th></th><th>실행</th><th>상태</th><th>브랜치</th><th>과제</th><th>진행</th><th>판정</th><th>호출</th><th>갱신</th></tr></thead>
            <tbody>
              {[...data.runs].map((run) => (
                <tr key={run.run_id} onClick={() => { location.hash = hrefRun(m, route.project, run.run_id); }}>
                  <td><StateDot state={run.live ? "working" : run.activity?.state} /></td>
                  <td className="mono nowrap"><a href={hrefRun(m, route.project, run.run_id)} onClick={(e) => e.stopPropagation()}>{run.run_id}</a></td>
                  <td><StatusBadge status={run.status} live={run.live} stale={run.stale} /></td>
                  <td className="nowrap small">{run.worktree ? <span title={run.worktree.branch}><span className={`badge ${TREE_STATUS[run.worktree.status].cls}`}>{TREE_STATUS[run.worktree.status].text}</span></span> : <span className="faint">-</span>}</td>
                  <td style={{ maxWidth: 380 }}><div className="ellipsis" title={run.task}>{oneLine(run.task, 90)}</div></td>
                  <td className="nowrap small">{PHASE[run.phase] || run.phase || "-"} · {STEP[run.step] || run.step || "-"}{run.round ? ` · ${run.round}회차` : ""}</td>
                  <td><Verdict v={run.last_verdict ? { status: run.last_verdict } : null} /></td>
                  <td className="nowrap small">{run.calls}회 · {fmtDur(run.total_sec)}</td>
                  <td className="nowrap small faint">{fmtWhen(run.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
