// 벤치마크 (DESIGN.md 28.3·34장): 결과 폴더 목록과 결과 한 개(워크플로별 요약 + 실행별).
// 주소: #/bench, #/bench?dir=<결과 폴더>. 원격 머신은 &m=<id> (옛 화면과 같은 주소).
import { useEffect, useState } from "react";
import type { Group } from "../data";
import { api, LOCAL } from "../lib/api";
import { baseName, fmtDur, fmtTok, fmtWhen } from "../lib/format";
import { hrefRun } from "../lib/router";
import { ErrorBox, usePoll } from "../ui";
import "./bench.css";

interface BenchListItem {
  dir: string; name: string; suite?: string | null; workflows?: string[] | null; tasks?: string[] | null;
  repeat?: number | null; mock?: boolean | null; started?: string | null; runs: number; approved: number; all_passed: number;
}
interface Hidden {
  passed: number; failed?: number; errors?: number; total: number; uncollected?: number; all_passed: boolean;
  exit_code?: number; timed_out?: boolean;
}
interface BenchRow {
  task: string; kind?: string; workflow: string; rep: number; workdir?: string; seconds?: number; limit_wait_sec?: number;
  solo?: boolean; status: string; approved: boolean; arbiter?: string | null; stop_reason?: string | null;
  rounds?: number; calls?: number; run_dir?: string; own_tests?: string | null; hidden?: Hidden | null; error?: string | null;
  has_runs?: boolean; week_pct?: Record<string, number | null>;
}
interface WorkflowStat {
  workflow: string; runs: number; solo: boolean; approved: number; arbiter: number; hidden_rate: number; graded: number;
  all_passed: number; missed: number; rounds: number; seconds: number; calls: number;
  input: { claude: number; codex: number }; output: number; codex_equiv?: number;
  week_pct?: { claude: number | null; codex: number | null };
}
interface BenchResult {
  dir: string;
  meta: { suite?: string; tasks?: string[]; workflows?: string[]; repeat?: number; mock?: boolean; started?: string; fixed_design?: boolean };
  rows: BenchRow[];
  stats: WorkflowStat[];
}

const UNKNOWN = "모름";
const ROW_STATUS: Record<string, [string, string]> = {
  approved: ["승인", "ok"], unapproved: ["미승인", "warn"], stopped: ["중단", "wait"], failed: ["실패", "bad"],
  error: ["오류", "bad"], design_only: ["설계만", "info"], solo: ["혼자 완료", "info"],
};
const OWN_TESTS: Record<string, string> = { passed: "통과", failed: "실패", error: "실행 불가", timeout: "시간 초과" };

const enc = encodeURIComponent;
const hrefBench = (m: string, dir?: string) => {
  const q = [dir ? `dir=${enc(dir)}` : "", m !== LOCAL ? `m=${enc(m)}` : ""].filter(Boolean).join("&");
  return `#/bench${q ? `?${q}` : ""}`;
};

