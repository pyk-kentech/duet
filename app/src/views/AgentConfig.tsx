import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { AgentTag, ErrorBox } from "../ui";

/** 에이전트 설정 보기 (DESIGN.md 36.19, 보기 전용): 이 폴더에서 Claude·Codex 가 실제로 읽는 것. 비밀값은 가림. */
export default function AgentConfigView({ project }: { project: string }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api("/api/agent-config", { query: { project } }).then(setD).catch(setErr); }, [project]);
  if (err) return <ErrorBox error={err} />;
  if (!d) return <div className="empty"><span className="spinner" /></div>;
  const c = d.claude, x = d.codex;
  return (
    <div className="col" style={{ gap: 12 }}>
      <div className="muted small">이 폴더에서 에이전트를 띄우면 아래 설정·메모리·스킬·MCP 가 함께 읽힙니다. 보기 전용이며 비밀값은 ••••로 가렸습니다.</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 12, alignItems: "start" }}>
        <section className="card card-pad col" style={{ gap: 10 }}>
          <div className="row"><AgentTag name="claude" /><b>Claude Code</b></div>
          <Group title="설정 파일" empty="없음">
            {c.settings.map((s: any) => (
              <div key={s.path} className="small">
                <b>{s.where}</b> <span className="mono faint">{s.path}</span>
                {s.model ? <div>모델 <span className="mono">{s.model}</span></div> : null}
                {s.default_mode ? <div>기본 권한 모드 <span className="mono">{s.default_mode}</span></div> : null}
                {Object.entries(s.permissions || {}).map(([k, v]: any) => <div key={k}>권한 {k}: <span className="mono">{v.join(", ")}</span></div>)}
                {Object.keys(s.hooks || {}).length ? <div>훅: {Object.entries(s.hooks).map(([ev, cmds]: any) => `${ev}(${cmds.length})`).join(", ")}</div> : null}
                {s.env.length ? <div>환경 변수: <span className="mono">{s.env.join(", ")}</span> (값 숨김)</div> : null}
                {s.plugins.length ? <div>플러그인: {s.plugins.join(", ")}</div> : null}
              </div>
            ))}
          </Group>
          <Files title="메모리 (CLAUDE.md)" items={c.memory} />
          <Items title="스킬" items={c.skills} />
          <Items title="서브에이전트" items={c.agents} />
          <Items title="명령" items={c.commands} />
          <Mcp items={c.mcp} />
          {c.allowed_tools.length ? <Group title="이 폴더에서 허용한 도구"><div className="mono small">{c.allowed_tools.join(", ")}</div></Group> : null}
        </section>
        <section className="card card-pad col" style={{ gap: 10 }}>
          <div className="row"><AgentTag name="codex" /><b>Codex</b></div>
          <Group title="설정" empty="없음">
            <div className="small"><span className="mono faint">{x.path}</span></div>
            {Object.entries(x.settings).map(([k, v]: any) => <div key={k} className="small">{k} = <span className="mono">{String(v)}</span></div>)}
            {Object.entries(x.this_folder || {}).map(([k, v]: any) => <div key={k} className="small">이 폴더: {k} = <span className="mono">{String(v)}</span></div>)}
            {x.notify.length ? <div className="small">notify: <span className="mono">{x.notify.join(" ")}</span> (tenure 세션에서도 이어서 부름)</div> : null}
            {x.profiles.length ? <div className="small">프로필: {x.profiles.join(", ")}</div> : null}
            {x.plugins.length ? <div className="small">플러그인: {x.plugins.join(", ")}</div> : null}
          </Group>
          <Files title="메모리 (AGENTS.md)" items={x.memory} />
          <Items title="스킬" items={x.skills} />
          <Items title="프롬프트" items={x.prompts} />
          <Mcp items={x.mcp} />
        </section>
      </div>
    </div>
  );
}

function Group({ title, children, empty }: { title: string; children?: React.ReactNode; empty?: string }) {
  const has = Array.isArray(children) ? children.some(Boolean) : !!children;
  return (
    <div className="col" style={{ gap: 4 }}>
      <div className="faint small" style={{ fontWeight: 600 }}>{title}</div>
      {has ? children : <div className="faint small">{empty || "없음"}</div>}
    </div>
  );
}

function Files({ title, items }: { title: string; items: { path: string; chars: number; first_line: string }[] }) {
  return <Group title={title}>{items.map((m) => <div key={m.path} className="small"><span className="mono">{m.path}</span> <span className="faint">({m.chars.toLocaleString()}자) {m.first_line}</span></div>)}</Group>;
}

function Items({ title, items }: { title: string; items: { name: string; description: string; where: string; path: string }[] }) {
  return (
    <Group title={`${title} ${items.length ? items.length + "개" : ""}`}>
      {items.length ? <details><summary className="small">펼치기</summary>
        {items.map((s) => <div key={s.path} className="small" title={s.path}><b>{s.name}</b> <span className="faint">{s.where}</span>{s.description ? ` — ${s.description}` : ""}</div>)}
      </details> : null}
    </Group>
  );
}

function Mcp({ items }: { items: any[] }) {
  return (
    <Group title="MCP 서버">
      {items.map((m) => (
        <div key={`${m.where}|${m.name}`} className="small">
          <b>{m.name}</b> <span className="faint">{m.where} · {m.type}</span>
          <div className="mono faint ellipsis" title={m.command}>{m.command} {(m.args || []).join(" ")}</div>
          {m.env.length ? <div className="faint">환경 변수 {m.env.join(", ")} (값 숨김)</div> : null}
        </div>
      ))}
    </Group>
  );
}
