import { useEffect, useMemo, useRef, useState } from "react";
import { api, LOCAL } from "../lib/api";
import { fmtWhen } from "../lib/format";
import { hrefProject, hrefRun, Route } from "../lib/router";
import { hrefSession, SessionInfo } from "../sessions";
import { useUi } from "../ui";
import { countStates, itemDoing, itemTitle, WorkFolder, WorkItem } from "../works";

/** 상태는 색과 모양을 함께 (herdr·색약, 36.21): 기다림 ◆, 실패 ▲, 진행 ●(맥박), 안 봄 ●, 끝 ○. */
export function Shape({ state, title }: { state: string; title?: string }) {
  return <span className={`shape shape-${state}`} role="img" aria-label={title || STATE_LABEL[state] || state} title={title || STATE_LABEL[state] || state} />;
}

export const STATE_LABEL: Record<string, string> = {
  blocked: "나를 기다림", failed: "실패", "done-unseen": "끝남 · 안 봄", working: "진행 중", unverifiable: "소식 끊김", idle: "끝",
};
const FILTERS: [string, string][] = [["all", "전부"], ["blocked", "기다림"], ["working", "진행"], ["done-unseen", "안 봄"]];

export function itemHref(it: WorkItem): string {
  return it.kind === "session" ? hrefSession(it.session.id) : hrefRun(it.machine, it.project, it.run.run_id);
}

export function routeKey(route: Route): string {
  if (route.name === "run") return `run|${route.machine}|${route.project}|${route.run}`;
  if (route.name === "session") return `session|${route.id}`;
  return "";
}

