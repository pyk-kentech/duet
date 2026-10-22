import { useEffect, useMemo, useRef, useState } from "react";
import { baseName } from "../lib/format";
import { hrefProject } from "../lib/router";
import { itemDoing, itemTitle, WorkFolder } from "../works";
import { itemHref, Shape } from "./WorkList";

interface Cmd { key: string; label: string; hint?: string; state?: string; run: () => void }

/** 명령 팔레트 (Ctrl+K, 36.21): 작업·프로젝트·화면을 글자로 찾아 Enter 로 연다. */
export default function Palette({ folders, onClose, onNew }: { folders: WorkFolder[]; onClose: () => void; onNew: () => void }) {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const d = ref.current; if (d && !d.open) d.showModal(); return () => { if (d?.open) d.close(); }; }, []);
  const go = (href: string) => () => { location.hash = href; };
  const cmds = useMemo<Cmd[]>(() => [
    { key: "new", label: "새 작업", hint: "N", run: onNew },
    { key: "home", label: "오늘", hint: "화면", run: go("#/") },
    { key: "usage", label: "사용량", hint: "화면", run: go("#/usage") },
    { key: "bench", label: "벤치마크", hint: "화면", run: go("#/bench") },
    { key: "setup", label: "환경·로그인", hint: "화면", run: go("#/setup") },
    { key: "settings", label: "설정", hint: "화면", run: go("#/settings") },
    ...folders.map((f) => ({ key: `p|${f.key}`, label: f.name, hint: "프로젝트", run: go(hrefProject(f.machine, f.path)) })),
    ...folders.flatMap((f) => f.items.map((it) => ({
      key: it.key, label: itemTitle(it), hint: `${baseName(it.project)} · ${itemDoing(it)}`, state: it.state, run: go(itemHref(it)),
    }))),
  ], [folders, onNew]);   // eslint-disable-line react-hooks/exhaustive-deps
  const shown = useMemo(() => {
    const n = q.trim().toLowerCase();
    return (n ? cmds.filter((c) => `${c.label} ${c.hint || ""}`.toLowerCase().includes(n)) : cmds).slice(0, 60);
  }, [cmds, q]);
  useEffect(() => setI(0), [q]);
  const pick = (c: Cmd | undefined) => { if (!c) return; onClose(); c.run(); };
  return (
    <dialog ref={ref} className="dialog palette" aria-label="명령 팔레트" onCancel={(e) => { e.preventDefault(); onClose(); }}
            onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="작업·프로젝트·화면 찾기" aria-label="찾기"
             onKeyDown={(e) => {
               if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(shown.length - 1, x + 1)); }
               else if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(0, x - 1)); }
               else if (e.key === "Enter") { e.preventDefault(); pick(shown[i]); }
             }} />
      <div className="pal-list" role="listbox">
        {shown.map((c, k) => (
          <button key={c.key} type="button" role="option" aria-selected={k === i} className={`pal-item${k === i ? " on" : ""}`}
                  onMouseEnter={() => setI(k)} onClick={() => pick(c)}>
            {c.state ? <Shape state={c.state} /> : <span className="pal-dot" aria-hidden="true" />}
            <span className="ellipsis">{c.label}</span>
            <span className="pal-hint ellipsis">{c.hint}</span>
          </button>
        ))}
        {!shown.length ? <div className="faint small" style={{ padding: 12 }}>맞는 것이 없습니다.</div> : null}
      </div>
    </dialog>
  );
}
