import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { TestTag, useUi } from "../ui";

/** worktree 실행의 병합 준비 점검·병합·버리기·충돌 해결 (DESIGN.md 36.14). 병합은 사람이 누른다. */
export interface Tree {
  run_id: string; path: string; branch: string; base_branch: string; base_commit: string; created: string;
  status: "open" | "merged" | "discarded"; merged_commit: string | null; patch: string | null; note: Record<string, any>;
}
interface Check { key: string; level: "block" | "warn" | "ok"; label: string; detail: string }
interface Ready { run_id: string; tree: Tree; checks: Check[]; conflicts: string[]; ahead: number; behind: number; files: string[]; can_merge: boolean }

const LEVEL: Record<Check["level"], { cls: string; text: string }> = {
  block: { cls: "bad", text: "막음" }, warn: { cls: "warn", text: "주의" }, ok: { cls: "ok", text: "통과" },
};
export const TREE_STATUS: Record<Tree["status"], { cls: string; text: string }> = {
  open: { cls: "info", text: "병합 대기" }, merged: { cls: "ok", text: "병합됨" }, discarded: { cls: "", text: "버림" },
};
const KIND: Record<string, string> = { resolve: "충돌 해결", notes: "줄 메모 반영" };

export function MergePanel({ m, q, tree, st, live, onReload }: {
  m: string; q: Record<string, string>; tree: Tree; st: any; live: boolean; onReload: () => void;
}) {
  const { toast, confirm } = useUi();
  const [ready, setReady] = useState<Ready | null>(null);
  const [err, setErr] = useState("");
  const [mode, setMode] = useState<"squash" | "merge">("squash");
  const [busy, setBusy] = useState(false);
  const check = () => {
    setErr("");
    api<Ready>("/api/merge/check", { query: q, machine: m }).then(setReady).catch((e) => setErr((e as Error).message));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (tree.status === "open") check(); }, [m, q, tree.status, live, st.updated_at]);

  const finished = ["done_approved", "done_unapproved", "done_design"].includes(st.status);
  const followups: any[] = st.followups || [];
  const act = async (path: string, body: Record<string, unknown>, done: string, wait = 0) => {
    setBusy(true);
    try {
      const r = await api<any>(path, { method: "POST", body: { ...q, ...body }, machine: m });
      toast(done.replace("{commit}", String(r?.commit || "").slice(0, 10)).replace("{patch}", r?.patch || "없음"));
      window.setTimeout(onReload, wait);
    } catch (e) { toast((e as Error).message, true); }
    finally { setBusy(false); }
  };
  const doMerge = async () => {
    const how = mode === "squash" ? "커밋 하나로 합칩니다(squash)" : "병합 커밋을 만듭니다(--no-ff)";
    if (!(await confirm(`${tree.branch} 의 변경을 ${tree.base_branch} 에 ${how}.\n끝나면 worktree 폴더를 지우고 브랜치는 남깁니다.`, { ok: "병합" }))) return;
    act("/api/actions/merge", { mode }, "병합했습니다 (커밋 {commit}).");
  };
  const doDiscard = async () => {
    if (!(await confirm("이 작업을 버립니다. 변경은 .tenure/discarded/ 에 패치로 남고, worktree 폴더는 지우며 브랜치는 남깁니다.", { ok: "버리기", danger: true }))) return;
    act("/api/actions/discard", {}, "버렸습니다. 패치: {patch}");
  };
  const doResolve = async () => {
    if (!(await confirm(`worktree 에서 ${tree.base_branch} 를 병합해 충돌 표시를 만든 뒤, 구현 담당에게 풀게 하고 테스트를 돌립니다. 에이전트를 한 번 부릅니다.`, { ok: "맡기기" }))) return;
    act("/api/actions/resolve", {}, "충돌 해결을 시작했습니다. 잠시 뒤 진행 상황이 보입니다.", 1200);
  };

  return (
    <section className="card card-pad col" style={{ gap: 10 }}>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <h2>병합</h2>
        <span className="chip mono">{tree.branch} → {tree.base_branch || "(분리된 HEAD)"}</span>
        <span className={`badge ${TREE_STATUS[tree.status].cls}`}>{TREE_STATUS[tree.status].text}</span>
        {ready && tree.status === "open" ? <span className="faint small">커밋 {ready.ahead}개 · 파일 {ready.files.length}개{ready.behind ? ` · 기준이 ${ready.behind}커밋 앞섬` : ""}</span> : null}
        <span className="spacer" />
        {tree.status === "open" ? (
          <div className="row">
            <button className="btn btn-sm" type="button" onClick={check} disabled={busy}>다시 점검</button>
            {ready?.conflicts.length && finished ? <button className="btn btn-sm" type="button" onClick={doResolve} disabled={busy || live}>에이전트에게 충돌 해결 맡기기</button> : null}
            <button className="btn btn-sm btn-danger" type="button" onClick={doDiscard} disabled={busy || live}>버리기</button>
            <select value={mode} onChange={(e) => setMode(e.target.value as "squash" | "merge")} aria-label="병합 방식" style={{ height: 26 }}>
              <option value="squash">한 커밋으로 (squash)</option><option value="merge">병합 커밋 (merge)</option>
            </select>
            <button className="btn btn-sm btn-primary" type="button" onClick={doMerge} disabled={busy || !ready?.can_merge}
                    title={ready && !ready.can_merge ? "막는 항목을 먼저 해결하세요" : undefined}>병합</button>
          </div>
        ) : null}
      </div>
      {tree.status === "merged" ? <div className="muted small">병합 커밋 <span className="mono">{(tree.merged_commit || "").slice(0, 10)}</span>
        {tree.patch ? <> · 커밋 안 한 변경은 <span className="mono">{tree.patch}</span> 에 남김</> : null} · 브랜치 <span className="mono">{tree.branch}</span> 는 남아 있습니다.</div> : null}
      {tree.status === "discarded" ? <div className="muted small">{tree.patch ? <>변경은 <span className="mono">{tree.patch}</span> 에 패치로 남겼습니다. </> : "남길 변경이 없었습니다. "}브랜치 <span className="mono">{tree.branch}</span> 는 남아 있습니다.</div> : null}
      {err ? <div className="alert alert-bad"><span>{err}</span></div> : null}
      {tree.status === "open" && ready ? (
        <ul className="checks">
          {ready.checks.map((c) => (
            <li key={c.key}><span className={`badge ${LEVEL[c.level].cls}`}>{LEVEL[c.level].text}</span><b>{c.label}</b>{c.detail ? <span className="faint small">{c.detail}</span> : null}</li>
          ))}
        </ul>
      ) : tree.status === "open" && !err ? <div className="faint small"><span className="spinner" /> 점검 중…</div> : null}
      {followups.length ? (
        <div className="row faint small" style={{ flexWrap: "wrap", gap: 6 }}>
          <span>후속 라운드</span>
          {followups.map((f) => (
            <span key={f.n} className="chip">{f.n}. {KIND[f.kind] || f.kind} · <span className="mono">{String(f.commit || "").slice(0, 7)}</span>
              {f.tests ? <> · <TestTag status={f.tests.status} /></> : null}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}
