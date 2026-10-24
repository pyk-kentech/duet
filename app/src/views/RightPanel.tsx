import { useCallback, useEffect, useState } from "react";
import { Icon } from "../icons";
import { api, LOCAL } from "../lib/api";
import { Tab, WsRef } from "../ws";
import AgentConfigView from "./AgentConfig";
import { RunData, RunMergePanel } from "./Run";

/** 오른쪽 판 (오르카 RightSidebar, 36.22): 파일 · 변경 · 합치기/커밋 · 에이전트 설정. 오른쪽 끝의 아이콘 줄로 고른다. */
export type RpKind = "files" | "changes" | "git" | "agents";
const ACTS: [RpKind, string, string][] = [["files", "files", "파일"], ["changes", "diff", "변경"], ["git", "git", "합치기 · 커밋"], ["agents", "robot", "에이전트 설정"]];

interface Entry { name: string; dir: boolean; size: number; heavy: boolean }
interface Status { repo: boolean; branch: string | null; files: { path: string; kind: string; add: number; del: number }[]; commits?: { short: string; subject: string; when: string }[] }

export default function RightPanel({ ws, run, kind, open, onKind, onToggle, onOpen, onReload, activeFile }: {
  ws: WsRef; run: RunData | null; kind: RpKind; open: boolean; onKind: (k: RpKind) => void; onToggle: () => void;
  onOpen: (t: Tab) => void; onReload: () => void; activeFile?: string;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const q = { project: ws.project, run: ws.run || undefined };
  const loadStatus = useCallback(() => {
    api<Status>("/api/ws/status", { query: q, machine: ws.machine }).then(setStatus).catch(() => setStatus(null));
  }, [ws.machine, ws.project, ws.run]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setStatus(null);
    if (!open || (kind !== "changes" && kind !== "git")) return;
    loadStatus();
    const id = window.setInterval(() => { if (!document.hidden) loadStatus(); }, 5000);
    return () => window.clearInterval(id);
  }, [open, kind, loadStatus]);
  const nChanges = status?.files.length || 0;
  const title = ACTS.find((a) => a[0] === kind)?.[2] || "";
  return (
    <aside className={`rp${open ? "" : " collapsed"}`} aria-label="작업공간 판">
      <div className="rp-main">
        <div className="rp-head"><b>{title}</b><span className="spacer" />
          {kind === "changes" || kind === "git" ? <button type="button" className="sb-btn" title="새로 읽기" aria-label="새로 읽기" onClick={() => { loadStatus(); onReload(); }}>↻</button> : null}
        </div>
        <div className="rp-body">
          {kind === "files" ? <FileTree ws={ws} onOpen={(path) => onOpen({ kind: "file", path })} active={activeFile} />
            : kind === "changes" ? <Changes ws={ws} run={run} status={status} onOpen={onOpen} />
            : kind === "git" ? (run ? <div className="page"><RunMergePanel data={run} m={ws.machine} q={{ project: ws.project, run: ws.run! }} onReload={onReload} /></div>
              : <Commits status={status} />)
            : ws.machine === LOCAL ? <div className="page"><AgentConfigView project={run?.code_dir || ws.project} /></div>
            : <div className="rp-empty">원격 머신의 에이전트 설정은 아직 볼 수 없습니다.</div>}
        </div>
      </div>
      <nav className="rp-acts" aria-label="판 고르기">
        {ACTS.map(([k, icon, label]) => (
          <button key={k} type="button" className={`rp-act${open && kind === k ? " on" : ""}`} title={label} aria-label={label}
                  onClick={() => (open && kind === k ? onToggle() : (onKind(k), !open && onToggle()))}>
            <Icon name={icon} />{k === "changes" && nChanges ? <span className="n">{nChanges}</span> : null}
            {k === "git" && run?.worktree?.status === "open" && !run.live ? <span className="n">!</span> : null}
          </button>
        ))}
        <span className="spacer" />
        <button type="button" className="rp-act" title={open ? "판 접기 (Ctrl+L)" : "판 펼치기 (Ctrl+L)"} aria-label="판 접기·펼치기" onClick={onToggle}><Icon name="panelRight" /></button>
      </nav>
    </aside>
  );
}

function extOf(name: string) { const i = name.lastIndexOf("."); return i > 0 ? name.slice(i + 1).slice(0, 4) : ""; }

function FileTree({ ws, onOpen, active }: { ws: WsRef; onOpen: (path: string) => void; active?: string }) {
  const [dirs, setDirs] = useState<Record<string, Entry[] | "err">>({});
  const [openDirs, setOpenDirs] = useState<Record<string, boolean>>({ "": true });
  const load = useCallback(async (path: string) => {
    try {
      const r = await api<{ entries: Entry[] }>("/api/ws/tree", { query: { project: ws.project, run: ws.run || undefined, path }, machine: ws.machine });
      setDirs((d) => ({ ...d, [path]: r.entries }));
    } catch { setDirs((d) => ({ ...d, [path]: "err" })); }
  }, [ws.machine, ws.project, ws.run]);
  useEffect(() => { setDirs({}); setOpenDirs({ "": true }); load(""); }, [load]);
  const toggle = (path: string) => {
    const now = !openDirs[path];
    setOpenDirs({ ...openDirs, [path]: now });
    if (now && !dirs[path]) load(path);
  };
  const render = (path: string, depth: number): JSX.Element[] => {
    const list = dirs[path];
    if (list === "err") return [<div key={`${path}!`} className="rp-empty" style={{ paddingLeft: 14 + depth * 12 }}>읽지 못했습니다.</div>];
    if (!list) return [<div key={`${path}…`} className="faint small" style={{ paddingLeft: 26 + depth * 12, height: 22 }}>…</div>];
    const out: JSX.Element[] = [];
    for (const e of list) {
      const p = path ? `${path}/${e.name}` : e.name;
      out.push(
        <button key={p} type="button" className={`ft-row${active === p ? " on" : ""}`} style={{ paddingLeft: 8 + depth * 12 }}
                onClick={() => (e.dir ? toggle(p) : onOpen(p))} title={p}>
          <span className="chev2">{e.dir ? (openDirs[p] ? "▾" : "▸") : ""}</span>
          {e.dir ? <Icon name="folder" size={14} /> : null}
          <span className="nm" style={{ color: e.heavy ? "var(--text-3)" : undefined }}>{e.name}</span>
          {!e.dir ? <span className="ext">{extOf(e.name)}</span> : null}
        </button>,
      );
      if (e.dir && openDirs[p]) out.push(...render(p, depth + 1));
    }
    if (!list.length) out.push(<div key={`${path}∅`} className="faint small" style={{ paddingLeft: 26 + depth * 12, height: 22 }}>(비어 있음)</div>);
    return out;
  };
  return <div style={{ padding: "4px 0 20px" }}>{render("", 0)}</div>;
}

