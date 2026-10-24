import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Diff } from "../lib/markdown";
import { AgentTag, TestTag, useUi } from "../ui";

/** 경쟁 초안 비교 (DESIGN.md 36.15, Daintree CrossWorktreeDiff 의 아이디어). */
interface Draft {
  branch: string; head: string; status: string; approved: boolean; blocking: number | null;
  tests: string | null; tests_summary?: string | null; lines: number; files: number;
  review_file?: string | null; reviewer: string; calls: number; sec: number;
}
export interface RaceInfo {
  drafters: string[]; base: string; drafts: Record<string, Draft>; winner?: string; loser?: string; reason?: string;
  picked?: string; picks?: { role: string; prev: string; kept: string }[];
}

export function DraftsPanel({ m, q, race, roles, canPick, onReload }: {
  m: string; q: Record<string, string>; race: RaceInfo; roles: Record<string, string>; canPick: boolean; onReload: () => void;
}) {
  const { toast, confirm } = useUi();
  const [diffs, setDiffs] = useState<Record<string, { text: string; truncated: boolean; title: string } | null>>({});
  const order = race.drafters.filter((r) => race.drafts[r]);
  const current = race.picked || race.winner;
  useEffect(() => {
    for (const r of order) {
      api<{ text: string; truncated: boolean; title: string }>("/api/diff", { query: { ...q, draft: r }, machine: m })
        .then((d) => setDiffs((x) => ({ ...x, [r]: d }))).catch((e) => setDiffs((x) => ({ ...x, [r]: { text: String(e.message), truncated: false, title: "오류" } })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m, q, race.base, order.join(",")]);
  if (!order.length) return <div className="card empty">초안이 아직 끝나지 않았습니다.</div>;
  const pick = async (role: string) => {
    if (!(await confirm(`코드를 ${role} 초안(${race.drafts[role].branch})으로 바꿉니다. 지금 상태는 브랜치로 남깁니다.\n${current} 초안에서 이어진 고치기 라운드의 결과는 이 실행에서 빠집니다.`, { ok: "바꾸기" }))) return;
    try {
      const r = await api<{ kept: string }>("/api/actions/pick", { method: "POST", body: { ...q, draft: role }, machine: m });
      toast(`${role} 초안으로 바꿨습니다. 이전 상태: ${r.kept}`);
      onReload();
    } catch (e) { toast((e as Error).message, true); }
  };
  return (
    <div className="col" style={{ gap: 12 }}>
      <section className="card card-pad row" style={{ flexWrap: "wrap" }}>
        <b>판정</b>
        {race.winner ? <span><AgentTag name={roles[race.winner] || race.winner} role={race.winner} /> 초안 채택 — {race.reason}</span> : <span className="faint">진행 중</span>}
        {race.picked && race.picked !== race.winner ? <span className="badge warn">사람이 {race.picked} 초안으로 바꿈</span> : null}
        <span className="faint small">판정은 테스트 → 상대 리뷰 승인 → 막는 지적 → 바뀐 줄 수 순 (모델 호출 없음)</span>
      </section>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${order.length}, minmax(0, 1fr))`, gap: 12, alignItems: "start" }}>
        {order.map((r) => {
          const d = race.drafts[r];
          const diff = diffs[r];
          return (
            <section key={r} className={`card col${r === current ? " draft-current" : ""}`} style={{ gap: 0 }}>
              <div className="card-pad col" style={{ gap: 8 }}>
                <div className="row" style={{ flexWrap: "wrap" }}>
                  <AgentTag name={roles[r] || r} role={r} /><b>초안</b>
                  {r === current ? <span className="badge ok">채택</span> : null}
                  <span className="spacer" />
                  {canPick && r !== current ? <button className="btn btn-sm" type="button" onClick={() => pick(r)}>이 초안으로 바꾸기</button> : null}
                </div>
                <div className="chips">
                  <span className="chip">테스트 {d.tests ? <TestTag status={d.tests} /> : <b>명령 없음</b>}</span>
                  <span className="chip">{d.reviewer} 리뷰 {d.approved ? <span className="verdict v-APPROVED">승인</span> : <span className="verdict v-CHANGES_REQUESTED">반려{d.blocking ? ` ${d.blocking}` : ""}</span>}</span>
                  <span className="chip">파일 {d.files} · 줄 {d.lines}</span>
                  <span className="chip">호출 {d.calls}회</span>
                  <span className="chip mono">{d.branch}</span>
                </div>
              </div>
              <div className="dialog-head"><b className="ellipsis small">{diff?.title || "불러오는 중…"}</b>{diff?.truncated ? <span className="badge warn">일부만</span> : null}</div>
              {diff ? <Diff text={diff.text} /> : <div className="empty"><span className="spinner" /></div>}
            </section>
          );
        })}
      </div>
    </div>
  );
}
