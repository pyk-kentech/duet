import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { useSessions } from "../sessions";
import { useUi } from "../ui";
import { buildFolders, countStates, itemDoing, itemTitle, useWorks, WorkItem } from "../works";
import { itemHref, Shape, STATE_LABEL } from "./WorkList";

/** 섬 (36.21): 데스크톱 앱이 화면 위 가운데에 띄우는 작은 창. 알약 · 펼친 판 · 배너.
 *  셸(Tauri)에는 창 크기 바꾸기(island_mode)와 메인 창 열기(open_main)만 부탁한다. 브라우저에서 열면 그냥 화면으로 보인다. */
type Mode = "pill" | "panel" | "banner";
declare global { interface Window { __TAURI_INTERNALS__?: { invoke: (cmd: string, args?: unknown) => Promise<unknown> }; islandToggle?: () => void } }

const shell = (cmd: string, args: Record<string, unknown>) => window.__TAURI_INTERNALS__?.invoke(cmd, args).catch(() => {});
const BANNER_SEC = 20;

export default function Island() {
  const { works, loaded: worksLoaded } = useWorks(null, 3000);
  const { sessions, loaded: sessionsLoaded, reload: reloadSessions } = useSessions(2000);
  const folders = useMemo(() => buildFolders(works, sessions), [works, sessions]);
  const counts = useMemo(() => countStates(folders), [folders]);
  const items = useMemo(() => folders.flatMap((f) => f.items).sort((a, b) => (b.rank - a.rank) || b.updated.localeCompare(a.updated)), [folders]);
  const [mode, setModeState] = useState<Mode>("pill");
  const [banner, setBanner] = useState<WorkItem | null>(null);
  const seen = useRef<Record<string, string> | null>(null);
  const leaveTimer = useRef(0);
  const setMode = useCallback((m: Mode) => { setModeState(m); shell("island_mode", { mode: m }); }, []);

  useEffect(() => { document.documentElement.classList.add("island-root"); }, []);
  useEffect(() => { window.islandToggle = () => setMode(mode === "panel" ? "pill" : "panel"); }, [mode, setMode]);
  useEffect(() => {                               // 새로 '나를 기다림'·'안 봄'이 되면 배너 (상태가 바뀔 때만)
    if (!worksLoaded || !sessionsLoaded) return;   // 처음 다 받은 것이 기준 (켜기 전부터 있던 것은 배너로 안 띄움)
    const now: Record<string, string> = Object.fromEntries(items.map((i) => [i.key, i.state]));
    if (seen.current) {
      const fresh = items.find((i) => (i.state === "blocked" || i.state === "done-unseen" || i.state === "failed") && seen.current![i.key] !== i.state);
      if (fresh && mode !== "panel") { setBanner(fresh); setMode("banner"); }
    }
    seen.current = now;
  }, [items, worksLoaded, sessionsLoaded]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (mode !== "banner") return;
    const id = window.setTimeout(() => { setBanner(null); setMode("pill"); }, BANNER_SEC * 1000);
    return () => window.clearTimeout(id);
  }, [mode, banner, setMode]);

  const open = (it: WorkItem) => { shell("open_main", { hash: itemHref(it) }); setMode("pill"); if (!window.__TAURI_INTERNALS__) location.hash = itemHref(it); };
  const waiting = (counts.blocked || 0) + (counts.failed || 0);
  const top = items[0];

  if (mode === "banner" && banner) {
    return (
      <div className="isl isl-banner" onMouseEnter={() => window.clearTimeout(leaveTimer.current)}>
        <button type="button" className="isl-banner-body" onClick={() => open(banner)}>
          <span className="row"><Shape state={banner.state} /><b className="ellipsis">{itemTitle(banner)}</b><span className="isl-faint">{STATE_LABEL[banner.state]}</span></span>
          <span className="isl-sub ellipsis">{itemDoing(banner)}</span>
        </button>
        <button type="button" className="isl-x" aria-label="닫기" onClick={() => { setBanner(null); setMode("pill"); }}>×</button>
      </div>
    );
  }
  if (mode === "panel") {
    return (
      <div className="isl isl-panel" onMouseEnter={() => window.clearTimeout(leaveTimer.current)}
           onMouseLeave={() => { leaveTimer.current = window.setTimeout(() => setMode("pill"), 600); }}>
        <div className="isl-head">
          <span className="isl-mark">t</span>
          <span className="isl-counts">
            {waiting ? <span className="c-bad">기다림 {waiting}</span> : null}
            {counts.working ? <span className="c-info">진행 {counts.working}</span> : null}
            {counts["done-unseen"] ? <span className="c-ok">안 봄 {counts["done-unseen"]}</span> : null}
            {!waiting && !counts.working && !counts["done-unseen"] ? <span className="isl-faint">조용함</span> : null}
          </span>
          <span className="spacer" />
          <button type="button" className="isl-link" onClick={() => shell("open_main", { hash: "#/" })}>tenure 열기</button>
          <button type="button" className="isl-x" aria-label="접기" onClick={() => setMode("pill")}>×</button>
        </div>
        <div className="isl-list">
          {items.slice(0, 14).map((it) => <IslandRow key={it.key} it={it} onOpen={open} onAnswered={reloadSessions} />)}
          {!items.length ? <div className="isl-faint" style={{ padding: 16 }}>작업이 없습니다.</div> : null}
        </div>
      </div>
    );
  }
  return (
    <button type="button" className="isl isl-pill" onClick={() => setMode("panel")}
            onMouseEnter={() => { leaveTimer.current = window.setTimeout(() => setMode("panel"), 350); }}
            onMouseLeave={() => window.clearTimeout(leaveTimer.current)} aria-label="tenure 섬 펼치기">
      <span className="isl-mark">t</span>
      {waiting ? <span className="isl-n"><Shape state="blocked" />{waiting}</span> : null}
      {counts.working ? <span className="isl-n"><Shape state="working" />{counts.working}</span> : null}
      {counts["done-unseen"] ? <span className="isl-n"><Shape state="done-unseen" />{counts["done-unseen"]}</span> : null}
      <span className="isl-one ellipsis">{top && top.rank >= 3 ? `${itemTitle(top)} · ${itemDoing(top)}` : "tenure"}</span>
    </button>
  );
}

function IslandRow({ it, onOpen, onAnswered }: { it: WorkItem; onOpen: (it: WorkItem) => void; onAnswered: () => void }) {
  const { toast } = useUi();
  const asking = it.kind === "session" && it.session.status.state === "blocked";
  const answer = async (approve: boolean) => {
    if (it.kind !== "session") return;
    try { await api("/api/session/answer", { method: "POST", body: { id: it.session.id, approve } }); onAnswered(); }
    catch (e) { toast((e as Error).message, true); }
  };
  return (
    <div className="isl-row-wrap">
      <button type="button" className="isl-row" onClick={() => onOpen(it)}>
        <Shape state={it.state} />
        <span className="wrow-main"><span className="wrow-t1">{itemTitle(it)}</span><span className="wrow-t2">{itemDoing(it)}</span></span>
      </button>
      {asking && it.kind === "session" ? (
        <div className="ask-card">
          <div className="ask-q">{it.session.status.reason || "승인을 기다립니다"}</div>
          <div className="row" style={{ gap: 6 }}>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => answer(true)}>예</button>
            <button type="button" className="btn btn-sm" onClick={() => answer(false)}>아니요</button>
            <span className="spacer" />
            <button type="button" className="link-quiet" onClick={() => onOpen(it)}>터미널 열기 ›</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
