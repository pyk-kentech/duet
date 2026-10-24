// 작업공간 (DESIGN.md 36.22): 오르카의 작업공간 = 작업 폴더 하나. tenure 에서는 프로젝트 폴더(기본) 또는 실행의 worktree.
// 한 작업공간 안에 탭(흐름·에이전트 세션·터미널·파일·차이)이 있고, 오른쪽 판은 그 폴더의 파일·변경·git 을 본다.
import { useCallback, useEffect, useState } from "react";
import { LOCAL } from "./lib/api";
import { SessionInfo } from "./sessions";

export interface WsRef { machine: string; project: string; run: string | null }

/** 탭. session 은 세션 목록에서 오고, 나머지는 사용자가 연 것(작업공간마다 localStorage 에 기억). */
export type Tab =
  | { kind: "flow" }                       // 실행의 흐름 (대화·결과 요약)
  | { kind: "overview" }                   // 폴더 작업공간의 개요 (실행 목록)
  | { kind: "session"; id: string }
  | { kind: "file"; path: string }
  | { kind: "diff"; path: string }         // 폴더 작업공간의 파일 차이 (HEAD 대비)
  | { kind: "changes" }                    // 실행의 기준 대비 전체 차이 + 줄 메모
  | { kind: "drafts" } | { kind: "design" } | { kind: "console" } | { kind: "issues" };

export const tabKey = (t: Tab): string =>
  t.kind === "session" ? `s:${t.id}` : t.kind === "file" ? `f:${t.path}` : t.kind === "diff" ? `d:${t.path}` : t.kind;

export function parseTabKey(k: string | null | undefined): Tab | null {
  if (!k) return null;
  if (k.startsWith("s:")) return { kind: "session", id: k.slice(2) };
  if (k.startsWith("f:")) return { kind: "file", path: k.slice(2) };
  if (k.startsWith("d:")) return { kind: "diff", path: k.slice(2) };
  if (["flow", "overview", "changes", "drafts", "design", "console", "issues"].includes(k)) return { kind: k } as Tab;
  return null;
}

export const wsKey = (w: WsRef) => `${w.machine}|${w.project}|${w.run || ""}`;

const enc = encodeURIComponent;
/** 작업공간 주소: 옛 주소(#/p/…, #/p/…/r/…)를 그대로 쓰고 ?tab= 으로 탭을 고른다. */
export function hrefWs(w: WsRef, tab?: Tab | string | null): string {
  const pre = w.machine && w.machine !== LOCAL ? `#/m/${enc(w.machine)}` : "#";
  const t = typeof tab === "string" ? tab : tab ? tabKey(tab) : "";
  return `${pre}/p/${enc(w.project)}` + (w.run ? `/r/${enc(w.run)}` : "") + (t ? `?tab=${enc(t)}` : "");
}

export const hrefSessionWs = (s: SessionInfo) => hrefWs({ machine: LOCAL, project: s.project, run: s.run_id }, { kind: "session", id: s.id });

/** 이 작업공간에 속한 세션: 같은 프로젝트·같은 실행. 끝나고 닫은 것은 목록에서 이미 빠져 있다. */
export function wsSessions(w: WsRef, sessions: SessionInfo[]): SessionInfo[] {
  if (w.machine !== LOCAL) return [];
  const recent = Date.now() - 30 * 60_000;          // 끝난 것은 30분 동안만 탭으로 남김 (안 본 턴 끝은 계속)
  return sessions.filter((s) => s.project === w.project && (s.run_id || null) === (w.run || null)
    && (s.live || !!s.status.attention || Date.parse(s.ended || s.created) > recent));
}

/** 사용자가 연 파일·차이·판 탭 (작업공간마다 기억). */
export function useOpenTabs(w: WsRef) {
  const key = `tenure.tabs.${wsKey(w)}`;
  const read = (): string[] => { try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; } };
  const [open, setOpen] = useState<string[]>(read);
  useEffect(() => { setOpen(read()); }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  const save = useCallback((next: string[]) => {
    setOpen(next);
    try { localStorage.setItem(key, JSON.stringify(next.slice(-30))); } catch { /* 기억 못 해도 됨 */ }
  }, [key]);
  const add = useCallback((k: string) => { const cur = read(); if (!cur.includes(k)) save([...cur, k]); }, [save]);   // eslint-disable-line react-hooks/exhaustive-deps
  const remove = useCallback((k: string) => save(read().filter((x) => x !== k)), [save]);   // eslint-disable-line react-hooks/exhaustive-deps
  return { open, add, remove };
}

/** 화면 크기·접힘 같은 개인 설정 (localStorage, 실패해도 기본값). */
export function usePref<T>(name: string, initial: T): [T, (v: T) => void] {
  const key = `tenure.pref.${name}`;
  const [v, setV] = useState<T>(() => { try { const s = localStorage.getItem(key); return s ? JSON.parse(s) as T : initial; } catch { return initial; } });
  const set = useCallback((x: T) => { setV(x); try { localStorage.setItem(key, JSON.stringify(x)); } catch { /* 무시 */ } }, [key]);
  return [v, set];
}
