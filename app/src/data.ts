// 여러 화면이 함께 쓰는 데이터: 머신별 프로젝트, 받은편지함
import { useCallback, useEffect, useRef, useState } from "react";
import { api, LOCAL } from "./lib/api";

export interface Activity { state: string; reason: string; rank: number }
export interface RunSummary {
  run_id: string; status: string; phase: string; step: string; round: number; task: string;
  created_at?: string; updated_at?: string; calls: number; total_sec: number; last_verdict?: string | null;
  live?: boolean; stale?: boolean; activity?: Activity; error?: string | null; config?: Record<string, any>;
  worktree?: { branch: string; status: "open" | "merged" | "discarded"; base_branch: string } | null;
}
export interface Project {
  path: string; name: string; display?: string; exists: boolean; run_count: number;
  latest?: RunSummary | null; live?: { pid: number; run_id: string } | null; bench?: string | null;
}
export interface Group { id: string; name: string; local?: boolean; ssh?: string; error?: string; projects: Project[]; jobs?: any[] }
export interface InboxItem { machine: string; project: string; run_id: string; task: string; status: string; activity: Activity; updated_at?: string }

export function useGroups(intervalMs = 5000) {
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => {
    try {
      const r = await api<{ machines: Group[] }>("/api/projects");   // 머신별 묶음 (이 머신이 먼저)
      setGroups(r.machines || []);
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, []);
  useEffect(() => {
    load();
    const id = window.setInterval(() => { if (!document.hidden) load(); }, intervalMs);
    return () => window.clearInterval(id);
  }, [load, intervalMs]);
  return { groups, error, reload: load };
}

/** 모든 머신의 받은편지함을 합친다 (주의 순: 나를 기다림 > 끝났는데 안 봄 > 진행 중). */
export function useInbox(groups: Group[] | null, intervalMs = 4000) {
  const [items, setItems] = useState<InboxItem[]>([]);
  const ids = (groups || []).filter((g) => !g.error).map((g) => g.id).join(",");
  const busy = useRef(false);
  const load = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const machines = ids ? ids.split(",") : [LOCAL];
      const all: InboxItem[] = [];
      await Promise.all(machines.map(async (m) => {
        try {
          const r = await api<{ items: Omit<InboxItem, "machine">[] }>("/api/inbox", { machine: m });
          for (const it of r.items) all.push({ ...it, machine: m });
        } catch { /* 원격이 안 될 때는 건너뜀 */ }
      }));
      all.sort((a, b) => (b.activity.rank - a.activity.rank) || String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
      setItems(all);
    } finally {
      busy.current = false;
    }
  }, [ids]);
  useEffect(() => {
    load();
    const id = window.setInterval(() => { if (!document.hidden) load(); }, intervalMs);
    return () => window.clearInterval(id);
  }, [load, intervalMs]);
  return { items, reload: load };
}
