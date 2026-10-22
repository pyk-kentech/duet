// 설정 화면: 화면 테마·로고, 작업 폴더 위치, 기본 실행 설정, 고급 설정(설정 항목 정의에서 만든다), 원격 머신, UI 서버.
// 값은 ~/.tenure/settings.json 에 저장된다 (테마만 이 브라우저의 localStorage).
import { KeyboardEvent as ReactKeyboardEvent, ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { api, LOCAL } from "../lib/api";
import { fmtDur } from "../lib/format";
import { STEP } from "../lib/labels";
import { ErrorBox, Modal, useUi } from "../ui";
import "./settings.css";

// ---------------------------------------------------------------- 서버 응답 모양
export interface OptionDef {
  key: string; label: string; help: string; kind: "bool" | "int" | "choice" | "text" | string;
  group: string; group_label: string; choices: string[]; min: number | null; max: number | null;
  run_dialog: boolean; effective: unknown; default: unknown;
}
interface ModelSugg { id: string; label?: string; note?: string; efforts?: string[]; default_effort?: string | null }
interface AgentSugg { models: ModelSugg[]; efforts: string[]; cli_default: string | null }
type Agent = "claude" | "codex";
export interface Machine { id: string; name?: string; ssh: string; port?: number; workspace_root?: string; python?: string }
interface SettingsData { workspace_roots: string[]; defaults: Record<string, any>; machines: Machine[] }
interface EffAgent {
  model: string; model_base: string; step_model: Record<string, string>;
  effort: string; effort_label: string; effort_base: string; step_effort: Record<string, string>;
}
interface SettingsResp {
  settings: SettingsData; error: string | null;
  suggestions: Record<Agent, AgentSugg>;
  effective: Record<string, any> & { claude?: EffAgent; codex?: EffAgent; limits?: { debate_rounds: number; max_review: number }; error?: string };
  options: OptionDef[];
}
export interface ServerInfo {
  version: string; loaded: string; current: string; stale: boolean; uptime_sec: number;
  running_terms: string[]; logos: Record<string, boolean>; native_picker: boolean;
}
export interface ProbeInfo {
  reachable: boolean; error?: string; hint?: string; uname?: string; python?: string;
  deployed?: boolean; up_to_date?: boolean; remote_hash?: string; local_hash?: string;
}

// ---------------------------------------------------------------- 쉬운 설명 (옛 화면의 ? 도움말)
export const TIPS: Record<string, string> = {
  roots: "새 실행에서 고를 수 있는 상위 폴더 목록입니다. 첫 번째가 기본으로 선택됩니다.",
  implementer: "코드를 직접 작성하고, 리뷰를 받으면 고치는 AI 입니다.",
  reviewer: "작성된 코드를 읽고 검사해서 승인하거나 반려하는 AI 입니다. 파일은 고칠 수 없습니다.",
  synth: "두 AI 의 설계안을 하나의 최종 설계(DESIGN.md)로 합치는 AI 입니다. 기본은 리뷰 담당이 합칩니다.",
  debate_rounds: "두 AI 가 서로의 설계안을 비판하고 고치는 횟수입니다. 0 이면 비판 없이 바로 합칩니다. 1 늘릴 때마다 AI 호출이 2번 늘어납니다.",
  max_review: "\"구현 → 리뷰\"를 최대 몇 번 반복할지입니다. 그 전에 승인되면 바로 끝납니다.",
  claude_model: "Claude 의 어떤 모델을 쓸지 정합니다. 비워 두면 Claude 가 평소 쓰는 기본 모델입니다.",
  codex_model: "Codex(ChatGPT)의 어떤 모델을 쓸지 정합니다. 비워 두면 기본 모델입니다.",
  effort: "AI 가 얼마나 깊게 생각할지입니다. 높을수록 꼼꼼하지만 느리고 사용량을 더 씁니다. 단계별 기본은 단계마다 정해진 강도를 씁니다(Codex: 설계 종합·첫 리뷰 high, 나머지 medium). 값을 고르면 모든 단계에 그 값을 씁니다.",
  test_command: "구현이 끝날 때마다 tenure 가 직접 돌릴 테스트 명령입니다. 비우면 프로젝트를 보고 알아서 찾습니다. none 이라고 쓰면 테스트를 하지 않습니다.",
  block_severity: "어느 정도 문제까지 반려할지입니다. P1 = 동작 안 함·보안 문제, P2 = 설계와 다름·흔한 입력에서 오류, P3 = 드문 입력·사소한 개선. 기본(P1·P2)은 사소한 것만 남으면 승인합니다.",
  stall_rounds: "리뷰에서 고칠 것이 이 횟수만큼 연속으로 줄지 않으면 멈추고 사람에게 넘깁니다. 끝없이 반려만 반복되는 걸 막습니다. 0 이면 이 기능을 끕니다.",
  require_tests: "켜 두면 테스트가 실패했을 때 리뷰어가 승인해도 승인하지 않습니다.",
  review_diff: "켜 두면 2번째 리뷰부터 지난 리뷰 이후 바뀐 부분만 리뷰어에게 보여줍니다. 리뷰 한 번에 드는 토큰이 크게 줄어듭니다.",
  repro_tests: "켜 두면 리뷰어가 지적을 \"실패하는 테스트\"로 낼 수 있습니다. tenure 가 저장해 돌려 보고, 구현자는 그 테스트를 통과시켜야 합니다.",
  "machine.id": "이 머신을 부를 짧은 영문 이름입니다(예: lab). 나중에 바꿀 수 없습니다.",
  "machine.name": "화면에 보일 이름입니다(예: 연구실 서버).",
  "machine.ssh": "접속 주소입니다. 사용자@호스트 형식(예: me@lab.example.com). 비밀번호 없이 접속되게 미리 ssh-copy-id 를 해 두세요.",
  "machine.port": "SSH 포트입니다. 보통 22 입니다.",
  "machine.root": "원격 머신에서 프로젝트 폴더를 만들 위치입니다(예: ~/tenure-projects).",
  deploy: "이 컴퓨터의 tenure 를 원격 머신에 복사합니다. tenure 를 업데이트한 뒤에도 누르세요.",
  restart: "UI 서버를 다시 켭니다. 같은 주소로 다시 뜨고, 진행 중인 실행은 영향이 없습니다.",
  update: "tenure 프로그램이 바뀌었습니다. 다시 시작해야 새 기능이 화면에 나옵니다.",
};

// ---------------------------------------------------------------- 색 테마 (이 브라우저에만 저장)
const THEME_KEY = "tenure.theme";
type ThemeId = "system" | "light" | "dark";
const THEMES: { id: ThemeId; label: string; note: string; sw: [string, string, string] }[] = [
  { id: "system", label: "시스템", note: "운영체제 설정을 따라감", sw: ["#f6f7f9", "#0f1115", "#7b8597"] },
  { id: "light", label: "밝게", note: "밝은 배경", sw: ["#f6f7f9", "#ffffff", "#121826"] },
  { id: "dark", label: "어둡게", note: "어두운 배경", sw: ["#0f1115", "#161920", "#e7eaf0"] },
];
// 옛 화면의 테마 이름(페이퍼·슬레이트·미드나잇)은 가까운 쪽으로 읽는다
const LEGACY_THEME: Record<string, ThemeId> = { light: "light", paper: "light", slate: "light", dark: "dark", midnight: "dark", system: "system" };

function readTheme(): ThemeId {
  try {
    return LEGACY_THEME[localStorage.getItem(THEME_KEY) || "system"] || "system";
  } catch {
    return "system";
  }
}
function setThemeAttr(id: ThemeId) {
  if (id === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = id;
}
/** 저장된 테마를 화면에 적용한다 (main.tsx 에서 처음 그리기 전에 부른다). */
export function applyStoredTheme(): void {
  setThemeAttr(readTheme());
}
function saveTheme(id: ThemeId) {
  setThemeAttr(id);
  try { localStorage.setItem(THEME_KEY, id); } catch { /* 저장 못 해도 지금 화면은 바뀐다 */ }
}

// ---------------------------------------------------------------- 작은 부품
/** ? 도움말. 누르거나 마우스를 올리면 설명이 뜬다 (휴대폰은 누르기). */
export function Help({ text }: { text?: string }) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const pinned = useRef(false);
  const show = () => {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const w = Math.min(300, window.innerWidth - 16);
    setPos({ top: r.bottom + 6, left: Math.max(8, Math.min(r.left - 8, window.innerWidth - w - 8)) });
  };
  const hide = () => { pinned.current = false; setPos(null); };
  useEffect(() => {
    if (!pos) return;
    const onDown = (e: MouseEvent) => { if (!btn.current?.contains(e.target as Node)) hide(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") hide(); };
    document.addEventListener("mousedown", onDown, true);
    document.addEventListener("scroll", hide, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", hide);
    return () => {
      document.removeEventListener("mousedown", onDown, true);
      document.removeEventListener("scroll", hide, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", hide);
    };
  }, [pos]);
  if (!text) return null;
  return (
    <>
      <button ref={btn} type="button" className="help-q" aria-label={`도움말: ${text}`} aria-expanded={!!pos}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (pos && pinned.current) hide(); else { pinned.current = true; show(); } }}
              onMouseEnter={() => { if (!pos) show(); }} onMouseLeave={() => { if (!pinned.current) setPos(null); }}
              onBlur={() => { if (!pinned.current) setPos(null); }}>?</button>
      {pos ? <span className="help-pop" role="tooltip" style={{ top: pos.top, left: pos.left }}>{text}</span> : null}
    </>
  );
}

/** 이름 + 도움말 + 입력 칸. label 안에 도움말 버튼을 넣으면 이름을 눌렀을 때 도움말이 눌려서 이렇게 나눈다. */
function Field({ label, tip, children, id }: { label: string; tip?: string; children: ReactNode; id?: string }) {
  return (
    <div className="set-field">
      <div className="set-field-label">{id ? <label htmlFor={id}>{label}</label> : <span>{label}</span>}<Help text={tip} /></div>
      {children}
    </div>
  );
}

export function Segmented({ value, options, onChange, label, disabled }: {
  value: string; options: { value: string; label: string }[]; onChange: (v: string) => void; label: string; disabled?: boolean;
}) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={o.value === value} className={o.value === value ? "on" : undefined}
                disabled={disabled} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

function Logo({ agent, size = 18 }: { agent: string; size?: number }) {
  const base = agent.replace(/^mock-/, "");
  if (base !== "claude" && base !== "codex") return <span className="logo-badge" style={{ width: size, height: size }}>{(base[0] || "?").toUpperCase()}</span>;
  return <img src={`/logos/${base}.svg`} alt="" width={size} height={size} className="logo-img" />;
}

const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));
const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

// ---------------------------------------------------------------- 화면
export function SettingsView() {
  const { toast } = useUi();
  const [v, setV] = useState<SettingsResp | null>(null);
  const [server, setServer] = useState<ServerInfo | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [ver, setVer] = useState<Record<string, number>>({});

  const load = useCallback(async () => {
    try {
      const [s, sv] = await Promise.all([
        api<SettingsResp>("/api/settings"),
        api<ServerInfo>("/api/server").catch(() => null),
      ]);
      setV(s);
      setServer(sv);
      setError(null);
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { load(); }, [load]);

  /** 카드 하나를 저장한다. 저장한 카드만 새 값으로 다시 그리고, 다른 카드에서 고치던 값은 그대로 둔다. */
  const save = useCallback(async (card: string, body: Record<string, unknown>): Promise<boolean> => {
    try {
      const nv = await api<SettingsResp>("/api/settings", { method: "POST", body });
      setV(nv);
      setVer((x) => ({ ...x, [card]: (x[card] || 0) + 1 }));
      toast("저장했습니다.");
      return true;
    } catch (e) {
      toast(errMsg(e), true);
      return false;
    }
  }, [toast]);

  return (
    <div className="page settings-page">
      <div className="page-head">
        <div>
          <h1>설정</h1>
          <div className="muted">~/.tenure/settings.json 에 저장됩니다. 화면 테마만 이 브라우저에 저장됩니다.</div>
        </div>
      </div>
      {error ? <ErrorBox error={error} /> : null}
      {v?.error ? <div className="alert alert-bad"><b>설정 파일 오류</b><span>{v.error}</span></div> : null}
      {v?.effective?.error ? <div className="alert alert-warn"><b>기본 설정 오류</b><span>{v.effective.error}</span></div> : null}

      <ScreenCard server={server} />
      {!v ? (!error ? <div className="card empty"><span className="spinner" /> 불러오는 중…</div> : null) : (
        <>
          <RootsCard key={`roots-${ver.roots || 0}`} initial={v.settings.workspace_roots || []} nativePicker={!!server?.native_picker}
                     onSave={(roots) => save("roots", { workspace_roots: roots })} />
          <DefaultsCard key={`defaults-${ver.defaults || 0}`} v={v} onSave={(d) => save("defaults", { defaults: d })} />
          <AdvancedCard key={`options-${ver.options || 0}`} options={v.options || []} defaults={v.settings.defaults || {}}
                        onSave={(o) => save("options", { options: o })} />
          <MachinesCard machines={v.settings.machines || []} onChanged={setV} reload={load} />
        </>
      )}
      <ServerCard server={server} reload={load} />
    </div>
  );
}

// ---------------------------------------------------------------- 화면: 색 테마와 로고
function ScreenCard({ server }: { server: ServerInfo | null }) {
  const [theme, setTheme] = useState<ThemeId>(readTheme);
  const logos = server?.logos || { claude: true, codex: true };
  return (
    <section className="card card-pad col">
      <div className="row"><h2>화면</h2></div>
      <p className="muted small set-desc">색 테마는 이 브라우저에만 저장됩니다(서버·다른 사람과 공유하지 않음). 배경·글자색만 바뀌고 배치는 같습니다.</p>
      <div className="theme-grid" role="radiogroup" aria-label="색 테마">
        {THEMES.map((t) => (
          <button key={t.id} type="button" role="radio" aria-checked={theme === t.id} className={`theme-card${theme === t.id ? " on" : ""}`}
                  onClick={() => { saveTheme(t.id); setTheme(t.id); }}>
            <span className="theme-swatch" style={{ background: t.id === "system" ? `linear-gradient(135deg, ${t.sw[0]} 50%, ${t.sw[1]} 50%)` : t.sw[0] }}>
              {t.id !== "system" ? <i className="sw-panel" style={{ background: t.sw[1], boxShadow: `inset 0 0 0 1px ${t.sw[2]}22` }} /> : null}
              <i className="sw-dot" style={{ background: t.sw[2] }} />
            </span>
            <span className="theme-name">{t.label}<small>{t.note}</small></span>
          </button>
        ))}
      </div>
      <h3 style={{ marginTop: 6 }}>Claude·Codex 표시</h3>
      <div className="row" style={{ flexWrap: "wrap", gap: 14 }}>
        {(["claude", "codex"] as const).map((a) => (
          <span key={a} className="chip"><Logo agent={a} size={16} /><b>{a === "claude" ? "Claude" : "Codex"}</b>{logos[a] ? "" : " (기본 표시)"}</span>
        ))}
      </div>
      <p className="muted small set-desc">
        이 그림은 tenure 에 함께 배포된 것을 씁니다. 바꾸려면 <code>$TENURE_HOME/logos/claude.svg</code>·<code>codex.svg</code>(기본 위치
        <code> ~/.tenure/logos/</code>, 300KB 이하)를 넣으세요. 넣은 파일은 그림(&lt;img&gt;)으로만 쓰여 안의 스크립트는 돌지 않습니다.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------- 작업 폴더 위치
function RootsCard({ initial, nativePicker, onSave }: { initial: string[]; nativePicker: boolean; onSave: (roots: string[]) => Promise<boolean> }) {
  const [roots, setRoots] = useState<string[]>(() => [...initial]);
  const [newRoot, setNewRoot] = useState("");
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(roots) !== JSON.stringify(initial);
  const add = () => {
    const r = newRoot.trim();
    if (!r) return;
    setRoots((xs) => [...xs, r]);
    setNewRoot("");
  };
  return (
    <section className="card card-pad col">
      <div className="row"><h2>작업 폴더 위치</h2><Help text={TIPS.roots} /></div>
      <p className="muted small set-desc">새 실행 때 이 위치를 고르고 폴더 이름만 쓰면 됩니다. 첫 번째가 기본입니다.</p>
      <div className="list-edit">
        {roots.map((r, i) => (
          <div key={i} className="list-edit-item">
            <input type="text" value={r} spellCheck={false} aria-label={`작업 폴더 위치 ${i + 1}`}
                   onChange={(e) => { const val = e.target.value; setRoots((xs) => xs.map((x, j) => (j === i ? val : x))); }} />
            {i === 0 ? <span className="chip">기본</span>
              : <button className="btn btn-sm" type="button" onClick={() => setRoots((xs) => [xs[i], ...xs.filter((_, j) => j !== i)])}>기본으로</button>}
            <button className="btn btn-sm btn-danger" type="button" onClick={() => setRoots((xs) => xs.filter((_, j) => j !== i))}>삭제</button>
          </div>
        ))}
        {roots.length === 0 ? <p className="muted small" style={{ margin: 0 }}>아직 없습니다.</p> : null}
      </div>
      <div className="row">
        <input type="text" value={newRoot} onChange={(e) => setNewRoot(e.target.value)} placeholder="~/projects 또는 /절대/경로" spellCheck={false}
               aria-label="추가할 작업 폴더 위치" onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
        <FolderPickButton start={newRoot.trim()} nativePicker={nativePicker} favorites={roots} onPick={setNewRoot} />
        <button className="btn" type="button" onClick={add} disabled={!newRoot.trim()}>추가</button>
      </div>
      <div className="row">
        <button className="btn btn-primary" type="button" disabled={busy}
                onClick={async () => { setBusy(true); await onSave(roots.map((x) => x.trim()).filter(Boolean)); setBusy(false); }}>저장</button>
        {dirty ? <span className="faint small">저장하지 않은 변경이 있습니다.</span> : null}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- 폴더 고르기 (DESIGN.md 28.9)
// 브라우저는 폴더의 절대 경로를 주지 않으므로 tenure 서버가 고른다: OS 폴더 선택 창, 안 되면 tenure 폴더 창.
function FolderIcon() {
  return (
    <svg className="ico" viewBox="0 0 16 16" aria-hidden="true" width="16" height="16">
      <path d="M1.75 4.25c0-.55.45-1 1-1h3.4l1.5 1.6h5.6c.55 0 1 .45 1 1v6.4c0 .55-.45 1-1 1H2.75c-.55 0-1-.45-1-1z" />
    </svg>
  );
}

function FolderPickButton({ start, nativePicker, favorites, onPick, machine = LOCAL }: {
  start: string; nativePicker: boolean; favorites: string[]; onPick: (p: string) => void; machine?: string;
}) {
  const { toast } = useUi();
  const [busy, setBusy] = useState(false);
  const [browse, setBrowse] = useState(false);
  const click = async () => {
    if (machine === LOCAL && nativePicker) {
      setBusy(true);
      toast("폴더 선택 창을 열었습니다. 안 보이면 작업 표시줄을 확인하세요.");
      try {
        const r = await api<{ path: string | null }>("/api/fs/pick", { method: "POST", body: { start } });
        if (r.path) onPick(r.path);
        return;
      } catch (e) {
        toast(`${errMsg(e)} tenure 폴더 창으로 엽니다.`, true);
      } finally {
        setBusy(false);
      }
    }
    setBrowse(true);
  };
  return (
    <>
      <button className="btn path-pick" type="button" title="폴더 고르기" aria-label="폴더 고르기" disabled={busy} onClick={click}><FolderIcon /></button>
      {browse ? <FolderBrowser machine={machine} start={start} favorites={favorites} onClose={() => setBrowse(false)}
                               onPick={(p) => { setBrowse(false); onPick(p); }} /> : null}
    </>
  );
}

interface DirsResp {
  roots: { name: string; path: string }[]; sep: string; home: string; path: string | null; parent: string | null;
  entries: { name: string; path: string; git: boolean; tenure: boolean }[]; truncated: boolean;
}

function FolderBrowser({ machine, start, favorites, onClose, onPick }: {
  machine: string; start: string; favorites: string[]; onClose: () => void; onPick: (p: string) => void;
}) {
  const [data, setData] = useState<DirsResp | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [pathIn, setPathIn] = useState("");
  const [newName, setNewName] = useState("");
  const [status, setStatus] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const load = useCallback(async (path: string, fallback = false) => {
    setLoading(true);
    setStatus("");
    try {
      const r = await api<DirsResp>("/api/fs/dirs", { query: { path }, machine });
      setData(r);
      setError(null);
      setPathIn(r.path || "");
      if (listRef.current) listRef.current.scrollTop = 0;
    } catch (e) {
      if (fallback) { load(""); return; }
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [machine]);
  useEffect(() => { load(start, true); }, [load, start]);
  const choose = () => {
    if (!data?.path) return;
    const n = newName.trim();
    if (n && /[\\/:*?"<>|]/.test(n)) { setStatus("폴더 이름에 \\ / : * ? \" < > | 는 쓸 수 없습니다."); return; }
    onPick(n ? data.path.replace(/[\\/]+$/, "") + (data.sep || "/") + n : data.path);   // 그 머신의 경로 구분자로
  };
  const mine = favorites.filter((p) => p.trim()).map((p) => ({ name: p.split(/[\\/]/).filter(Boolean).pop() || p, path: p, star: true }));
  return (
    <Modal onClose={onClose} label="폴더 고르기">
      <div className="dialog-head"><h2>폴더 고르기</h2><span className="spacer" />
        <button className="btn btn-sm" type="button" aria-label="닫기" onClick={onClose}>×</button></div>
      <div className="dialog-body col fs-body">
        <div className="chips">
          {[...(data?.roots || []).map((x) => ({ ...x, star: false })), ...mine].map((x) => (
            <button key={`${x.star ? "*" : ""}${x.path}`} type="button" className={`fs-chip${x.path === data?.path ? " on" : ""}`} title={x.path}
                    onClick={() => load(x.path)}>{x.star ? `★ ${x.name}` : x.name}</button>
          ))}
        </div>
        <div className="row">
          <button className="btn btn-sm" type="button" title="위 폴더로" disabled={!data?.parent} onClick={() => data?.parent && load(data.parent)}>↑ 위로</button>
          <input type="text" value={pathIn} onChange={(e) => setPathIn(e.target.value)} spellCheck={false} autoComplete="off" placeholder="경로를 쓰고 Enter"
                 aria-label="폴더 경로" onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); load(pathIn.trim()); } }} />
        </div>
        <div className="fs-list" ref={listRef}>
          {loading ? <div className="empty small">불러오는 중…</div>
            : error ? <ErrorBox error={error} />
            : !data?.path ? <div className="empty small">위에서 시작할 곳을 고르세요.</div>
            : data.entries.length === 0 ? <div className="empty small">하위 폴더가 없습니다.</div>
            : data.entries.map((e) => (
              <button key={e.path} type="button" className="fs-item" title={e.path} onClick={() => load(e.path)}>
                <FolderIcon /><span className="ellipsis">{e.name}</span><span className="spacer" />
                {e.tenure ? <span className="badge ok">tenure</span> : e.git ? <span className="chip">git</span> : null}
              </button>
            ))}
        </div>
        {data?.truncated ? <div className="faint small">폴더가 많아 앞의 {data.entries.length}개만 보입니다. 경로를 직접 써서 들어가세요.</div> : null}
        {status ? <div className="alert alert-warn small"><span>{status}</span></div> : null}
      </div>
      <footer className="dialog-foot">
        <input type="text" className="fs-new" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="이 안에 새 폴더 이름 (선택)"
               spellCheck={false} autoComplete="off" aria-label="새 폴더 이름" />
        <button className="btn" type="button" onClick={onClose}>취소</button>
        <button className="btn btn-primary" type="button" disabled={!data?.path} onClick={choose}>{newName.trim() ? "새 폴더로 선택" : "이 폴더 선택"}</button>
      </footer>
    </Modal>
  );
}

// ---------------------------------------------------------------- 기본 실행 설정
const EFFORT_LABELS: Record<string, string> = { "": "단계별", minimal: "min", medium: "med" };

function modelInfo(sugg: AgentSugg | undefined, id: string): ModelSugg | undefined {
  return (sugg?.models || []).find((m) => m.id === id);
}
/** CLI 가 모델을 지정하지 않을 때 쓰는 모델의 이름 (DESIGN.md 30.6) */
function cliDefaultLabel(agent: Agent, sugg: AgentSugg | undefined): string {
  const id = sugg?.cli_default;
  if (!id) return agent === "claude" ? "Claude Code 기본값" : "Codex 기본값";
  return modelInfo(sugg, id)?.label || id;
}
function effortLevels(agent: Agent, sugg: AgentSugg | undefined, model: string): string[] {
  let levels = sugg?.efforts || [];
  if (agent === "codex" && model) {
    const m = modelInfo(sugg, model);
    if (m?.efforts?.length) levels = m.efforts;
  }
  return levels;
}
function stepText(map: Record<string, string> | undefined): string {
  const by: Record<string, string[]> = {};
  for (const [k, val] of Object.entries(map || {})) (by[val] = by[val] || []).push(STEP[k] || k);
  return Object.entries(by).map(([val, ks]) => `${ks.join("·")} ${val}`).join(", ");
}

/** 모델 고르기: 추천 모델(이름 + 짧은 설명) + 직접 입력. */
function ModelPicker({ agent, value, onChange, sugg, id }: {
  agent: Agent; value: string; onChange: (v: string) => void; sugg: AgentSugg | undefined; id?: string;
}) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const wrap = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const models = sugg?.models || [];
  const m = value ? modelInfo(sugg, value) : undefined;
  const cliDef = cliDefaultLabel(agent, sugg);
  const label = !value ? "기본 모델" : m ? (m.label || m.id) : value;
  const note = !value ? `CLI 기본 · ${cliDef}` : m ? (m.note || "") : "목록에 없음";
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown, true);
    window.setTimeout(() => (wrap.current?.querySelector(".mp-item.on, .mp-item") as HTMLElement | null)?.focus(), 0);
    return () => document.removeEventListener("mousedown", onDown, true);
  }, [open]);
  const pick = (val: string) => { onChange(val); setOpen(false); btn.current?.focus(); };
  const onKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); btn.current?.focus(); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const items = Array.from(wrap.current?.querySelectorAll<HTMLButtonElement>(".mp-item") || []);
      if (!items.length) return;
      e.preventDefault();
      const i = items.indexOf(document.activeElement as HTMLButtonElement);
      items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    }
  };
  const known = models.some((x) => x.id === value);
  const item = (key: string, on: boolean, lbl: string, nt: string | undefined, onPick: () => void, icon?: ReactNode) => (
    <button key={key} type="button" role="option" aria-selected={on} className={`mp-item${on ? " on" : ""}`} onClick={onPick}>
      {icon || <span className="mp-icon-space" />}
      <span className="mp-text"><span className="mp-item-label">{lbl}</span>{nt ? <span className="mp-item-note">{nt}</span> : null}</span>
      <span className="mp-check" aria-hidden="true">{on ? "✓" : ""}</span>
    </button>
  );
  return (
    <div className="mp" ref={wrap} onKeyDown={onKey}>
      <button ref={btn} id={id} type="button" className="mp-btn" aria-haspopup="listbox" aria-expanded={open}
              title={value || `CLI 기본 모델: ${cliDef}`} onClick={() => setOpen((o) => !o)}>
        <Logo agent={agent} />
        <span className={`mp-label${value ? "" : " def"}`}>{label}</span>
        {note ? <span className="mp-note">{note}</span> : null}
        <svg className="chev" viewBox="0 0 16 16" aria-hidden="true" width="14" height="14"><path d="M4 6l4 4 4-4" /></svg>
      </button>
      {open ? (
        <div className="mp-menu" role="listbox" aria-label={`${agent === "claude" ? "Claude" : "Codex"} 모델`}>
          {item("__def", !value, "기본 모델", `지금 ${cliDef} · CLI 설정을 따라감(새 모델이 나오면 함께 바뀜)`, () => pick(""), <Logo agent={agent} />)}
          {models.length ? <div className="mp-group">모델</div> : null}
          {models.map((x) => item(x.id, x.id === value, x.label || x.id, x.note, () => pick(x.id)))}
          {value && !known ? item("__cur", true, value, "지금 설정값 · 목록에 없음", () => { setOpen(false); btn.current?.focus(); }) : null}
          <div className="mp-group">직접 입력</div>
          <form className="mp-custom" onSubmit={(e) => { e.preventDefault(); if (custom.trim()) { pick(custom.trim()); setCustom(""); } }}>
            <input type="text" value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="모델 id (예: 새로 나온 모델)" spellCheck={false}
                   autoComplete="off" aria-label="모델 id 직접 입력" />
            <button className="btn btn-sm" type="submit" disabled={!custom.trim()}>적용</button>
          </form>
        </div>
      ) : null}
    </div>
  );
}