/** 라우터의 bench 경로는 머신을 갖지 않아서 주소의 m= 을 직접 읽는다. */
function useHashMachine(): string {
  const read = () => new URLSearchParams(location.hash.split("?")[1] || "").get("m") || LOCAL;
  const [m, setM] = useState(read);
  useEffect(() => {
    const on = () => setM(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return m;
}

const pctp = (v: number | null | undefined) => (typeof v === "number" ? `${v.toFixed(1)}%p` : UNKNOWN);

export function BenchView({ dir }: { dir?: string }) {
  const m = useHashMachine();
  return dir ? <BenchResultPage key={`${m}|${dir}`} dir={dir} m={m} /> : <BenchList key={m} m={m} />;
}

function MachineTabs({ current }: { current: string }) {
  const [groups, setGroups] = useState<Group[] | null>(null);
  useEffect(() => {
    let alive = true;
    api<{ machines: Group[] }>("/api/projects").then((r) => { if (alive) setGroups(r.machines || []); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!groups || groups.length < 2) return null;
  return (
    <nav className="tabs" aria-label="머신">
      {groups.map((g) => {
        const id = g.id || LOCAL;
        return (
          <a key={id} href={hrefBench(id)} className={id === current ? "active" : undefined} aria-current={id === current ? "page" : undefined}>
            {g.local ? "이 머신" : g.name}{g.error ? <span className="count">연결 안 됨</span> : null}
          </a>
        );
      })}
    </nav>
  );
}

function BenchList({ m }: { m: string }) {
  const [results, setResults] = useState<BenchListItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  usePoll(async () => {
    try {
      const d = await api<{ results: BenchListItem[] }>("/api/bench", { machine: m });
      setResults(d.results || []);
      setError(null);
    } catch (e) { setError(e); }
  }, null, [m]);

  return (
    <div className="page bench-page">
      <div className="page-head">
        <div>
          <h1>벤치마크</h1>
          <div className="muted">어떤 워크플로가 더 잘 만드는지 비교합니다. 같은 과제들을 워크플로마다 돌리고, 에이전트에게 보이지 않는 채점용 테스트(숨은 테스트)로 결과물을 채점합니다. 터미널에서 tenure bench run 으로 만듭니다.</div>
        </div>
      </div>
      <MachineTabs current={m} />
      {error ? <ErrorBox error={error} /> : null}
      {!results ? (!error ? <div className="empty"><span className="spinner" /></div> : null) : results.length === 0 ? (
        <div className="card empty">
          <p style={{ margin: "0 0 6px" }}>아직 벤치마크 결과가 없습니다.</p>
          <code>tenure bench run --suite hard --workflow classic --workflow lean --yes</code>
        </div>
      ) : (
        <div className="card table-scroll">
          <table className="list bench-table">
            <thead><tr>
              <th>결과</th><th>묶음</th><th>워크플로</th><th className="num">실행</th><th className="num">승인</th>
              <th className="num">숨은 테스트 전부 통과</th><th>시작</th><th>폴더</th>
            </tr></thead>
            <tbody>{results.map((r) => (
              <tr key={r.dir} className="go" onClick={() => { location.hash = hrefBench(m, r.dir); }}>
                <td className="nowrap">
                  <a href={hrefBench(m, r.dir)} onClick={(e) => e.stopPropagation()}>{r.name}</a>
                  {r.mock ? <span className="badge" style={{ marginLeft: 6 }}>mock</span> : null}
                </td>
                <td>{r.suite || UNKNOWN}</td>
                <td>{(r.workflows || []).join(", ") || UNKNOWN}</td>
                <td className="num">{r.runs}</td>
                <td className="num">{r.approved}/{r.runs}</td>
                <td className="num">{r.all_passed}/{r.runs}</td>
                <td className="nowrap small faint">{r.started ? fmtWhen(r.started) : UNKNOWN}</td>
                <td className="mono small faint bench-dir" title={r.dir}>{r.dir}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function BenchResultPage({ dir, m }: { dir: string; m: string }) {
  const [data, setData] = useState<BenchResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  usePoll(async () => {
    try {
      setData(await api<BenchResult>("/api/bench/result", { query: { dir }, machine: m }));
      setError(null);
    } catch (e) { setError(e); }
  }, null, [dir, m]);

  const crumbs = (
    <div className="crumbs"><a href={hrefBench(m)}>벤치마크</a><span className="sep">/</span><span>{baseName(dir)}</span></div>
  );
  if (!data) {
    return <div className="page bench-page">{crumbs}{error ? <ErrorBox error={error} /> : <div className="empty"><span className="spinner" /></div>}</div>;
  }
  const meta = data.meta || {};
  return (
    <div className="page bench-page">
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          {crumbs}
          <h1>{baseName(data.dir)}</h1>
          <div className="sub">{data.dir}</div>
        </div>
      </div>
      {error ? <ErrorBox error={error} /> : null}
      <div className="chips">
        <span className="chip">묶음 <b>{meta.suite || UNKNOWN}</b></span>
        <span className="chip">과제 {(meta.tasks || []).length}개 × 워크플로 {(meta.workflows || []).length}개 × {meta.repeat || 1}회</span>
        <span className="chip">실행 {data.rows.length}번</span>
        {meta.fixed_design ? <span className="chip">고정 설계</span> : null}
        {meta.mock ? <span className="badge">mock</span> : null}
        {meta.started ? <span className="chip">{fmtWhen(meta.started)}</span> : null}
      </div>

      <h2>워크플로별</h2>
      <StatsTable stats={data.stats || []} />

      <h2>실행별</h2>
      <RowsTable rows={data.rows || []} m={m} />

      <p className="muted small">
        숨은 테스트: 에이전트가 보지 못한 수용 테스트. 승인했는데 실패: 리뷰가 놓친 결함. 시간에서는 한도 대기 시간을 뺐습니다.
        solo-claude·solo-codex 는 에이전트 하나가 혼자 만든 기준선이라 리뷰·승인 칸이 ‘-’ 입니다.
        주간 사용률 변화는 실행 전후 7일 한도 사용률의 차이(기록된 실행만의 평균)입니다.
      </p>
    </div>
  );
}

function StatsTable({ stats }: { stats: WorkflowStat[] }) {
  if (!stats.length) return <div className="card empty">아직 실행이 없습니다.</div>;
  return (
    <div className="card table-scroll">
      <table className="list bench-table">
        <thead><tr>
          <th>워크플로</th><th className="num">실행</th><th className="num">승인</th><th className="num">중재 승인</th>
          <th className="num">숨은 테스트</th><th className="num">전부 통과</th><th className="num">승인했는데 실패</th>
          <th className="num">평균 라운드</th><th className="num">평균 시간</th><th className="num">평균 호출</th>
          <th className="num">입력 토큰 (Claude / Codex)</th><th className="num">출력 토큰</th>
          <th className="num">주간 사용률 변화 (Claude / Codex)</th>
        </tr></thead>
        <tbody>{stats.map((s) => (
          <tr key={s.workflow}>
            <td className="nowrap"><b>{s.workflow}</b>{s.solo ? <span className="badge" style={{ marginLeft: 6 }}>혼자</span> : null}</td>
            <td className="num">{s.runs}</td>
            <td className="num">{s.solo ? "-" : `${s.approved}/${s.runs}`}</td>
            <td className="num">{s.solo ? "-" : s.arbiter}</td>
            <td className="num" title={`${s.graded}개 채점`}>
              {s.graded ? <HiddenRate pct={s.hidden_rate} /> : <span className="faint">{UNKNOWN}</span>}
            </td>
            <td className="num">{s.all_passed}/{s.graded}</td>
            <td className={`num${!s.solo && s.missed ? " bench-bad" : ""}`}>{s.solo ? "-" : s.missed}</td>
            <td className="num">{s.solo ? "-" : s.rounds.toFixed(1)}</td>
            <td className="num nowrap">{fmtDur(s.seconds)}</td>
            <td className="num">{s.calls.toFixed(1)}</td>
            <td className="num nowrap">{fmtTok(s.input?.claude)} / {fmtTok(s.input?.codex)}</td>
            <td className="num">{fmtTok(s.output)}</td>
            <td className="num nowrap">{pctp(s.week_pct?.claude)} / {pctp(s.week_pct?.codex)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function HiddenRate({ pct }: { pct: number }) {
  const p = Math.max(0, Math.min(100, pct));
  return (
    <span className="bench-rate">
      <span className="bench-rate-bar" aria-hidden="true"><span style={{ width: `${p}%` }} /></span>
      {p.toFixed(0)}%
    </span>
  );
}

function hiddenTitle(h: Hidden): string {
  const parts = [`통과 ${h.passed}`];
  if (h.failed) parts.push(`실패 ${h.failed}`);
  if (h.errors) parts.push(`오류 ${h.errors}`);
  if (h.uncollected) parts.push(`불러오지 못한 테스트 ${h.uncollected}`);
  if (h.timed_out) parts.push("시간 초과");
  return parts.join(" · ");
}

function RowsTable({ rows, m }: { rows: BenchRow[]; m: string }) {
  if (!rows.length) return <div className="card empty">아직 실행이 없습니다.</div>;
  return (
    <div className="card table-scroll">
      <table className="list bench-table">
        <thead><tr>
          <th>과제</th><th>워크플로</th><th className="num">#</th><th>결과</th><th className="num">라운드</th>
          <th className="num">숨은 테스트</th><th>자체 테스트</th><th className="num">시간</th><th className="num">호출</th>
        </tr></thead>
        <tbody>{rows.map((r, i) => {
          const run = r.run_dir ? baseName(r.run_dir) : null;
          const link = !r.solo && r.has_runs && run && r.workdir ? hrefRun(m, r.workdir, run) : null;
          const [label, tone] = ROW_STATUS[r.status] || [r.status, ""];
          const h = r.hidden;
          const wait = r.limit_wait_sec || 0;
          return (
            <tr key={`${r.task}|${r.workflow}|${r.rep}|${i}`} className={link ? "go" : undefined}
                onClick={link ? () => { location.hash = link; } : undefined}>
              <td className="nowrap">
                {link ? <a href={link} onClick={(e) => e.stopPropagation()}>{r.task}</a> : r.task}
                {r.kind ? <span className="faint small"> · {r.kind}</span> : null}
              </td>
              <td className="nowrap">{r.workflow}</td>
              <td className="num">{r.rep}</td>
              <td>
                <span className={`badge ${tone}`} title={r.error || r.stop_reason || undefined}>
                  {label}{r.arbiter === "arbiter" ? " (중재)" : ""}
                </span>
              </td>
              <td className="num">{r.solo ? "-" : r.rounds || 0}</td>
              <td className={`num${h && !h.all_passed ? " bench-bad" : ""}`} title={h ? hiddenTitle(h) : "채점하지 않았습니다 (끝까지 가지 못한 실행)"}>
                {h ? `${h.passed}/${h.total}` : <span className="faint">채점 안 함</span>}
              </td>
              <td className="small">{r.own_tests ? OWN_TESTS[r.own_tests] || r.own_tests : <span className="faint">-</span>}</td>
              <td className="num nowrap" title={wait ? `한도 대기 ${fmtDur(wait)} 제외` : undefined}>
                {typeof r.seconds === "number" ? fmtDur(r.seconds - wait) : UNKNOWN}
              </td>
              <td className="num">{r.calls || 0}</td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}
