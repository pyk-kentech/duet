import { FormEvent, useMemo, useState } from "react";
import type { Group } from "../data";
import { api, LOCAL } from "../lib/api";
import { baseName, fmtWhen } from "../lib/format";
import { hrefProject } from "../lib/router";
import { ErrorBox, useUi } from "../ui";
import { itemDoing, itemTitle, WorkFolder, WorkItem } from "../works";
import type { NewRunInit } from "./NewRun";
import { itemHref, Shape, STATE_LABEL } from "./WorkList";

/** 오늘 (36.21): 아무것도 고르지 않았을 때. 바로 시작 · 나를 기다리는 것 · 최근 끝난 것 · 프로젝트. */
export default function Home({ groups, error, folders, onNewRun, onChanged }: {
  groups: Group[] | null; error: unknown; folders: WorkFolder[]; onNewRun: (i?: NewRunInit) => void; onChanged: () => void;
}) {
  const { toast } = useUi();
  const [task, setTask] = useState("");
  const local = (groups || []).find((g) => g.local);
  const projects = (local?.projects || []).filter((p) => p.exists && !p.bench);
  const [project, setProject] = useState("");
  const [path, setPath] = useState("");
  const all = useMemo(() => folders.flatMap((f) => f.items), [folders]);
  const attention = all.filter((i) => i.rank >= 4).slice(0, 8);
  const working = all.filter((i) => i.state === "working").slice(0, 6);
  const recent = all.filter((i) => i.rank < 4 && i.state !== "working")
    .sort((a, b) => b.updated.localeCompare(a.updated)).slice(0, 6);

  const start = (ev: FormEvent) => {
    ev.preventDefault();
    onNewRun({ task: task.trim(), project: project || undefined, machine: LOCAL });
    setTask("");
  };
  const add = async (ev: FormEvent) => {
    ev.preventDefault();
    try {
      const r = await api<{ path: string }>("/api/projects", { method: "POST", body: { path } });
      toast(`추가했습니다: ${r.path}`);
      setPath("");
      onChanged();
    } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <div className="page today">
      {error ? <ErrorBox error={error} /> : null}
      <form className="composer" onSubmit={start}>
        <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={3} placeholder="무엇을 만들거나 고칠까요? 과제를 적고 시작하면 새 작업 창이 채워져 열립니다."
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) start(e); }} aria-label="과제" />
        <div className="row">
          <select value={project} onChange={(e) => setProject(e.target.value)} aria-label="폴더">
            <option value="">새 폴더 또는 고르기…</option>
            {projects.map((p) => <option key={p.path} value={p.path}>{p.display || p.name}</option>)}
          </select>
          <span className="faint small">Ctrl+Enter</span>
          <span className="spacer" />
          <button className="btn btn-primary" type="submit">시작</button>
        </div>
      </form>

      {attention.length ? (
        <Section title="나를 기다림 · 안 봄" items={attention} />
      ) : null}
      {working.length ? <Section title="진행 중" items={working} /> : null}
      {!attention.length && !working.length ? (
        <div className="calm">기다리는 일이 없습니다. 진행 중이거나 새로 끝난 작업이 생기면 왼쪽 목록과 여기에 보입니다.</div>
      ) : null}
      {recent.length ? <Section title="최근 끝난 작업" items={recent} /> : null}

      <section className="col" style={{ gap: 8 }}>
        <div className="sec-title">프로젝트</div>
        <div className="proj-chips">
          {projects.map((p) => (
            <a key={p.path} className="proj-chip" href={hrefProject(LOCAL, p.path)} title={p.path}>
              <Shape state={p.live ? "working" : p.latest?.activity?.state || "idle"} />
              <span className="ellipsis">{p.display || p.name || baseName(p.path)}</span>
              <span className="faint small">{p.run_count}</span>
            </a>
          ))}
          {(groups || []).filter((g) => !g.local).map((g) => g.projects.filter((p) => !p.bench).map((p) => (
            <a key={`${g.id}|${p.path}`} className="proj-chip" href={hrefProject(g.id, p.path)} title={`${g.name} · ${p.path}`}>
              <Shape state={p.latest?.activity?.state || "idle"} /><span className="ellipsis">{p.name}</span><span className="machine">{g.name}</span>
            </a>
          )))}
        </div>
        <form className="row" onSubmit={add}>
          <input type="text" value={path} onChange={(e) => setPath(e.target.value)} spellCheck={false} autoComplete="off"
                 placeholder="기존 폴더를 목록에 추가 (절대 경로)" aria-label="추가할 폴더 경로" />
          <button className="btn" type="submit" disabled={!path.trim()}>추가</button>
        </form>
      </section>
    </div>
  );
}

function Section({ title, items }: { title: string; items: WorkItem[] }) {
  return (
    <section className="col" style={{ gap: 6 }}>
      <div className="sec-title">{title}</div>
      <div className="card list-card">
        {items.map((it) => (
          <a key={it.key} className="today-row" href={itemHref(it)}>
            <Shape state={it.state} />
            <span className="wrow-main">
              <span className="wrow-t1">{itemTitle(it)}</span>
              <span className="wrow-t2">{baseName(it.project)} · {it.state === "blocked" || it.state === "done-unseen" ? STATE_LABEL[it.state] + " · " : ""}{itemDoing(it)}</span>
            </span>
            <span className="wrow-when">{fmtWhen(it.updated)}</span>
          </a>
        ))}
      </div>
    </section>
  );
}
