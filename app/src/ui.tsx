// 공통 화면 조각
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ACTIVITY, STATUS, TEST_STATUS } from "./lib/labels";

export function StateDot({ state, title }: { state?: string; title?: string }) {
  const s = state || "idle";
  return <span className={`dot dot-${s}`} role="img" aria-label={title || ACTIVITY[s] || s} title={title || ACTIVITY[s] || s} />;
}

const STATUS_TONE: Record<string, string> = {
  running: "info", done_approved: "ok", done_unapproved: "warn", done_design: "info",
  stopped_rate_limit: "wait", stopped_user: "", failed: "bad", broken: "bad", stale: "warn",
};

export function StatusBadge({ status, live, stale }: { status: string; live?: boolean; stale?: boolean }) {
  const key = stale ? "stale" : status;
  if (live) return <span className="badge info"><span className="spinner" style={{ width: 10, height: 10 }} />실행 중</span>;
  return <span className={`badge ${STATUS_TONE[key] || ""}`}>{STATUS[key] || key}</span>;
}

export function Verdict({ v }: { v?: { status?: string; must_fix?: number | null } | null }) {
  if (!v || !v.status) return null;
  return <span className={`verdict v-${v.status}`}>{v.status === "APPROVED" ? "승인" : "반려"}{v.must_fix ? ` ${v.must_fix}` : ""}</span>;
}

export function TestTag({ status }: { status?: string }) {
  if (!status) return null;
  return <span className={`verdict t-${status}`}>테스트 {TEST_STATUS[status] || status}</span>;
}

export function AgentTag({ name, role }: { name?: string; role?: string }) {
  if (!name) return null;
  const base = String(name).replace(/^mock-/, "");
  const known = base === "claude" || base === "codex";
  return (
    <span className="row" style={{ gap: 5, display: "inline-flex" }} title={role ? `${role} (${name})` : undefined}>
      {known ? <img src={`/logos/${base}.svg`} alt="" width={14} height={14} /> : null}
      <span>{role || name}</span>
    </span>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="alert alert-bad"><b>오류</b><span>{msg}</span></div>;
}

// ---------------------------------------------------------------- 알림·확인 창
type ToastFn = (msg: string, bad?: boolean) => void;
type ConfirmFn = (msg: string, opts?: { ok?: string; danger?: boolean }) => Promise<boolean>;
const Ctx = createContext<{ toast: ToastFn; confirm: ConfirmFn }>({ toast: () => {}, confirm: async () => false });
export const useUi = () => useContext(Ctx);

export function UiProvider({ children }: { children: ReactNode }) {
  const [toastMsg, setToastMsg] = useState<{ msg: string; bad: boolean } | null>(null);
  const [ask, setAsk] = useState<{ msg: string; ok: string; danger: boolean; resolve: (v: boolean) => void } | null>(null);
  const timer = useRef<number>();
  const toast = useCallback<ToastFn>((msg, bad = false) => {
    setToastMsg({ msg, bad });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToastMsg(null), bad ? 6000 : 3200);
  }, []);
  // 브라우저 confirm() 은 앱 안 미리보기 등에서 바로 '취소'를 돌려주기도 해서 쓰지 않는다
  const confirm = useCallback<ConfirmFn>((msg, opts) => new Promise((resolve) => {
    setAsk({ msg, ok: opts?.ok || "확인", danger: !!opts?.danger, resolve });
  }), []);
  const done = (v: boolean) => { ask?.resolve(v); setAsk(null); };
  return (
    <Ctx.Provider value={{ toast, confirm }}>
      {children}
      {toastMsg && <div className={`toast${toastMsg.bad ? " bad" : ""}`} role="status">{toastMsg.msg}</div>}
      {ask && (
        <Modal onClose={() => done(false)} label="확인">
          <div className="dialog-body"><p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{ask.msg}</p></div>
          <footer className="dialog-foot">
            <button className="btn" type="button" onClick={() => done(false)}>취소</button>
            <button className={`btn ${ask.danger ? "btn-danger" : "btn-primary"}`} type="button" autoFocus onClick={() => done(true)}>{ask.ok}</button>
          </footer>
        </Modal>
      )}
    </Ctx.Provider>
  );
}

export function Modal({ children, onClose, label, wide }: { children: ReactNode; onClose: () => void; label: string; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
    return () => { if (d?.open) d.close(); };
  }, []);
  return (
    <dialog ref={ref} className={`dialog${wide ? " wide" : ""}`} aria-label={label}
            onCancel={(e) => { e.preventDefault(); onClose(); }}
            onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      {children}
    </dialog>
  );
}

/** 주기적으로 다시 불러오기. ms 가 null 이면 멈춘다. */
export function usePoll(fn: () => void, ms: number | null, deps: unknown[] = []) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    saved.current();
    if (ms === null) return;
    const id = window.setInterval(() => { if (!document.hidden) saved.current(); }, ms);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, ...deps]);
}