/** 작업 목록 (NotchCrew 홈 + Orca 사이드바, 36.21). */
export default function WorkList({ folders, route, onNew, onChanged, searchRef }: {
  folders: WorkFolder[]; route: Route; onNew: (project?: string, machine?: string) => void; onChanged: () => void;
  searchRef: React.RefObject<HTMLInputElement>;
}) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [folded, setFolded] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem("tenure.folded") || "{}"); } catch { return {}; }
  });
  const counts = useMemo(() => countStates(folders), [folders]);
  const current = routeKey(route);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return folders.map((f) => ({
      ...f,
      items: f.items.filter((it) => (filter === "all" || it.state === filter || (filter === "blocked" && it.state === "failed"))
        && (!needle || `${itemTitle(it)} ${itemDoing(it)} ${f.name}`.toLowerCase().includes(needle))),
    })).filter((f) => f.items.length || (!needle && filter === "all"));
  }, [folders, q, filter]);
  const flat = useMemo(() => shown.flatMap((f) => (folded[f.key] ? [] : f.items)), [shown, folded]);
  const toggle = (key: string) => setFolded((x) => {
    const next = { ...x, [key]: !x[key] };
    try { localStorage.setItem("tenure.folded", JSON.stringify(next)); } catch { /* 저장 못 해도 됨 */ }
    return next;
  });

  // 키보드: ↑↓ 이동, / 찾기 (입력 칸에 있을 때는 빼고)
  const flatRef = useRef(flat);
  flatRef.current = flat;
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable || t.closest(".xterm"))) return;
      if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); return; }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "j" && e.key !== "k") return;
      const list = flatRef.current;
      if (!list.length) return;
      e.preventDefault();
      const i = list.findIndex((it) => it.key === routeKey(parseCurrent()));
      const down = e.key === "ArrowDown" || e.key === "j";
      const next = i < 0 ? (down ? 0 : list.length - 1) : Math.max(0, Math.min(list.length - 1, i + (down ? 1 : -1)));
      location.hash = itemHref(list[next]);
      document.querySelector(`[data-work="${CSS.escape(list[next].key)}"]`)?.scrollIntoView({ block: "nearest" });
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [searchRef]);

  return (
    <div className="wl">
      <div className="wl-head">
        <div className="row">
          <b className="wl-title">작업</b>
          <span className="wl-counts">
            {counts.blocked || counts.failed ? <span className="c-bad">기다림 {(counts.blocked || 0) + (counts.failed || 0)}</span> : null}
            {counts.working ? <span className="c-info">진행 {counts.working}</span> : null}
            {counts["done-unseen"] ? <span className="c-ok">안 봄 {counts["done-unseen"]}</span> : null}
          </span>
          <span className="spacer" />
          <button className="btn btn-sm btn-primary" type="button" onClick={() => onNew()} title="새 작업 (N)">새 작업</button>
        </div>
        <input ref={searchRef} className="wl-search" type="search" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="찾기 ( / )  ·  명령 팔레트 Ctrl+K" aria-label="작업 찾기"
               onKeyDown={(e) => { if (e.key === "Escape") { setQ(""); (e.target as HTMLInputElement).blur(); } }} />
        <div className="wl-filters" role="tablist" aria-label="상태로 거르기">
          {FILTERS.map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={filter === k} className={`capsule${filter === k ? " on" : ""}`} onClick={() => setFilter(k)}>
              {label}{k !== "all" && (counts[k] || (k === "blocked" && counts.failed)) ? <span className="n">{(counts[k] || 0) + (k === "blocked" ? counts.failed || 0 : 0)}</span> : null}
            </button>
          ))}
        </div>
      </div>
      <div className="wl-body" role="list">
        {shown.length === 0 ? (
          <div className="wl-empty">{q || filter !== "all" ? "맞는 작업이 없습니다." : <>아직 작업이 없습니다.<br /><button className="btn btn-sm" type="button" onClick={() => onNew()}>첫 작업 시작</button></>}</div>
        ) : shown.map((f) => (
          <div key={f.key} className="wl-folder">
            <div className="wl-folder-head">
              <button type="button" className="wl-fold" onClick={() => toggle(f.key)} aria-expanded={!folded[f.key]} title={f.path}>
                <span className={`chev${folded[f.key] ? "" : " open"}`} aria-hidden="true">›</span>
                <span className="ellipsis">{f.name}</span>
                {f.machine !== LOCAL ? <span className="machine">{f.machine}</span> : null}
                {folded[f.key] && f.items.some((i) => i.rank >= 4) ? <Shape state={f.items[0].state} /> : null}
              </button>
              <a className="wl-icon" href={hrefProject(f.machine, f.path)} title="프로젝트 보기" aria-label="프로젝트 보기">⋯</a>
              <button type="button" className="wl-icon" onClick={() => onNew(f.path, f.machine)} title="이 폴더에서 새 작업" aria-label="이 폴더에서 새 작업">+</button>
            </div>
            {!folded[f.key] && f.items.map((it) => (
              <WorkRow key={it.key} it={it} selected={it.key === current} onChanged={onChanged} />
            ))}
            {!folded[f.key] && f.items.length === 0 ? <div className="wl-none">실행 기록 없음</div> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function parseCurrent(): Route {
  // 키보드 핸들러는 최신 주소로 판단한다
  const h = location.hash.replace(/^#/, "");
  const m = /^\/s\/([0-9a-f]+)/.exec(h);
  if (m) return { name: "session", id: m[1] };
  const parts = h.split("?")[0].split("/").filter(Boolean);
  let machine = LOCAL;
  let p = parts;
  if (p[0] === "m" && p[1]) { machine = decodeURIComponent(p[1]); p = p.slice(2); }
  if (p[0] === "p" && p[2] === "r" && p[3]) return { name: "run", machine, project: decodeURIComponent(p[1]), run: decodeURIComponent(p[3]), tab: "" };
  return { name: "home" };
}

function WorkRow({ it, selected, onChanged }: { it: WorkItem; selected: boolean; onChanged: () => void }) {
  const { toast } = useUi();
  const s: SessionInfo | null = it.kind === "session" ? it.session : null;
  const asking = s?.status.state === "blocked";
  const answer = async (approve: boolean) => {
    try {
      await api("/api/session/answer", { method: "POST", body: { id: s!.id, approve } });
      toast(approve ? "승인을 보냈습니다." : "거절을 보냈습니다.");
      onChanged();
    } catch (e) { toast((e as Error).message, true); }
  };
  useEffect(() => {                                // 고른 행이 승인 카드면 1·2 로 답한다 (NotchCrew)
    if (!selected || !asking) return;
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.closest(".xterm"))) return;
      if (e.key === "1") { e.preventDefault(); answer(true); }
      if (e.key === "2") { e.preventDefault(); answer(false); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });   // eslint-disable-line react-hooks/exhaustive-deps
  const when = it.kind === "run" && it.run.live ? "지금" : fmtWhen(it.updated);
  return (
    <div className="wrow-wrap">
      <a className={`wrow${selected ? " sel" : ""}`} href={itemHref(it)} data-work={it.key} role="listitem" aria-current={selected ? "true" : undefined}>
        <Shape state={it.state} />
        <span className="wrow-main">
          <span className="wrow-t1">
            {it.kind === "session" ? <span className="tag-term" aria-label="대화형 세션">⌘</span> : null}
            {itemTitle(it)}
          </span>
          <span className="wrow-t2">{itemDoing(it)}</span>
        </span>
        <span className="wrow-when">{when}</span>
      </a>
      {asking ? (
        <div className="ask-card" role="group" aria-label="승인 요청">
          <div className="ask-q">{s!.status.reason || "승인을 기다립니다"}</div>
          <div className="row" style={{ gap: 6 }}>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => answer(true)}>예 <kbd>1</kbd></button>
            <button type="button" className="btn btn-sm" onClick={() => answer(false)}>아니요 <kbd>2</kbd></button>
            <span className="spacer" />
            <a className="link-quiet" href={hrefSession(s!.id)}>터미널 열기 ›</a>
          </div>
        </div>
      ) : null}
    </div>
  );
}