function DefaultsCard({ v, onSave }: { v: SettingsResp; onSave: (d: Record<string, unknown>) => Promise<boolean> }) {
  const d = v.settings.defaults || {};
  const eff = v.effective || {};
  const sugg = v.suggestions || ({} as Record<Agent, AgentSugg>);
  const limits = eff.limits || { debate_rounds: 5, max_review: 10 };
  const uid = useId();
  const [f, setF] = useState(() => ({
    implementer: String(d.implementer || ""), reviewer: String(d.reviewer || ""), synth: String(d.synth || ""),
    debate_rounds: d.debate_rounds ?? "", max_review: d.max_review ?? "",
    claude_model: String(d.claude?.model || ""), claude_effort: String(d.claude?.effort || ""),
    codex_model: String(d.codex?.model || ""), codex_effort: String(d.codex?.effort || ""),
    test_command: String(d.test_command || ""), block_severity: String(d.block_severity || ""),
    stall_rounds: d.stall_rounds ?? "",
    require_tests_pass: !!(d.require_tests_pass ?? eff.require_tests_pass),
    review_diff: ((d.review_diff ?? eff.review_diff) || "incremental") === "incremental",
    repro_tests: !!(d.repro_tests ?? eff.repro_tests ?? true),
  }));
  const [initial] = useState(f);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof typeof f>(k: K, val: (typeof f)[K]) => setF((x) => ({ ...x, [k]: val }));
  const dirty = JSON.stringify(f) !== JSON.stringify(initial);

  const effortCtl = (agent: Agent) => {
    const model = agent === "claude" ? f.claude_model : f.codex_model;
    const cur = agent === "claude" ? f.claude_effort : f.codex_effort;
    const levels = effortLevels(agent, sugg[agent], model);
    const opts = ["", ...levels, ...(cur && !levels.includes(cur) ? [cur] : [])];
    return (
      <Segmented label={`${agent === "claude" ? "Claude" : "Codex"} 추론 강도`} value={cur}
                 options={opts.map((o) => ({ value: o, label: EFFORT_LABELS[o] ?? o }))}
                 onChange={(val) => set(agent === "claude" ? "claude_effort" : "codex_effort", val)} />
    );
  };
  const nowNote = (agent: Agent) => {
    const e = eff[agent] as EffAgent | undefined;
    if (!e) return null;
    const sm = stepText(e.step_model);
    return (
      <div className="faint small">
        지금 적용: 모델 {e.model_base || `기본(${cliDefaultLabel(agent, sugg[agent])})`}{sm ? ` · 단계별 모델 ${sm}` : ""} · 추론 {e.effort_label || e.effort_base || "CLI 기본값"}
      </div>
    );
  };
  const onCodexModel = (val: string) => {
    setF((x) => {
      const levels = effortLevels("codex", sugg.codex, val);
      return { ...x, codex_model: val, codex_effort: levels.includes(x.codex_effort) ? x.codex_effort : "" };
    });
  };
  const submit = async () => {
    setBusy(true);
    await onSave({
      implementer: f.implementer, reviewer: f.reviewer, synth: f.synth,
      debate_rounds: String(f.debate_rounds), max_review: String(f.max_review),
      claude: { model: f.claude_model, effort: f.claude_effort },
      codex: { model: f.codex_model, effort: f.codex_effort },
      test_command: f.test_command, block_severity: f.block_severity,
      stall_rounds: String(f.stall_rounds), require_tests_pass: f.require_tests_pass,
      review_diff: f.review_diff ? "incremental" : "full", repro_tests: f.repro_tests,
    });
    setBusy(false);
  };
  const hasStepOv = d.step_overrides && Object.keys(d.step_overrides).length > 0;

  return (
    <section className="card card-pad col">
      <div className="row"><h2>기본 실행 설정</h2></div>
      <p className="muted small set-desc">CLI 와 UI 의 모든 실행에 적용됩니다. 작업 폴더의 tenure.toml 이나 실행할 때 고른 값이 더 우선합니다. 단계별 모델·강도는 새 실행 창의 순서도에서 고릅니다.</p>
      <div className="set-grid">
        <Field label="구현" tip={TIPS.implementer} id={`${uid}-impl`}>
          <select id={`${uid}-impl`} value={f.implementer} onChange={(e) => set("implementer", e.target.value)}>
            <option value="">기본값 ({eff.implementer})</option><option value="claude">claude</option><option value="codex">codex</option>
          </select>
        </Field>
        <Field label="리뷰" tip={TIPS.reviewer} id={`${uid}-rev`}>
          <select id={`${uid}-rev`} value={f.reviewer} onChange={(e) => set("reviewer", e.target.value)}>
            <option value="">기본값 ({eff.reviewer})</option><option value="codex">codex</option><option value="claude">claude</option>
          </select>
        </Field>
        <Field label="설계 종합" tip={TIPS.synth} id={`${uid}-syn`}>
          <select id={`${uid}-syn`} value={f.synth} onChange={(e) => set("synth", e.target.value)}>
            <option value="">리뷰 담당</option><option value="claude">claude</option><option value="codex">codex</option>
          </select>
        </Field>
        <Field label="토론 라운드" tip={TIPS.debate_rounds} id={`${uid}-dr`}>
          <input id={`${uid}-dr`} type="number" min={0} max={limits.debate_rounds} value={f.debate_rounds}
                 placeholder={String(eff.debate_rounds ?? "")} onChange={(e) => set("debate_rounds", e.target.value)} />
        </Field>
        <Field label="리뷰 최대" tip={TIPS.max_review} id={`${uid}-mr`}>
          <input id={`${uid}-mr`} type="number" min={1} max={limits.max_review} value={f.max_review}
                 placeholder={String(eff.max_review ?? "")} onChange={(e) => set("max_review", e.target.value)} />
        </Field>
      </div>

      <div className="agent-grid">
        {(["claude", "codex"] as const).map((agent) => (
          <div key={agent} className="agent-box col">
            <Field label={`${agent === "claude" ? "Claude" : "Codex"} 모델`} tip={agent === "claude" ? TIPS.claude_model : TIPS.codex_model} id={`${uid}-${agent}-m`}>
              <ModelPicker id={`${uid}-${agent}-m`} agent={agent} sugg={sugg[agent]}
                           value={agent === "claude" ? f.claude_model : f.codex_model}
                           onChange={agent === "claude" ? (val) => set("claude_model", val) : onCodexModel} />
            </Field>
            <Field label={`${agent === "claude" ? "Claude" : "Codex"} 추론`} tip={TIPS.effort}>{effortCtl(agent)}</Field>
            {nowNote(agent)}
          </div>
        ))}
      </div>
      {hasStepOv ? (
        <div className="alert alert-warn small"><b>단계별 지정</b>
          <span>settings.json 의 defaults.step_overrides 에 단계별 모델·강도가 있습니다. 이 카드를 저장하면 서버가 그 값을 남기지 않으니, 유지하려면 파일에서 직접 고치세요.</span></div>
      ) : null}

      <h3>리뷰·테스트</h3>
      <p className="muted small set-desc">반려 기준: 이 심각도 이상의 지적이 남아 있으면 반려합니다(P1 핵심 동작·보안, P2 설계 위반·일반 입력 오류, P3 드문 경계 사례). 수렴 판단: 막는 지적 수가 N 라운드 연속 줄지 않으면 멈춥니다(0=끔).</p>
      <div className="set-grid">
        <Field label="테스트 명령" tip={TIPS.test_command} id={`${uid}-tc`}>
          <input id={`${uid}-tc`} type="text" value={f.test_command} placeholder="자동 감지 (none 이면 끔)" spellCheck={false}
                 onChange={(e) => set("test_command", e.target.value)} />
        </Field>
        <Field label="반려 기준" tip={TIPS.block_severity} id={`${uid}-bs`}>
          <select id={`${uid}-bs`} value={f.block_severity} onChange={(e) => set("block_severity", e.target.value)}>
            <option value="">기본값 ({eff.block_severity})</option>{["P1", "P2", "P3"].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </Field>
        <Field label="수렴 판단 라운드" tip={TIPS.stall_rounds} id={`${uid}-sr`}>
          <input id={`${uid}-sr`} type="number" min={0} max={10} value={f.stall_rounds} placeholder={String(eff.stall_rounds ?? "")}
                 onChange={(e) => set("stall_rounds", e.target.value)} />
        </Field>
      </div>
      <div className="checklines">
        <span className="checkline"><label><input type="checkbox" checked={f.require_tests_pass} onChange={(e) => set("require_tests_pass", e.target.checked)} />테스트 실패 시 승인 안 함</label><Help text={TIPS.require_tests} /></span>
        <span className="checkline"><label><input type="checkbox" checked={f.review_diff} onChange={(e) => set("review_diff", e.target.checked)} />2번째 리뷰부터 바뀐 부분만</label><Help text={TIPS.review_diff} /></span>
        <span className="checkline"><label><input type="checkbox" checked={f.repro_tests} onChange={(e) => set("repro_tests", e.target.checked)} />리뷰어의 재현 테스트 받기</label><Help text={TIPS.repro_tests} /></span>
      </div>
      <div className="row">
        <button className="btn btn-primary" type="button" disabled={busy} onClick={submit}>저장</button>
        {dirty ? <span className="faint small">저장하지 않은 변경이 있습니다.</span> : null}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- 고급 설정 (설정 항목 정의, DESIGN.md 28.4)
export function optStr(val: unknown): string {
  return val === true ? "true" : val === false ? "false" : val === null || val === undefined ? "" : String(val);
}
function fmtOptValue(val: unknown): string {
  if (val === true) return "켬";
  if (val === false) return "끔";
  return val === null || val === undefined || val === "" ? "없음" : String(val);
}

function OptionControl({ o, value, base, onChange, id }: { o: OptionDef; value: string; base: string; onChange: (v: string) => void; id: string }) {
  if (o.kind === "bool") {
    return <Segmented label={o.label} value={value} onChange={onChange} options={[{ value: "true", label: "켬" }, { value: "false", label: "끔" }]} />;
  }
  if (o.kind === "choice") {
    const choices = [...(o.choices || [])];
    return (
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {base === "" ? <option value="">없음</option> : null}
        {choices.map((c) => <option key={c} value={c}>{c}</option>)}
        {value && !choices.includes(value) ? <option value={value}>{value}</option> : null}
      </select>
    );
  }
  return (
    <input id={id} type={o.kind === "int" ? "number" : "text"} min={o.min ?? undefined} max={o.max ?? undefined} value={value}
           placeholder={base === "" ? "없음" : base} spellCheck={false} autoComplete="off" onChange={(e) => onChange(e.target.value)} />
  );
}

function AdvancedCard({ options, defaults, onSave }: {
  options: OptionDef[]; defaults: Record<string, any>; onSave: (o: Record<string, string>) => Promise<boolean>;
}) {
  // 칸에는 늘 실제 값(저장한 값, 없으면 tenure 내장 기본값)을 보이고, 기본값과 같으면 저장하지 않는다(기본값이 바뀌면 따라감)
  const uid = useId();
  const [vals, setVals] = useState<Record<string, string>>(() =>
    Object.fromEntries(options.map((o) => [o.key, optStr(defaults[o.key] ?? o.default)])));
  const [initial] = useState(vals);
  const [busy, setBusy] = useState(false);
  const base = (o: OptionDef) => optStr(o.default);
  const changed = (o: OptionDef) => { const x = (vals[o.key] || "").trim(); return x !== "" && x !== base(o); };
  const dirty = options.some((o) => (vals[o.key] || "").trim() !== (initial[o.key] || "").trim());
  const groups: [string, OptionDef[]][] = [];
  for (const o of options) {
    const g = groups.find(([l]) => l === o.group_label);
    if (g) g[1].push(o); else groups.push([o.group_label, [o]]);
  }
  const submit = async () => {
    setBusy(true);
    const out: Record<string, string> = {};
    for (const o of options) {
      const x = (vals[o.key] || "").trim();
      out[o.key] = x === base(o) ? "" : x;      // 기본값과 같으면 '지정 안 함' → 서버가 지운다
    }
    await onSave(out);
    setBusy(false);
  };
  return (
    <section className="card card-pad col">
      <div className="row"><h2>고급 설정</h2></div>
      <p className="muted small set-desc">리뷰 관문·중재자·중복 확인·안전장치·한도 대기 같은 설정입니다. 칸에는 지금 쓰는 값이 보입니다. 기본값과 다른 줄은 ● 로 표시되고, ↺ 로 하나씩, ‘기본값으로’ 로 전부 되돌립니다.</p>
      {options.length === 0 ? <div className="empty small">설정 항목 정의를 받지 못했습니다.</div> : null}
      <div>
        {groups.map(([label, list]) => {
          const n = list.filter(changed).length;
          return (
            <details key={label} className="opt-section" open>
              <summary><span>{label}</span>{n ? <span className="opt-count">{n}개 바꿈</span> : null}</summary>
              <div className="opt-list">
                {list.map((o) => {
                  const id = `${uid}-${o.key}`;
                  const b = base(o);
                  return (
                    <div key={o.key} className={`opt-row${changed(o) ? " changed" : ""}`}>
                      <div className="opt-text">
                        <label className="opt-label" htmlFor={o.kind === "bool" ? undefined : id}>{o.label}</label>
                        <div className="opt-help">{o.help} <span className="opt-key">{o.key}</span></div>
                      </div>
                      <div className="opt-ctl">
                        <button type="button" className="opt-reset" disabled={!changed(o)} title={`기본값(${fmtOptValue(o.default)})으로 되돌리기`}
                                aria-label={`${o.label} 기본값으로 되돌리기`} onClick={() => setVals((x) => ({ ...x, [o.key]: b }))}>↺</button>
                        <OptionControl o={o} id={id} value={vals[o.key] ?? ""} base={b} onChange={(val) => setVals((x) => ({ ...x, [o.key]: val }))} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </details>
          );
        })}
      </div>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <button className="btn btn-primary" type="button" disabled={busy} onClick={submit}>저장</button>
        <button className="btn" type="button" onClick={() => setVals(Object.fromEntries(options.map((o) => [o.key, base(o)])))}>기본값으로</button>
        <span className="faint small">{dirty ? "저장하지 않은 변경이 있습니다. " : ""}되돌린 뒤 저장해야 적용됩니다.</span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- 원격 머신
const EMPTY_MACHINE = { id: "", name: "", ssh: "", port: "22", workspace_root: "" };

function MachinesCard({ machines, onChanged, reload }: { machines: Machine[]; onChanged: (v: SettingsResp) => void; reload: () => Promise<void> }) {
  const { toast, confirm } = useUi();
  const uid = useId();
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_MACHINE);
  const [busy, setBusy] = useState(false);
  const [probes, setProbes] = useState<Record<string, { busy?: boolean; deploying?: boolean; info?: ProbeInfo; error?: string }>>({});
  const set = (k: keyof typeof EMPTY_MACHINE, val: string) => setForm((x) => ({ ...x, [k]: val }));
  const edit = (m: Machine) => {
    setEditing(m.id);
    setForm({ id: m.id, name: m.name || "", ssh: m.ssh || "", port: String(m.port || 22), workspace_root: m.workspace_root || "" });
  };
  const cancel = () => { setEditing(null); setForm(EMPTY_MACHINE); };
  const saveMachine = async () => {
    setBusy(true);
    try {
      const nv = await api<SettingsResp>("/api/machines", { method: "POST", body: {
        id: form.id.trim(), name: form.name.trim(), ssh: form.ssh.trim(), port: form.port, workspace_root: form.workspace_root.trim() } });
      onChanged(nv);
      cancel();
      toast("저장했습니다. ‘연결 확인’이나 환경·로그인 화면에서 연결을 확인하세요.");
    } catch (e) { toast(errMsg(e), true); }
    setBusy(false);
  };
  const remove = async (m: Machine) => {
    if (!(await confirm(`${m.name || m.id} 머신을 목록에서 지울까요? 원격의 파일은 그대로 둡니다.`, { ok: "지우기", danger: true }))) return;
    try {
      const nv = await api<SettingsResp>("/api/machines", { method: "DELETE", query: { id: m.id } });
      onChanged(nv);
      if (editing === m.id) cancel();
    } catch (e) { toast(errMsg(e), true); }
  };
  const probe = async (m: Machine) => {
    setProbes((x) => ({ ...x, [m.id]: { ...x[m.id], busy: true, error: undefined } }));
    try {
      const info = await api<ProbeInfo>("/api/machines/probe", { method: "POST", machine: m.id });
      setProbes((x) => ({ ...x, [m.id]: { info } }));
      if (info.python && info.python !== m.python) reload();   // 서버가 찾은 Python 경로를 설정에 적어 둔다
    } catch (e) {
      setProbes((x) => ({ ...x, [m.id]: { error: errMsg(e) } }));
    }
  };
  const deploy = async (m: Machine) => {
    setProbes((x) => ({ ...x, [m.id]: { ...x[m.id], deploying: true } }));
    try {
      const r = await api<{ version: string }>("/api/machines/deploy", { method: "POST", machine: m.id });
      toast(`배포했습니다: ${r.version}`);
      await probe(m);
    } catch (e) {
      toast(errMsg(e), true);
      setProbes((x) => ({ ...x, [m.id]: { ...x[m.id], deploying: false } }));
    }
  };

  return (
    <section className="card card-pad col">
      <div className="row"><h2>원격 머신</h2></div>
      <p className="muted small set-desc">다른 머신에서 tenure 를 돌립니다. 이 머신에서 비밀번호 없이 SSH 접속이 되어야 합니다(키 등록: <code>ssh-copy-id user@host</code>). 원격에는 Python 3.11+ 만 있으면 되고 tenure 는 UI 가 복사합니다.</p>
      {machines.length ? (
        <div className="table-scroll">
          <table className="list set-table">
            <thead><tr><th>머신</th><th>SSH</th><th>작업 폴더 위치</th><th>Python</th><th>연결</th><th></th></tr></thead>
            <tbody>
              {machines.map((m) => {
                const p = probes[m.id] || {};
                const info = p.info;
                return (
                  <tr key={m.id}>
                    <td><b>{m.name || m.id}</b><div className="mono small faint">{m.id}</div></td>
                    <td className="mono small">{m.ssh}{m.port && m.port !== 22 ? `:${m.port}` : ""}</td>
                    <td className="mono small">{m.workspace_root || "-"}</td>
                    <td className="mono small">{m.python || <span className="faint">미확인</span>}</td>
                    <td className="small">
                      {p.busy ? <span className="row"><span className="spinner" />확인 중…</span>
                        : p.error ? <span className="badge bad" title={p.error}>오류</span>
                        : !info ? <span className="faint">-</span>
                        : <ProbeSummary info={info} />}
                      {p.error ? <div className="small bad-text">{p.error}</div> : null}
                      {info && !info.reachable && info.hint ? <div className="mono small faint">{info.hint}</div> : null}
                    </td>
                    <td>
                      <div className="row set-acts">
                        <button className="btn btn-sm" type="button" disabled={p.busy} onClick={() => probe(m)}>연결 확인</button>
                        {info?.reachable && info.python && !(info.deployed && info.up_to_date) ? (
                          <button className="btn btn-sm btn-primary" type="button" disabled={p.deploying} title={TIPS.deploy} onClick={() => deploy(m)}>
                            {p.deploying ? "배포 중…" : info.deployed ? "업데이트" : "배포"}</button>
                        ) : null}
                        <a className="btn btn-sm" href={`#/setup?m=${encodeURIComponent(m.id)}`}>환경·로그인</a>
                        <button className="btn btn-sm" type="button" onClick={() => edit(m)}>수정</button>
                        <button className="btn btn-sm btn-danger" type="button" onClick={() => remove(m)}>삭제</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : <p className="muted small" style={{ margin: 0 }}>등록된 원격 머신이 없습니다.</p>}

      <h3>{editing ? `머신 수정: ${editing}` : "머신 추가"}</h3>
      <form className="col" onSubmit={(e) => { e.preventDefault(); saveMachine(); }}>
        <div className="set-grid">
          <Field label="id (영문 소문자)" tip={TIPS["machine.id"]} id={`${uid}-id`}>
            <input id={`${uid}-id`} type="text" value={form.id} placeholder="lab" spellCheck={false} readOnly={!!editing} required
                   onChange={(e) => set("id", e.target.value)} />
          </Field>
          <Field label="이름" tip={TIPS["machine.name"]} id={`${uid}-name`}>
            <input id={`${uid}-name`} type="text" value={form.name} placeholder="연구실 서버" onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="SSH 대상" tip={TIPS["machine.ssh"]} id={`${uid}-ssh`}>
            <input id={`${uid}-ssh`} type="text" value={form.ssh} placeholder="me@lab.example.com" spellCheck={false} required
                   onChange={(e) => set("ssh", e.target.value)} />
          </Field>
          <Field label="포트" tip={TIPS["machine.port"]} id={`${uid}-port`}>
            <input id={`${uid}-port`} type="number" value={form.port} min={1} max={65535} onChange={(e) => set("port", e.target.value)} />
          </Field>
          <Field label="작업 폴더 위치" tip={TIPS["machine.root"]} id={`${uid}-root`}>
            <input id={`${uid}-root`} type="text" value={form.workspace_root} placeholder="~/tenure-projects" spellCheck={false}
                   onChange={(e) => set("workspace_root", e.target.value)} />
          </Field>
        </div>
        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={busy || !form.id.trim() || !form.ssh.trim()}>{editing ? "수정 저장" : "머신 추가"}</button>
          {editing ? <button className="btn" type="button" onClick={cancel}>취소</button> : null}
        </div>
      </form>
    </section>
  );
}

export function ProbeSummary({ info }: { info: ProbeInfo }) {
  if (!info.reachable) return <span className="badge bad" title={info.error}>연결 안 됨</span>;
  return (
    <span className="chips">
      <span className="badge ok" title={info.uname}>연결됨</span>
      {info.python ? <span className="badge ok" title={info.python}>Python</span> : <span className="badge bad">Python 없음</span>}
      {!info.deployed ? <span className="badge">미배포</span>
        : info.up_to_date ? <span className="badge ok" title={info.remote_hash}>최신</span>
        : <span className="badge warn" title={`원격 ${info.remote_hash} · 이 머신 ${info.local_hash}`}>업데이트 필요</span>}
    </span>
  );
}

// ---------------------------------------------------------------- UI 서버
function ServerCard({ server, reload }: { server: ServerInfo | null; reload: () => Promise<void> }) {
  const { toast, confirm } = useUi();
  const [restarting, setRestarting] = useState(false);
  const restart = async () => {
    const running = server?.running_terms || [];
    if (running.length) { toast(`진행 중인 터미널 작업이 있습니다: ${running.join(", ")}`, true); return; }
    if (!(await confirm("UI 를 다시 시작할까요? 같은 주소로 다시 뜨고, 진행 중인 실행은 그대로 돕니다.", { ok: "다시 시작" }))) return;
    try {
      await api("/api/server/restart", { method: "POST" });
    } catch (e) { toast(errMsg(e), true); return; }
    setRestarting(true);
    const before = server ? server.uptime_sec : null;
    const wasStale = !!server?.stale;
    const deadline = Date.now() + 30000;
    await sleep(800);
    while (Date.now() < deadline) {
      try {
        const s = await api<ServerInfo>("/api/server");
        if (before === null || s.uptime_sec < before || (wasStale && !s.stale)) { location.reload(); return; }
      } catch { /* 아직 다시 뜨는 중 */ }
      await sleep(500);
    }
    setRestarting(false);
    toast("UI 가 다시 뜨지 않았습니다. tenure ui 를 실행한 터미널을 확인하세요.", true);
  };
  return (
    <section className="card card-pad col">
      <div className="row"><h2>UI 서버</h2><span className="spacer" />
        <button className="btn btn-sm" type="button" onClick={() => reload()}>새로 고침</button></div>
      <p className="muted small set-desc">tenure 코드를 바꾸거나 업데이트한 뒤에는 다시 시작해야 반영됩니다. 같은 주소로 다시 뜨고, 진행 중인 실행은 그대로 돕니다.</p>
      {!server ? <div className="faint small">서버 정보를 받지 못했습니다.</div> : (
        <div className="chips">
          <span className="chip">버전 <b>{server.version || "?"}</b></span>
          <span className="chip">실행 중 코드 <b className="mono">{server.loaded || "?"}</b></span>
          <span className="chip">설치된 코드 <b className="mono">{server.current || "?"}</b></span>
          {server.uptime_sec != null ? <span className="chip">켜진 지 {fmtDur(server.uptime_sec)}</span> : null}
          {server.stale ? <span className="badge warn" title={TIPS.update}>다시 시작 필요</span> : <span className="badge ok">최신</span>}
          {server.running_terms?.length ? <span className="badge info">터미널 작업 진행 중: {server.running_terms.join(", ")}</span> : null}
        </div>
      )}
      {server?.stale ? <div className="alert alert-warn"><b>업데이트</b><span>{TIPS.update}</span></div> : null}
      <div className="row">
        <button className="btn" type="button" title={TIPS.restart} onClick={restart} disabled={restarting}>UI 다시 시작</button>
        <Help text={TIPS.restart} />
      </div>
      {restarting ? (
        <Modal onClose={() => { /* 다시 뜰 때까지 기다린다 */ }} label="다시 시작하는 중">
          <div className="dialog-body row" style={{ gap: 12 }}><span className="spinner" /><span>UI 를 다시 시작하는 중입니다… 다시 뜨면 화면을 새로 불러옵니다.</span></div>
        </Modal>
      ) : null}
    </section>
  );
}
