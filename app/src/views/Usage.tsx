// 사용량: 구독 한도(Claude·Codex)와 tenure 실행이 쓴 토큰. 로컬 기록만 읽으므로 사용량을 쓰지 않는다 (DESIGN.md 28.6).
import { useState } from "react";
import type { Group } from "../data";
import { api, LOCAL } from "../lib/api";
import { fmtDate, fmtDur, fmtTok, fmtUsd, fmtWhen } from "../lib/format";
import { hrefProject } from "../lib/router";
import { AgentTag, ErrorBox, usePoll } from "../ui";
import "./usage.css";

interface LimitWindow { used_percent?: number | null; window_minutes?: number | null; resets_at?: number | string | null }
interface CodexLimits { primary?: LimitWindow; secondary?: LimitWindow; plan_type?: string; reached?: string; as_of?: string }
interface ClaudeLimits { as_of?: string; limits?: Record<string, unknown> | null }
interface AgentUsage {
  input_tokens?: number; cached_input_tokens?: number; output_tokens?: number; reasoning_tokens?: number;
  cost_usd?: number; calls?: number;
}
interface LocalWindow { input_tokens?: number; output_tokens?: number; messages?: number }
interface UsageData {
  codex_limits: CodexLimits | null;
  claude_limits: ClaudeLimits | null;
  claude_local: { windows: Record<string, LocalWindow>; output_by_model_7d?: Record<string, number>; files?: number; as_of?: string };
  tenure: {
    by_agent: Record<string, AgentUsage>;
    by_day: Record<string, Record<string, AgentUsage>>;
    projects: { path: string; name: string; by_agent: Record<string, AgentUsage> }[];
  };
}

const UNKNOWN = "모름";

const TIPS = {
  codex_limit: "ChatGPT 구독의 Codex 사용 한도 중 얼마나 썼는지입니다. 100% 가 되면 초기화 시각까지 Codex 를 못 씁니다.",
  claude_tokens: "Claude 는 남은 한도를 따로 알려주지 않아서, tenure 가 Claude 를 부를 때 받은 한도(%)와 이 컴퓨터에서 쓴 양(토큰)을 보여줍니다. 남은 한도는 claude 를 켜고 /usage 로도 볼 수 있습니다.",
  duet_usage: "tenure 실행이 쓴 양만 따로 모았습니다.",
  tokens: "토큰은 AI 가 글을 세는 단위(글자 조각)입니다. 입력은 AI 가 읽은 양, 출력은 AI 가 쓴 양입니다.",
  usage_cost: "같은 양을 API 로 썼다면 드는 요금의 추정치입니다. 실제로 내는 구독 요금과는 별개입니다.",
};

// Claude 한도 창 이름 (rate_limit_info.unifiedWindows)
const CLAUDE_WINDOW_LABEL: Record<string, string> = {
  five_hour: "5시간 한도", seven_day: "7일 한도", seven_day_opus: "7일 한도 (Opus)", seven_day_sonnet: "7일 한도 (Sonnet)",
};
const CLAUDE_WINDOW_ORDER = ["five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"];

function windowLabel(min: number | null | undefined): string {
  const m = Number(min) || 0;
  if (!m) return "";
  if (m % 1440 === 0) return `${m / 1440}일`;
  if (m % 60 === 0) return `${m / 60}시간`;
  return `${m}분`;
}

/** 초기화 시각: 초 단위 epoch(Codex·Claude) 또는 ISO 문자열 */
function resetDate(v: number | string | null | undefined): Date | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : /^\d+(\.\d+)?$/.test(String(v)) ? Number(v) : NaN;
  const d = !isNaN(n) ? new Date(n > 1e12 ? n : n * 1000) : new Date(String(v));
  return isNaN(d.getTime()) ? null : d;
}

function resetLabel(v: number | string | null | undefined): string {
  const d = resetDate(v);
  if (!d) return "초기화 시각 모름";
  const left = (d.getTime() - Date.now()) / 1000;
  return `${fmtDate(d)} 초기화` + (left > 0 ? ` (${fmtDur(left)} 후)` : " (지남 — 다음 호출 때 갱신)");
}

const tok = (n: number | null | undefined) => (typeof n === "number" ? fmtTok(n) : UNKNOWN);
const isWindow = (v: unknown): v is LimitWindow => !!v && typeof v === "object" && "used_percent" in (v as object);

