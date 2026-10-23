import { hrefRun, Route } from "../lib/router";
import { hrefSession } from "../sessions";
import type { WorkItem } from "../works";

/** 상태 표시 (오르카 StatusIndicator, 36.22): 진행 = 도는 노란 고리, 기다림 = 주황 ?, 안 봄 = 초록 점, 실패 = 빨간 점, 끝 = 흐린 점. */
export function Shape({ state, title }: { state: string; title?: string }) {
  return <span className={`shape shape-${state}`} role="img" aria-label={title || STATE_LABEL[state] || state} title={title || STATE_LABEL[state] || state} />;
}

export const STATE_LABEL: Record<string, string> = {
  blocked: "나를 기다림", failed: "실패", "done-unseen": "끝남 · 안 봄", working: "진행 중", unverifiable: "소식 끊김", idle: "끝",
};

export function itemHref(it: WorkItem): string {
  return it.kind === "session" ? hrefSession(it.session.id) : hrefRun(it.machine, it.project, it.run.run_id);
}

export function routeKey(route: Route): string {
  if (route.name === "run") return `run|${route.machine}|${route.project}|${route.run}`;
  if (route.name === "session") return `session|${route.id}`;
  return "";
}