const KIND_LETTER: Record<string, string> = { modified: "M", added: "A", untracked: "U", deleted: "D", renamed: "R" };

/** 실행 diff 텍스트에서 파일별 +/- 를 센다. */
function diffFiles(text: string): { path: string; add: number; del: number }[] {
  const out: { path: string; add: number; del: number }[] = [];
  let cur: { path: string; add: number; del: number } | null = null;
  for (const line of text.split("\n")) {
    const m = /^diff --git a\/(.+?) b\/(.+)$/.exec(line);
    if (m) { cur = { path: m[2], add: 0, del: 0 }; out.push(cur); continue; }
    if (!cur || line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) cur.add++; else if (line.startsWith("-")) cur.del++;
  }
  return out;
}

function Changes({ ws, run, status, onOpen }: { ws: WsRef; run: RunData | null; status: Status | null; onOpen: (t: Tab) => void }) {
  const [runFiles, setRunFiles] = useState<{ path: string; add: number; del: number }[] | null>(null);
  useEffect(() => {
    setRunFiles(null);
    if (!run) return;
    api<{ text: string }>("/api/diff", { query: { project: ws.project, run: ws.run! }, machine: ws.machine })
      .then((d) => setRunFiles(diffFiles(d.text))).catch(() => setRunFiles([]));
  }, [run?.last_seq, ws.machine, ws.project, ws.run]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div style={{ paddingBottom: 20 }}>
      {run ? (
        <>
          <div className="rp-sec">기준 대비 (리뷰어가 받는 차이){runFiles ? <span>· {runFiles.length}</span> : null}<span className="spacer" />
            {run.notes_open ? <span className="cr-badge warn">메모 {run.notes_open}</span> : null}</div>
          <div style={{ padding: "2px 14px 8px" }}>
            <button type="button" className="btn btn-sm btn-block" onClick={() => onOpen({ kind: "changes" })}>전체 차이 · 줄 메모 열기</button>
          </div>
          {runFiles === null ? <div className="rp-empty">불러오는 중…</div> : !runFiles.length ? <div className="rp-empty">아직 바뀐 것이 없습니다.</div>
            : runFiles.map((f) => (
              <button key={f.path} type="button" className="chg" onClick={() => onOpen({ kind: "changes" })} title={f.path}>
                <span className="k modified">M</span><span className="p">{f.path}</span>
                {f.add ? <span className="ad">+{f.add}</span> : null}{f.del ? <span className="dl">−{f.del}</span> : null}
              </button>
            ))}
        </>
      ) : null}
      <div className="rp-sec">{run ? "커밋 안 된 변경" : "바뀐 파일 (HEAD 대비)"}{status?.files.length ? <span>· {status.files.length}</span> : null}</div>
      {!status ? <div className="rp-empty">불러오는 중…</div> : !status.repo ? <div className="rp-empty">git 저장소가 아닙니다.</div>
        : !status.files.length ? <div className="rp-empty">바뀐 것이 없습니다.</div>
        : status.files.map((f) => (
          <button key={f.path} type="button" className="chg" onClick={() => onOpen({ kind: "diff", path: f.path })} title={f.path}>
            <span className={`k ${f.kind}`}>{KIND_LETTER[f.kind] || "?"}</span><span className="p">{f.path}</span>
            {f.add ? <span className="ad">+{f.add}</span> : null}{f.del ? <span className="dl">−{f.del}</span> : null}
          </button>
        ))}
    </div>
  );
}

function Commits({ status }: { status: Status | null }) {
  if (!status) return <div className="rp-empty">불러오는 중…</div>;
  if (!status.repo) return <div className="rp-empty">git 저장소가 아닙니다. 새 작업을 worktree 로 따로 돌리려면 git 저장소여야 합니다.</div>;
  return (
    <div style={{ paddingBottom: 20 }}>
      <div className="rp-sec">브랜치</div>
      <div style={{ padding: "0 14px 6px" }} className="mono">{status.branch}</div>
      <div className="rp-sec">최근 커밋</div>
      {(status.commits || []).map((c) => (
        <div key={c.short} className="chg" style={{ cursor: "default" }} title={c.subject}>
          <span className="mono faint" style={{ flex: "none" }}>{c.short}</span><span className="ellipsis" style={{ flex: 1 }}>{c.subject}</span>
          <span className="faint" style={{ flex: "none", fontSize: 11 }}>{c.when}</span>
        </div>
      ))}
      <div className="rp-empty">worktree 실행을 고르면 여기서 병합 준비 확인 · 합치기 · 버리기를 합니다.</div>
    </div>
  );
}
