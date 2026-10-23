import { useEffect, useMemo, useRef, useState } from "react";
import { Group } from "../data";
import { Icon } from "../icons";
import { api, LOCAL } from "../lib/api";
import { baseName, fmtWhen } from "../lib/format";
import { useUi } from "../ui";
import { itemDoing, itemTitle, WorkFolder, WorkItem } from "../works";
import { hrefSessionWs, hrefWs, usePref, WsRef, wsKey } from "../ws";
import { Shape, STATE_LABEL } from "./WorkList";

/** 왼쪽 작업공간 목록 (오르카 사이드바, 36.22). 묶음은 주의 순: 고정 · 나를 기다림 · 진행 중 · 끝남(안 봄) · 최근 · 폴더. */
export function itemWs(it: WorkItem): WsRef {
  return it.kind === "run" ? { machine: it.machine, project: it.project, run: it.run.run_id }
    : { machine: LOCAL, project: it.project, run: it.session.run_id };
}
export function itemWsHref(it: WorkItem): string {
  return it.kind === "session" ? hrefSessionWs(it.session) : hrefWs(itemWs(it), "flow");
}

const NAV: [string, string, string][] = [
  ["#/usage", "gauge", "사용량"], ["#/bench", "flask", "벤치마크"], ["#/setup", "plug", "환경·로그인"], ["#/settings", "cog", "설정"],
];

