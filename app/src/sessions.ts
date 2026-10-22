// 대화형 터미널 세션 (DESIGN.md 36.19): 목록 폴링, 상태 바뀜 알림.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./lib/api";

export interface SessionStatus { state: "working" | "blocked" | "idle" | "ended"; reason: string; source: string; rule: string | null; attention: "blocked" | "done-unseen" | null }
export interface SessionInfo {
  id: string; agent: "claude" | "codex"; cwd: string; project: string; run_id: string | null; created: string;
  ended: string | null; returncode: number | null; rows: number; cols: number; seen_at: string | null; title: string;
  live: boolean; status: SessionStatus;
}

export const SESSION_STATE: Record<string, string> = { working: "일하는 중", blocked: "나를 기다림", idle: "입력 기다림", ended: "끝남" };
export const hrefSession = (id: string) => `#/s/${id}`;

/** 상태 점 모양: 나를 기다림 > 일하는 중 > 턴 끝(안 봄) > 그 밖. */
export function sessionDot(s: SessionInfo) {
  return s.status.state === "blocked" ? "blocked" : s.status.state === "working" ? "working"
    : s.status.attention === "done-unseen" ? "done-unseen" : "idle";
}

const NOTIFY_KEY = "tenure.notify";
export function notifyEnabled(): boolean {
  try { return localStorage.getItem(NOTIFY_KEY) === "1" && "Notification" in window && Notification.permission === "granted"; }
  catch { return false; }
}
export async function setNotify(on: boolean): Promise<boolean> {
  if (on && "Notification" in window && Notification.permission !== "granted") {
    if ((await Notification.requestPermission()) !== "granted") return false;
  }
  try { localStorage.setItem(NOTIFY_KEY, on ? "1" : "0"); } catch { /* 저장 못 해도 이번엔 켬 */ }
  return on;
}

/** 세션 목록. 상태가 '나를 기다림'·'턴 끝(안 봄)'으로 바뀌면 브라우저 알림 (지금 보고 있는 세션은 빼고). */
export function useSessions(intervalMs = 2000) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const prev = useRef<Record<string, string | null>>({});
  const load = useCallback(async () => {
    try {
      const r = await api<{ sessions: SessionInfo[] }>("/api/sessions");
      for (const s of r.sessions) {
        const before = prev.current[s.id];
        const now = s.status.attention;
        if (now && now !== before && before !== undefined && notifyEnabled()) {
          const viewing = location.hash === hrefSession(s.id) && !document.hidden;
          if (!viewing) {
            const n = new Notification(`tenure · ${s.agent} ${now === "blocked" ? "승인을 기다림" : "턴이 끝남"}`,
              { body: `${s.status.reason}\n${s.cwd}`, tag: `tenure-session-${s.id}` });
            n.onclick = () => { window.focus(); location.hash = hrefSession(s.id); n.close(); };
          }
        }
        prev.current[s.id] = now;
      }
      setSessions(r.sessions);
    } catch { /* 서버가 잠깐 안 될 때 */ }
  }, []);
  useEffect(() => {
    load();
    const id = window.setInterval(() => { if (!document.hidden || notifyEnabled()) load(); }, intervalMs);
    return () => window.clearInterval(id);
  }, [load, intervalMs]);
  return { sessions, reload: load };
}

export async function openSession(agent: string, project: string, run?: string, title?: string): Promise<SessionInfo> {
  return api<SessionInfo>("/api/sessions", { method: "POST", body: { agent, project, run, title, rows: 32, cols: 120 } });
}