function Tip({ text }: { text: string }) {
  return <span className="usage-tip" tabIndex={0} role="note" title={text} aria-label={text}>?</span>;
}

function Meter({ label, w }: { label: string; w: LimitWindow }) {
  const known = typeof w.used_percent === "number" && isFinite(w.used_percent);
  const pct = known ? Math.max(0, Math.min(100, Number(w.used_percent))) : 0;
  const tone = pct >= 90 ? " high" : pct >= 70 ? " mid" : "";
  const win = windowLabel(w.window_minutes);
  return (
    <div className="meter">
      <div className="meter-label">
        <b>{label}{win ? ` (${win} 창)` : ""}</b>
        <span className={known ? undefined : "faint"}>{known ? `${pct.toFixed(0)}% 사용` : `사용률 ${UNKNOWN}`}</span>
      </div>
      <div className="meter-bar" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100}
           aria-valuenow={known ? Math.round(pct) : undefined} aria-valuetext={known ? `${pct.toFixed(0)}%` : UNKNOWN}>
        {known ? <div className={`meter-fill${tone}`} style={{ width: `${pct}%` }} /> : null}
      </div>
      <div className="muted small">{resetLabel(w.resets_at)}</div>
    </div>
  );
}

function MachineTabs({ current, groups }: { current: string; groups: Group[] | null }) {
  if (!groups || groups.length < 2) return null;
  return (
    <nav className="tabs" aria-label="머신">
      {groups.map((g) => {
        const id = g.id || LOCAL;
        return (
          <a key={id} href={`#/usage?m=${encodeURIComponent(id)}`} className={id === current ? "active" : undefined}
             aria-current={id === current ? "page" : undefined}>
            {g.local ? "이 머신" : g.name}{g.error ? <span className="count">연결 안 됨</span> : null}
          </a>
        );
      })}
    </nav>
  );
}

