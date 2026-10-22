import { lazy, Suspense, useState } from "react";
import { Group, useGroups, useInbox } from "./data";
import { LOCAL } from "./lib/api";
import { baseName } from "./lib/format";
import { hrefProject, Route, useRoute } from "./lib/router";
import { hrefSession, SESSION_STATE, SessionInfo, sessionDot, useSessions } from "./sessions";
import { AgentTag, StateDot, UiProvider } from "./ui";
import Home from "./views/Home";
import NewRun, { NewRunInit } from "./views/NewRun";
import ProjectView from "./views/Project";
import RunView from "./views/Run";
import { BenchView } from "./views/Bench";
import { SettingsView } from "./views/Settings";
import { SetupView } from "./views/Setup";
import { UsageView } from "./views/Usage";

// 터미널(xterm)은 무거워서 세션 화면을 열 때만 불러온다
const SessionView = lazy(() => import("./views/Session"));

export default function App() {
  return (
    <UiProvider>
      <Shell />
    </UiProvider>
  );
}

function Shell() {
  const route = useRoute();
  const { groups, error, reload } = useGroups();
  const { items, reload: reloadInbox } = useInbox(groups);
  const { sessions, reload: reloadSessions } = useSessions();
  const [newRun, setNewRun] = useState<NewRunInit | null>(null);
  const waiting = items.filter((i) => i.activity.state === "blocked").length
    + sessions.filter((s) => s.status.attention === "blocked").length;
  const openNew = (init: NewRunInit = {}) => setNewRun(init);

  return (
    <div className="shell">
      <aside className="side" aria-label="탐색">
        <div className="side-top">
          <div className="brand"><span className="brand-mark">t</span>tenure</div>
          <button className="btn btn-primary btn-block" type="button" onClick={() => openNew({})}>새 실행</button>
        </div>
        <nav className="nav">
          <NavLink href="#/" active={route.name === "home"} label="받은편지함" count={waiting || undefined} />
          <NavLink href="#/usage" active={route.name === "usage"} label="사용량" />
          <NavLink href="#/bench" active={route.name === "bench"} label="벤치마크" />
          <NavLink href="#/setup" active={route.name === "setup"} label="환경·로그인" />
          <NavLink href="#/settings" active={route.name === "settings"} label="설정" />
        </nav>
        <SideSessions sessions={sessions} route={route} />
        <SideProjects groups={groups} route={route} inboxStates={Object.fromEntries(items.map((i) => [`${i.machine}|${i.project}`, i.activity.state]))} />
      </aside>
      <main className="main">
        {route.name === "home" && <Home groups={groups} error={error} inbox={items} sessions={sessions} onNewRun={openNew}
                                         onChanged={() => { reload(); reloadInbox(); reloadSessions(); }} />}
        {route.name === "project" && <ProjectView route={route} onNewRun={openNew} onChanged={reload} onSession={reloadSessions} />}
        {route.name === "session" && <Suspense fallback={<div className="empty"><span className="spinner" /></div>}>
          <SessionView key={route.id} id={route.id} sessions={sessions} onChanged={reloadSessions} /></Suspense>}
        {route.name === "run" && <RunView key={`${route.machine}|${route.project}|${route.run}`} route={route} onSeen={reloadInbox} onSession={reloadSessions} />}
        {route.name === "usage" && <UsageView machine={route.machine} groups={groups} />}
        {route.name === "setup" && <SetupView machine={route.machine} groups={groups} />}
        {route.name === "settings" && <SettingsView />}
        {route.name === "bench" && <BenchView dir={route.dir} />}
      </main>
      {newRun && <NewRun init={newRun} groups={groups} onClose={() => setNewRun(null)}
                         onStarted={() => { setNewRun(null); reload(); reloadInbox(); }} />}
    </div>
  );
}

function NavLink({ href, label, active, count }: { href: string; label: string; active: boolean; count?: number }) {
  return (
    <a href={href} className={active ? "active" : undefined} aria-current={active ? "page" : undefined}>
      {label}{count ? <span className="count" aria-label={`${count}개`}>{count}</span> : null}
    </a>
  );
}

/** 대화형 세션 (36.19): 열려 있는 것과 최근 끝난 것. */
function SideSessions({ sessions, route }: { sessions: SessionInfo[]; route: Route }) {
  const shown = sessions.filter((s) => s.live || s.status.attention).slice(0, 8);
  if (!shown.length) return null;
  return (
    <>
      <div className="side-section">세션</div>
      <div className="side-list" style={{ flex: "none" }}>
        {shown.map((s) => (
          <a key={s.id} className={`side-proj${route.name === "session" && route.id === s.id ? " active" : ""}`} href={hrefSession(s.id)}
             title={`${SESSION_STATE[s.status.state]} · ${s.status.reason}\n${s.cwd}`}>
            <StateDot state={sessionDot(s)} />
            <AgentTag name={s.agent} />
            <span className="ellipsis">{s.title || baseName(s.cwd)}</span>
          </a>
        ))}
      </div>
    </>
  );
}

function SideProjects({ groups, route, inboxStates }: { groups: Group[] | null; route: Route; inboxStates: Record<string, string> }) {
  if (!groups) return null;
  const current = route.name === "project" || route.name === "run" ? `${route.machine}|${route.project}` : "";
  return (
    <>
      {groups.map((g) => (
        <div key={g.id} style={{ display: "contents" }}>
          <div className="side-section">{g.local ? "이 머신" : g.name}{g.error ? <span className="badge bad" style={{ marginLeft: 6 }}>연결 안 됨</span> : null}</div>
          <div className="side-list" style={{ flex: "none" }}>
            {g.projects.filter((p) => p.exists && !p.bench).map((p) => {
              const key = `${g.id}|${p.path}`;
              const state = p.live ? "working" : inboxStates[key] || p.latest?.activity?.state || "idle";
              return (
                <a key={key} className={`side-proj${current === key ? " active" : ""}`} href={hrefProject(g.id || LOCAL, p.path)} title={p.path}>
                  <StateDot state={state} />
                  <span className="ellipsis">{p.display || p.name || baseName(p.path)}</span>
                </a>
              );
            })}
            {!g.projects.some((p) => p.exists && !p.bench) && <div className="faint small" style={{ padding: "4px 8px" }}>프로젝트 없음</div>}
          </div>
        </div>
      ))}
    </>
  );
}
