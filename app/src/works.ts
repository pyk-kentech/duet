// 작업대의 목록 데이터 (DESIGN.md 36.21): 머신별 실행 요약 + 이 머신의 대화형 세션을 폴더별로 합친다.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Group, RunSummary } from "./data";
import { api, LOCAL } from "./lib/api";
import { baseName, fmtTok, oneLine } from "./lib/format";
import { STATUS, STEP } from "./lib/labels";
import { SESSION_STATE, SessionInfo, sessionDot } from "./sessions";

export interface WorkRun extends RunSummary {
  tokens?: number; race?: boolean;
  doing?: { kind?: string; agent?: string; role?: string; step?: string; round?: number; text?: string; ts?: string };
}
export interface WorkGroup { machine: string; path: string; name: string; items: WorkRun[] }

/** 목록의 한 행. 실행이거나 대화형 세션. */
export type WorkItem =
  | { kind: "run"; key: string; machine: string; project: string; run: WorkRun; state: string; rank: number; updated: string }
  | { kind: "session"; key: string; machine: string; project: string; session: SessionInfo; state: string; rank: number; updated: string };

export interface WorkFolder { key: string; machine: string; path: string; name: string; items: WorkItem[] }

const RANK: Record<string, number> = { blocked: 6, failed: 5, "done-unseen": 4, working: 3, unverifiable: 3, idle: 1 };

export function useWorks(groups: Group[] | null, intervalMs = 3000) {
  const [data, setData] = useState<WorkGroup[]>([]);
  const [loaded, setLoaded] = useState(false);
  const busy = useRef(false);
  const ids = (groups || []).filter((g) => !g.error).map((g) => g.id).join(",");
  const load = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const machines = ids ? ids.split(",") : [LOCAL];
      const all: WorkGroup[] = [];
      await Promise.all(machines.map(async (m) => {
        try {
          const r = await api<{ groups: Omit<WorkGroup, "machine">[] }>("/api/works", { machine: m });
          for (const g of r.groups) all.push({ ...g, machine: m });
        } catch { /* 원격이 안 될 때는 건너뜀 */ }
      }));
      setData(all);
      setLoaded(true);
    } finally {
      busy.current = false;
    }
  }, [ids]);
  useEffect(() => {
    load();
    const id = window.setInterval(() => { if (!document.hidden) load(); }, intervalMs);
    return () => window.clearInterval(id);
  }, [load, intervalMs]);
  return { works: data, loaded, reload: load };
}

/** 실행·세션을 폴더별로 묶고, 묶음 안에서는 주의 순 → 최근 순. 폴더도 가장 급한 것 순. */
export function buildFolders(works: WorkGroup[], sessions: SessionInfo[]): WorkFolder[] {
  const map = new Map<string, WorkFolder>();
  const folder = (machine: string, path: string, name?: string) => {
    const key = `${machine}|${path}`;
    let f = map.get(key);
    if (!f) { f = { key, machine, path, name: name || baseName(path), items: [] }; map.set(key, f); }
    return f;
  };
  for (const g of works) {
    const f = folder(g.machine, g.path, g.name);
    for (const r of g.items) {
      const state = r.live ? "working" : r.activity?.state || "idle";
      f.items.push({ kind: "run", key: `run|${g.machine}|${g.path}|${r.run_id}`, machine: g.machine, project: g.path, run: r,
                     state, rank: RANK[state] || 0, updated: r.updated_at || r.created_at || "" });
    }
  }
  for (const s of sessions) {
    if (s.agent === "shell") continue;                       // 보통 터미널은 작업공간의 탭일 뿐 (36.22)
    if (!s.live && !s.status.attention) continue;          // 끝나고 본 세션은 목록에서 뺌 (세션 기록은 프로젝트에서)
    const state = sessionDot(s);
    folder(LOCAL, s.project).items.push({ kind: "session", key: `session|${s.id}`, machine: LOCAL, project: s.project, session: s,
                                         state, rank: RANK[state] || 0, updated: s.created });
  }
  const folders = [...map.values()];
  for (const f of folders) f.items.sort((a, b) => (b.rank - a.rank) || b.updated.localeCompare(a.updated));
  folders.sort((a, b) => ((b.items[0]?.rank || 0) - (a.items[0]?.rank || 0))
    || (b.items[0]?.updated || "").localeCompare(a.items[0]?.updated || ""));
  return folders;
}

export function countStates(folders: WorkFolder[]): Record<string, number> {
  const c: Record<string, number> = {};
  for (const f of folders) for (const it of f.items) c[it.state] = (c[it.state] || 0) + 1;
  return c;
}

/** 첫 줄: 과제 첫 줄(세션은 제목 또는 '대화형 세션'). */
export function itemTitle(it: WorkItem): string {
  if (it.kind === "session") return it.session.title || `${it.session.agent} 대화형 세션`;
  return oneLine(it.run.task, 90) || it.run.run_id;
}

/** 둘째 줄: 지금 하는 일, 끝났으면 결과. */
export function itemDoing(it: WorkItem): string {
  if (it.kind === "session") {
    const s = it.session;
    return `${s.agent} 세션 · ${SESSION_STATE[s.status.state] || s.status.state}${s.status.reason && s.status.state !== "working" ? ` — ${s.status.reason}` : ""}`;
  }
  const r = it.run;
  const wf = r.config?.workflow && r.config.workflow !== "classic" ? r.config.workflow : "";
  if (r.live) {
    const d = r.doing || {};
    if (d.kind === "step_start" || d.kind === "step_end") {
      const who = d.role || d.agent || "";
      return [who, `${STEP[d.step || ""] || d.step || ""}${d.round ? ` ${d.round}회차` : ""}`, wf].filter(Boolean).join(" · ");
    }
    if (d.kind === "log" && d.text) return oneLine(d.text, 80);
    return [STEP[r.step] || r.step, r.round ? `${r.round}회차` : "", wf].filter(Boolean).join(" · ") || "진행 중";
  }
  if (r.activity?.state === "blocked" || r.activity?.state === "failed") return r.activity.reason || STATUS[r.status] || r.status;
  const parts = [STATUS[r.status] || r.status];
  if (r.worktree) parts.push(r.worktree.status === "open" ? "병합 대기" : r.worktree.status === "merged" ? "병합됨" : "버림");
  if (r.race) parts.push("경쟁 초안");
  else if (wf) parts.push(wf);
  if (r.tokens) parts.push(`입력 ${fmtTok(r.tokens)}`);
  return parts.join(" · ");
}