function agentOrder(names: Iterable<string>): string[] {
  const rank = (a: string) => { const b = a.replace(/^mock-/, ""); return b === "claude" ? 0 : b === "codex" ? 1 : 2; };
  return [...new Set(names)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

export function UsageView({ machine, groups }: { machine: string; groups: Group[] | null }) {
  const m = machine || LOCAL;
  const [data, setData] = useState<UsageData | null>(null);
  const [loadedFor, setLoadedFor] = useState<string>("");
  const [error, setError] = useState<unknown>(null);
  usePoll(async () => {
    try {
      const u = await api<UsageData>("/api/usage", { machine: m });
      setData(u);
      setLoadedFor(m);
      setError(null);
    } catch (e) { setError(e); }
  }, 30000, [m]);

  const current = loadedFor === m ? data : null;
  const machineName = groups?.find((g) => (g.id || LOCAL) === m);
  return (
    <div className="page usage-page">
      <div className="page-head">
        <div>
          <h1>사용량{machineName && !machineName.local ? <span className="faint"> · {machineName.name}</span> : null}</h1>
          <div className="muted">구독 한도와 tenure 실행이 쓴 토큰을 봅니다. 로컬 기록만 읽으므로 사용량을 쓰지 않습니다. 30초마다 다시 읽습니다.</div>
        </div>
      </div>
      <MachineTabs current={m} groups={groups} />
      {error ? <ErrorBox error={error} /> : null}
      {!current ? (!error ? <div className="empty"><span className="spinner" /></div> : null) : (
        <>
          <CodexCard cl={current.codex_limits} />
          <ClaudeCard limits={current.claude_limits} local={current.claude_local} />
          <TenureCard usage={current.tenure} machine={m} />
        </>
      )}
    </div>
  );
}

function CodexCard({ cl }: { cl: CodexLimits | null }) {
  return (
    <section className="card usage-card">
      <div className="row">
        <h2>Codex 구독 한도</h2><Tip text={TIPS.codex_limit} />
        {cl?.plan_type ? <span className="chip">{cl.plan_type}</span> : null}
        <span className="spacer" />
        {cl?.as_of ? <span className="muted small">기준 {fmtWhen(cl.as_of)}</span> : null}
      </div>
      {cl ? (
        <>
          {cl.primary ? <Meter label="주 한도" w={cl.primary} /> : null}
          {cl.secondary ? <Meter label="보조 한도" w={cl.secondary} /> : null}
          {!cl.primary && !cl.secondary ? <p className="muted">한도 사용률: {UNKNOWN}</p> : null}
          {cl.reached ? <div className="alert alert-bad"><b>한도 도달</b><span>{cl.reached}</span></div> : null}
        </>
      ) : <p className="muted">최근 Codex 세션 기록이 없어 한도를 {UNKNOWN}. Codex 를 한 번 쓰면 보입니다.</p>}
      <p className="usage-desc">Codex 가 남긴 마지막 세션 기록 기준입니다(tenure 밖에서 쓴 것 포함).</p>
    </section>
  );
}

function ClaudeCard({ limits, local }: { limits: ClaudeLimits | null; local: UsageData["claude_local"] }) {
  const lim = limits?.limits && typeof limits.limits === "object" ? limits.limits : null;
  const windows = lim
    ? Object.entries(lim).filter((e): e is [string, LimitWindow] => isWindow(e[1]))
        .sort(([a], [b]) => {
          const ia = CLAUDE_WINDOW_ORDER.indexOf(a), ib = CLAUDE_WINDOW_ORDER.indexOf(b);
          return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
        })
    : [];
  const status = lim && typeof lim.status === "string" ? lim.status : "";
  const type = lim && typeof lim.type === "string" ? lim.type : "";
  const noRecords = local.files === 0;
  const byModel = Object.entries(local.output_by_model_7d || {}).sort((a, b) => b[1] - a[1]);
  return (
    <section className="card usage-card">
      <div className="row">
        <h2>Claude Code 사용량</h2><Tip text={TIPS.claude_tokens} />
        <span className="spacer" />
        {limits?.as_of ? <span className="muted small">한도 기준 {fmtWhen(limits.as_of)}</span> : null}
      </div>
      {windows.map(([name, w]) => <Meter key={name} label={CLAUDE_WINDOW_LABEL[name] || name} w={w} />)}
      {lim && !windows.length ? <p className="muted">한도 사용률: {UNKNOWN}</p> : null}
      {status === "rejected" ? (
        <div className="alert alert-bad"><b>한도 도달</b>
          <span>{CLAUDE_WINDOW_LABEL[type] || type || "어느 한도인지 모름"}{lim?.resets_at ? ` · ${resetLabel(lim.resets_at as number | string)}` : ""}</span></div>
      ) : status === "allowed_warning" ? (
        <div className="alert alert-warn"><b>한도 임박</b><span>{CLAUDE_WINDOW_LABEL[type] || type || "곧 한도에 닿습니다"}</span></div>
      ) : null}
      <div className="usage-stats">
        {Object.entries(local.windows || {}).map(([name, w]) => (
          <div key={name} className="card usage-stat">
            <span className="k">최근 {name}</span>
            <span className="v">출력 {noRecords ? UNKNOWN : tok(w.output_tokens)}</span>
            <span className="s">입력 {noRecords ? UNKNOWN : tok(w.input_tokens)} · 응답 {noRecords || typeof w.messages !== "number" ? UNKNOWN : `${w.messages}개`}</span>
          </div>
        ))}
      </div>
      {noRecords ? <p className="muted small">이 머신에서 최근 7일 동안의 Claude Code 기록을 찾지 못해 토큰은 {UNKNOWN}입니다.</p> : null}
      {byModel.length ? (
        <div className="table-scroll">
          <table className="list usage-table">
            <thead><tr><th>모델 (7일)</th><th className="num">출력 토큰</th></tr></thead>
            <tbody>{byModel.map(([model, n]) => <tr key={model}><td className="mono">{model}</td><td className="num">{fmtTok(n)}</td></tr>)}</tbody>
          </table>
        </div>
      ) : null}
      <p className="usage-desc">
        {windows.length
          ? "한도(%)는 tenure 가 Claude 를 마지막으로 부를 때 받은 값입니다. 토큰은 이 머신의 Claude Code 기록(tenure 밖 사용 포함)을 합산했습니다."
          : "한도(%)는 tenure 가 Claude 를 한 번 부르면 보입니다. 토큰은 이 머신의 Claude Code 기록에서 합산했습니다."}
      </p>
    </section>
  );
}

function TenureCard({ usage, machine }: { usage: UsageData["tenure"]; machine: string }) {
  const agents = agentOrder(Object.keys(usage.by_agent || {}));
  const days = Object.entries(usage.by_day || {});
  const dayMax = Math.max(1, ...days.map(([, a]) => agents.reduce((s, ag) => s + (a[ag]?.output_tokens || 0), 0)));
  const outCell = (u: AgentUsage | undefined) =>
    u ? `${tok(u.output_tokens)} (${typeof u.calls === "number" ? `${u.calls}회` : `호출 ${UNKNOWN}`})` : "-";
  return (
    <section className="card usage-card">
      <div className="row"><h2>tenure 실행이 쓴 양</h2><Tip text={TIPS.duet_usage} /></div>
      {agents.length ? (
        <>
          <div className="table-scroll">
            <table className="list usage-table">
              <thead><tr>
                <th>에이전트</th><th className="num">호출</th>
                <th className="num">입력 토큰 <Tip text={TIPS.tokens} /></th><th className="num">출력 토큰</th>
                <th className="num">API 환산 <Tip text={TIPS.usage_cost} /></th>
              </tr></thead>
              <tbody>{agents.map((a) => {
                const t = usage.by_agent[a];
                return (
                  <tr key={a}>
                    <td><AgentTag name={a} /></td>
                    <td className="num">{typeof t.calls === "number" ? t.calls : UNKNOWN}</td>
                    <td className="num" title={typeof t.cached_input_tokens === "number" && t.cached_input_tokens ? `그중 캐시 ${fmtTok(t.cached_input_tokens)}` : undefined}>{tok(t.input_tokens)}</td>
                    <td className="num" title={t.reasoning_tokens ? `그중 추론 ${fmtTok(t.reasoning_tokens)}` : undefined}>{tok(t.output_tokens)}</td>
                    <td className="num">{fmtUsd(t.cost_usd) || <span className="faint" title="이 에이전트는 요금 추정치를 알려주지 않습니다">{UNKNOWN}</span>}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>

          <h3>날짜별 출력 (최근 14일)</h3>
          <div className="table-scroll">
            <table className="list usage-table">
              <thead><tr>
                <th>날짜</th>{agents.map((a) => <th key={a} className="num">{a} 출력</th>)}<th className="usage-bar-col" aria-label="비율" />
              </tr></thead>
              <tbody>{days.map(([day, per]) => (
                <tr key={day || "unknown"}>
                  <td className="nowrap">{day || `날짜 ${UNKNOWN}`}</td>
                  {agents.map((a) => <td key={a} className="num nowrap">{outCell(per[a])}</td>)}
                  <td className="usage-bar-col">
                    <div className="usage-bar" aria-hidden="true">
                      {agents.map((a, i) => {
                        const v = per[a]?.output_tokens || 0;
                        return v ? <span key={a} className={`seg seg-${Math.min(i, 2)}`} style={{ width: `${(v / dayMax) * 100}%` }} title={`${a} ${fmtTok(v)}`} /> : null;
                      })}
                    </div>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {agents.length > 1 ? (
            <div className="row small faint usage-legend">
              {agents.map((a, i) => <span key={a} className="row"><span className={`swatch seg-${Math.min(i, 2)}`} />{a}</span>)}
            </div>
          ) : null}

          <h3>프로젝트별 출력</h3>
          <div className="table-scroll">
            <table className="list usage-table">
              <thead><tr><th>프로젝트</th>{agents.map((a) => <th key={a} className="num">{a} 출력</th>)}</tr></thead>
              <tbody>{usage.projects.map((p) => (
                <tr key={p.path} onClick={() => { location.hash = hrefProject(machine, p.path); }}>
                  <td><a href={hrefProject(machine, p.path)} title={p.path} onClick={(e) => e.stopPropagation()}>{p.name}</a></td>
                  {agents.map((a) => <td key={a} className="num nowrap">{outCell(p.by_agent[a])}</td>)}
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      ) : <p className="muted">아직 사용량이 기록된 실행이 없습니다. 사용량 기록이 생긴 뒤의 실행부터 보입니다.</p>}
      <p className="usage-desc">API 환산은 Claude 가 알려주는 같은 양의 API 요금 추정치이며, 구독 요금과는 다릅니다. ‘-’ 는 그날(그 프로젝트에서) 그 에이전트의 기록이 없다는 뜻입니다.</p>
    </section>
  );
}
