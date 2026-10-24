// 해시 라우팅. 옛 화면과 같은 주소를 쓴다(북마크·알림 링크 호환).
// #/                     받은편지함·프로젝트
// #/p/<path>             이 머신의 프로젝트,   #/m/<id>/p/<path>  원격 머신의 프로젝트
// .../r/<run>?tab=...    실행
// #/usage?m=  #/setup?m=  #/settings  #/bench
import { useEffect, useState } from "react";
import { LOCAL } from "./api";

export type Route =
  | { name: "home" }
  | { name: "project"; machine: string; project: string; tab: string; panel?: string }
  | { name: "run"; machine: string; project: string; run: string; tab: string; panel?: string }
  | { name: "usage"; machine: string }
  | { name: "setup"; machine: string }
  | { name: "settings" }
  | { name: "bench"; dir?: string }
  | { name: "session"; id: string }
  | { name: "island" };

const enc = encodeURIComponent;
const prefix = (m?: string) => (m && m !== LOCAL ? `#/m/${enc(m)}` : "#");
export const hrefProject = (m: string, p: string, tab?: string) => `${prefix(m)}/p/${enc(p)}` + (tab ? `?tab=${tab}` : "");
export const hrefRun = (m: string, p: string, r: string, tab?: string) =>
  `${prefix(m)}/p/${enc(p)}/r/${enc(r)}` + (tab ? `?tab=${tab}` : "");

export function parseHash(hash = location.hash): Route {
  const raw = hash.replace(/^#/, "") || "/";
  const [pathPart, qs] = raw.split("?");
  let parts = pathPart.split("/").filter(Boolean);
  const q = new URLSearchParams(qs || "");
  try {
    if (parts[0] === "usage") return { name: "usage", machine: q.get("m") || LOCAL };
    if (parts[0] === "setup") return { name: "setup", machine: q.get("m") || LOCAL };
    if (parts[0] === "settings") return { name: "settings" };
    if (parts[0] === "bench") return { name: "bench", dir: q.get("dir") || undefined };
    if (parts[0] === "island") return { name: "island" };                                        // 데스크톱 섬 (36.21)
    if (parts[0] === "s" && parts[1]) return { name: "session", id: decodeURIComponent(parts[1]) };   // 대화형 세션 (36.19)
    let machine = LOCAL;
    if (parts[0] === "m" && parts[1]) {
      machine = decodeURIComponent(parts[1]);
      parts = parts.slice(2);
    }
    if (parts[0] === "p" && parts[1]) {
      const project = decodeURIComponent(parts[1]);
      // 작업공간 (36.22): tab 은 작업공간의 탭 키 (flow, s:<id>, f:<경로> …), 옛 탭 이름(timeline·runs)은 기본 탭으로
      let tab = q.get("tab") || "";
      let panel = q.get("panel") || undefined;
      if (tab === "merge") { tab = ""; panel = "merge"; }
      if (parts[2] === "r" && parts[3]) return { name: "run", machine, project, run: decodeURIComponent(parts[3]), tab: tab === "timeline" || tab === "talk" ? "" : tab, panel };
      return { name: "project", machine, project, tab: tab === "runs" ? "" : tab, panel };
    }
  } catch { /* 잘못된 주소 → 홈 */ }
  return { name: "home" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash());
  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