export default function Sidebar({ folders, groups, current, currentTab, page, width, onNew, onPalette, onChanged, onAddFolder }: {
  folders: WorkFolder[]; groups: Group[] | null; current: WsRef | null; currentTab: string; page: string; width: number;
  onNew: (project?: string, machine?: string) => void; onPalette: () => void; onChanged: () => void; onAddFolder: () => void;
}) {
  const [q, setQ] = useState("");
  const [pins, setPins] = usePref<string[]>("pins", []);
  const [folded, setFolded] = usePref<Record<string, boolean>>("sbFolded", {});
  const filterRef = useRef<HTMLInputElement>(null);
  const items = useMemo(() => folders.flatMap((f) => f.items.map((it) => ({ it, folder: f }))), [folders]);
  const needle = q.trim().toLowerCase();
  const match = (it: WorkItem, f: WorkFolder) => !needle || `${itemTitle(it)} ${itemDoing(it)} ${f.name}`.toLowerCase().includes(needle);

  const sections = useMemo(() => {
    const list = items.filter(({ it, folder }) => match(it, folder));
    const pinned = list.filter(({ it }) => pins.includes(it.key));
    const rest = list.filter(({ it }) => !pins.includes(it.key));
    const by = (pred: (s: string) => boolean) => rest.filter(({ it }) => pred(it.state))
      .sort((a, b) => (b.it.rank - a.it.rank) || b.it.updated.localeCompare(a.it.updated));
    const recent = by((s) => s === "idle").slice(0, 10);
    return [
      ["pinned", "고정", pinned],
      ["ask", "나를 기다림", by((s) => s === "blocked" || s === "failed")],
      ["working", "진행 중", by((s) => s === "working" || s === "unverifiable")],
      ["unseen", "끝남 · 안 봄", by((s) => s === "done-unseen")],
      ["recent", "최근", recent],
    ] as [string, string, { it: WorkItem; folder: WorkFolder }[]][];
  }, [items, pins, needle]);   // eslint-disable-line react-hooks/exhaustive-deps

  // 폴더(기본 작업공간): 등록된 모든 프로젝트 + 작업이 있는 폴더
  const projects = useMemo(() => {
    const map = new Map<string, { machine: string; path: string; name: string; n: number }>();
    for (const g of groups || []) for (const p of g.projects || []) map.set(`${g.id}|${p.path}`, { machine: g.id, path: p.path, name: baseName(p.path), n: 0 });
    for (const f of folders) {
      const k = `${f.machine}|${f.path}`;
      const cur = map.get(k) || { machine: f.machine, path: f.path, name: f.name, n: 0 };
      cur.n = f.items.length;
      map.set(k, cur);
    }
    return [...map.values()].filter((p) => !needle || p.name.toLowerCase().includes(needle)).sort((a, b) => a.name.localeCompare(b.name));
  }, [groups, folders, needle]);

  const flat = useMemo(() => sections.flatMap(([k, , list]) => (folded[k] ? [] : list.map((x) => x.it))), [sections, folded]);
  const flatRef = useRef(flat);
  flatRef.current = flat;
  const curKey = current ? wsKey(current) : "";
  const isOn = (it: WorkItem) => wsKey(itemWs(it)) === curKey && (it.kind === "run" || currentTab === `s:${it.session.id}`);

  useEffect(() => {                                // ↑↓ / j k 로 작업 이동, / 로 거르기 칸
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable || t.closest(".xterm"))) return;
      if (e.key === "/") { e.preventDefault(); filterRef.current?.focus(); return; }
      if (!["ArrowDown", "ArrowUp", "j", "k"].includes(e.key) || e.ctrlKey || e.altKey || e.metaKey) return;
      const list = flatRef.current;
      if (!list.length) return;
      e.preventDefault();
      const i = list.findIndex((it) => document.querySelector(`[data-work="${CSS.escape(it.key)}"].on`));
      const down = e.key === "ArrowDown" || e.key === "j";
      const next = i < 0 ? (down ? 0 : list.length - 1) : Math.max(0, Math.min(list.length - 1, i + (down ? 1 : -1)));
      location.hash = itemWsHref(list[next]);
      document.querySelector(`[data-work="${CSS.escape(list[next].key)}"]`)?.scrollIntoView({ block: "nearest" });
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  const waiting = sections[1][2].length;
  const togglePin = (key: string) => setPins(pins.includes(key) ? pins.filter((x) => x !== key) : [...pins, key]);
  const fold = (k: string) => setFolded({ ...folded, [k]: !folded[k] });
  const empty = !items.length && !projects.length;

  return (
    <aside className="sb" style={{ ["--sb-w" as string]: `${width}px` }} aria-label="작업공간">
      <nav className="sb-nav">
        <button type="button" className="sb-search" onClick={onPalette}><Icon name="search" size={15} /><span>찾기 · 명령</span><span className="kbd">Ctrl K</span></button>
        <button type="button" className="sb-link" onClick={() => onNew()} style={{ border: 0, background: "none", cursor: "pointer", textAlign: "left" }}>
          <Icon name="plus" /><span>새 작업</span><span className="kbd" style={{ marginLeft: "auto" }}>N</span></button>
        <a href="#/" className={`sb-link${page === "home" ? " on" : ""}`}><Icon name="work" /><span>할 일</span>{waiting ? <span className="n">{waiting}</span> : null}</a>
        {NAV.map(([href, icon, label]) => (
          <a key={href} href={href} className={`sb-link${page === href.slice(2) ? " on" : ""}`}><Icon name={icon} /><span>{label}</span></a>
        ))}
      </nav>
      <div className="sb-head">
        <b>작업공간</b><span className="spacer" />
        <button type="button" className="sb-btn" title="폴더 추가" aria-label="폴더 추가" onClick={onAddFolder}><Icon name="folderPlus" /></button>
        <button type="button" className="sb-btn" title="새 작업 (N)" aria-label="새 작업" onClick={() => onNew()}><Icon name="plus" /></button>
      </div>
      <input ref={filterRef} className="sb-filter" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="거르기 ( / )" aria-label="작업 거르기"
             onKeyDown={(e) => { if (e.key === "Escape") { setQ(""); (e.target as HTMLInputElement).blur(); } }} />
      <div className="sb-body" role="list">
        {empty ? <div className="sb-empty">아직 작업공간이 없습니다.<br />폴더를 추가하거나 새 작업을 시작하세요.</div> : null}
        {sections.map(([k, label, list]) => list.length ? (
          <div key={k}>
            <button type="button" className="sb-group" onClick={() => fold(k)} aria-expanded={!folded[k]}>
              {k === "pinned" ? <Icon name="pin" /> : k === "ask" ? <Shape state="blocked" /> : k === "working" ? <Shape state="working" />
                : k === "unseen" ? <Shape state="done-unseen" /> : null}
              <span>{label}</span><span className="cnt">{list.length}</span>
            </button>
            {!folded[k] && list.map(({ it, folder }) => (
              <Row key={it.key} it={it} folder={folder} on={isOn(it)} pinned={pins.includes(it.key)} onPin={() => togglePin(it.key)} onChanged={onChanged} />
            ))}
          </div>
        ) : null)}
        {projects.length ? (
          <div>
            <button type="button" className="sb-group" onClick={() => fold("folders")} aria-expanded={!folded.folders}>
              <Icon name="folder" /><span>폴더</span><span className="cnt">{projects.length}</span>
            </button>
            {!folded.folders && projects.map((p) => {
              const ws: WsRef = { machine: p.machine, project: p.path, run: null };
              const on = wsKey(ws) === curKey;
              return (
                <a key={`${p.machine}|${p.path}`} className={`card-row${on ? " on" : ""}`} href={hrefWs(ws)} title={p.path}>
                  <span className="cr-title"><Icon name="folder" size={13} /><span className="t">{p.name}</span>
                    {p.machine !== LOCAL ? <span className="cr-badge">{p.machine}</span> : null}
                    {p.n ? <span className="cr-badge">{p.n}</span> : null}
                    <button type="button" className="sb-btn cr-pin" title="이 폴더에서 새 작업" aria-label="이 폴더에서 새 작업"
                            onClick={(e) => { e.preventDefault(); e.stopPropagation(); onNew(p.path, p.machine); }}><Icon name="plus" /></button>
                  </span>
                </a>
              );
            })}
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function AgentIcon({ name }: { name?: string }) {
  const base = String(name || "").replace(/^mock-/, "");
  if (base === "claude" || base === "codex") return <img src={`/logos/${base}.svg`} alt="" width={13} height={13} style={{ flex: "none" }} />;
  if (base === "shell") return <span className="agent-ic shell">$</span>;
  return null;
}

function Row({ it, folder, on, pinned, onPin, onChanged }: {
  it: WorkItem; folder: WorkFolder; on: boolean; pinned: boolean; onPin: () => void; onChanged: () => void;
}) {
  const { toast } = useUi();
  const s = it.kind === "session" ? it.session : null;
  const asking = s?.status.state === "blocked";
  const answer = async (approve: boolean) => {
    try {
      await api("/api/session/answer", { method: "POST", body: { id: s!.id, approve } });
      toast(approve ? "승인을 보냈습니다." : "거절을 보냈습니다.");
      onChanged();
    } catch (e) { toast((e as Error).message, true); }
  };
  useEffect(() => {                                // 고른 행이 승인 카드면 1·2 로 답한다 (NotchCrew)
    if (!on || !asking) return;
    const k = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.closest(".xterm"))) return;
      if (e.key === "1") { e.preventDefault(); answer(true); }
      if (e.key === "2") { e.preventDefault(); answer(false); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });   // eslint-disable-line react-hooks/exhaustive-deps
  const r = it.kind === "run" ? it.run : null;
  const branch = r?.worktree?.branch || (r ? (r.config?.workflow || "classic") : `${s!.agent} 세션`);
  const agent = r ? (r.live ? r.doing?.agent : undefined) : s!.agent;
  const when = r?.live ? "지금" : fmtWhen(it.updated);
  return (
    <div>
      <a className={`card-row${on ? " on" : ""}`} href={itemWsHref(it)} data-work={it.key} role="listitem" aria-current={on ? "true" : undefined}
         title={`${STATE_LABEL[it.state] || it.state} · ${itemTitle(it)}`}>
        <span className="cr-title"><Shape state={it.state} /><span className="t">{itemTitle(it)}</span></span>
        <span className="cr-meta">
          <span className="chip-repo">{folder.name}</span>
          <span className="cr-branch">{branch}</span>
          {r?.worktree?.status === "open" && !r.live && r.activity?.state !== "failed" ? <span className="cr-badge warn">병합 대기</span> : null}
          {r?.race ? <span className="cr-badge">경쟁</span> : null}
        </span>
        <span className="cr-last"><AgentIcon name={agent} /><span className={`m${it.state === "done-unseen" ? " unseen" : ""}`}>{itemDoing(it)}</span><span className="w">{when}</span></span>
        <button type="button" className={`sb-btn cr-pin${pinned ? " on" : ""}`} title={pinned ? "고정 풀기" : "고정"} aria-label={pinned ? "고정 풀기" : "고정"}
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); onPin(); }}><Icon name="pin" /></button>
      </a>
      {asking ? (
        <div className="ask-card" role="group" aria-label="승인 요청" style={{ margin: "2px 4px 6px 24px" }}>
          <div className="ask-q">{s!.status.reason || "승인을 기다립니다"}</div>
          <div className="row" style={{ gap: 6 }}>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => answer(true)}>예 <kbd>1</kbd></button>
            <button type="button" className="btn btn-sm" onClick={() => answer(false)}>아니요 <kbd>2</kbd></button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
