// 폴더 고르기 (DESIGN.md 28.9): 브라우저는 절대 경로를 주지 않으므로 서버가 고른다.
// 이 머신이고 OS 창을 쓸 수 있으면 OS 폴더 선택 창, 아니면 tenure 폴더 창(/api/fs/dirs).
import { useEffect, useState } from "react";
import { api, LOCAL } from "../lib/api";
import { ErrorBox, Modal, useUi } from "../ui";

interface Dirs { path: string | null; parent: string | null; sep: string; roots: { name: string; path: string }[];
  entries: { name: string; path: string; git?: boolean; tenure?: boolean }[]; truncated?: boolean }

export function FolderButton({ machine, value, onPick, nativeOk }: { machine: string; value: string; onPick: (p: string) => void; nativeOk: boolean }) {
  const { toast } = useUi();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const click = async () => {
    if (machine === LOCAL && nativeOk) {
      setBusy(true);
      toast("폴더 선택 창을 열었습니다. 안 보이면 작업 표시줄을 확인하세요.");
      try {
        const r = await api<{ path?: string }>("/api/fs/pick", { method: "POST", body: { start: value.trim() } });
        if (r.path) onPick(r.path);
        return;
      } catch (e) {
        toast(`${(e as Error).message} tenure 폴더 창으로 엽니다.`, true);
      } finally { setBusy(false); }
    }
    setOpen(true);
  };
  return (
    <>
      <button type="button" className="btn" onClick={click} disabled={busy} aria-label="폴더 고르기" title="폴더 고르기">폴더…</button>
      {open ? <FolderDialog machine={machine} start={value.trim()} onClose={() => setOpen(false)} onPick={(p) => { setOpen(false); onPick(p); }} /> : null}
    </>
  );
}

function FolderDialog({ machine, start, onClose, onPick }: { machine: string; start: string; onClose: () => void; onPick: (p: string) => void }) {
  const [d, setD] = useState<Dirs | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [typed, setTyped] = useState(start);
  const [newName, setNewName] = useState("");
  const [msg, setMsg] = useState("");
  const load = async (path: string, fallback = false) => {
    setError(null);
    try {
      const r = await api<Dirs>("/api/fs/dirs", { query: { path }, machine });
      setD(r);
      setTyped(r.path || "");
    } catch (e) {
      if (fallback) return load("");
      setError(e);
    }
  };
  useEffect(() => { load(start, true); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const choose = () => {
    if (!d?.path) return;
    const n = newName.trim();
    if (n && /[\\/:*?"<>|]/.test(n)) { setMsg('폴더 이름에 \\ / : * ? " < > | 는 쓸 수 없습니다.'); return; }
    onPick(n ? d.path.replace(/[\\/]+$/, "") + (d.sep || "/") + n : d.path);
  };
  return (
    <Modal onClose={onClose} label="폴더 고르기">
      <div className="dialog-head"><h2>폴더 고르기</h2></div>
      <div className="dialog-body col">
        <div className="chips">{(d?.roots || []).map((r) => (
          <button key={r.path} type="button" className="chip" style={{ cursor: "pointer", border: "none" }} title={r.path} onClick={() => load(r.path)}>{r.name}</button>
        ))}</div>
        <div className="row">
          <button type="button" className="btn btn-sm" disabled={!d?.parent} onClick={() => d?.parent && load(d.parent)}>↑ 위로</button>
          <input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} spellCheck={false} placeholder="경로를 쓰고 Enter"
                 onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); load(typed.trim()); } }} aria-label="경로" />
        </div>
        {error ? <ErrorBox error={error} /> : null}
        <div className="card" style={{ maxHeight: 320, overflow: "auto" }}>
          {!d ? <div className="empty small">불러오는 중…</div> : !d.path ? <div className="empty small">위에서 시작할 곳을 고르세요.</div>
            : d.entries.length === 0 ? <div className="empty small">하위 폴더가 없습니다.</div>
            : d.entries.map((e) => (
              <button key={e.path} type="button" className="tl-item clickable" title={e.path}
                      style={{ gridTemplateColumns: "1fr auto", width: "100%", border: "none", background: "none", textAlign: "left" }}
                      onClick={() => load(e.path)}>
                <span className="ellipsis">📁 {e.name}</span>
                {e.tenure ? <span className="badge ok">tenure</span> : e.git ? <span className="chip">git</span> : <span />}
              </button>
            ))}
        </div>
        {d?.truncated ? <div className="faint small">폴더가 많아 앞부분만 보입니다. 경로를 직접 써서 들어가세요.</div> : null}
        {msg ? <div className="alert alert-warn"><span>{msg}</span></div> : null}
      </div>
      <footer className="dialog-foot">
        <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="이 안에 새 폴더 이름 (선택)" style={{ maxWidth: 260 }} spellCheck={false} />
        <span className="spacer" />
        <button type="button" className="btn" onClick={onClose}>취소</button>
        <button type="button" className="btn btn-primary" disabled={!d?.path} onClick={choose}>{newName.trim() ? "새 폴더로 선택" : "이 폴더 선택"}</button>
      </footer>
    </Modal>
  );
}
