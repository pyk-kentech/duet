import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtWhen } from "../lib/format";

/** 아래 상태 막대 (오르카 StatusBar, 36.22): Claude·Codex 한도(5시간·주), 동시 에이전트 자리, 엔진 연결. 모르면 '모름'. */
interface Win { used_percent: number; resets_at?: string | number | null; window_minutes?: number | null }
interface Limits {
  codex: { primary?: Win; secondary?: Win; as_of?: string } | null;
  claude: { as_of?: string; limits?: Record<string, Win | string> } | null;
  slots: { busy: number; max: number };
}

function Meter({ label, w }: { label: string; w?: Win | null }) {
  if (!w || typeof w.used_percent !== "number") return <span className="bar-seg" title={`${label}: 아직 기록 없음`}>{label} 모름</span>;
  const p = Math.max(0, Math.min(100, w.used_percent));
  const cls = p >= 95 ? " bad" : p >= 80 ? " warn" : "";
  const reset = w.resets_at ? (typeof w.resets_at === "number" ? new Date(w.resets_at * 1000).toISOString() : String(w.resets_at)) : "";
  return (
    <span className="bar-seg" title={`${label} ${p.toFixed(0)}% 사용${reset ? ` · 다시 채워짐 ${reset.replace("T", " ").slice(5, 16)}` : ""}`}>
      <span className={`meter${cls}`}><i style={{ width: `${p}%` }} /></span>{label} {p.toFixed(0)}%
    </span>
  );
}

export default function StatusBar() {
  const [lim, setLim] = useState<Limits | null>(null);
  const [ok, setOk] = useState(true);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try { const l = await api<Limits>("/api/limits"); if (alive) { setLim(l); setOk(true); } }
      catch { if (alive) setOk(false); }
    };
    tick();
    const id = window.setInterval(() => { if (!document.hidden) tick(); }, 30_000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);
  const cl = (lim?.claude?.limits || {}) as Record<string, Win>;
  const cx = lim?.codex || null;
  return (
    <footer className="bar" aria-label="상태">
      <span className="bar-seg"><img src="/logos/claude.svg" alt="" width={12} height={12} /><b>Claude</b></span>
      <Meter label="5시간" w={cl.five_hour} /><Meter label="주" w={cl.seven_day} />
      {lim?.claude?.as_of ? <span className="bar-seg" title="tenure 가 Claude 를 부를 때마다 갱신">{fmtWhen(lim.claude.as_of)}</span> : null}
      <span className="bar-seg" style={{ marginLeft: 6 }}><img src="/logos/codex.svg" alt="" width={12} height={12} /><b>Codex</b></span>
      <Meter label="5시간" w={cx?.primary} /><Meter label="주" w={cx?.secondary} />
      <span className="spacer" />
      {lim ? <span className="bar-seg" title="이 머신의 모든 tenure 실행을 합친 동시 에이전트 수 / 상한">에이전트 {lim.slots.busy}/{lim.slots.max}</span> : null}
      <span className="bar-seg" title={ok ? "엔진과 연결됨" : "엔진에 연결할 수 없습니다"}><span className={ok ? "dot-ok" : "dot-bad"} />{ok ? "연결됨" : "끊김"}</span>
    </footer>
  );
}
