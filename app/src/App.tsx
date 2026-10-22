import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useGroups } from "./data";
import { Icon } from "./icons";
import { LOCAL } from "./lib/api";
import { Route, useRoute } from "./lib/router";
import { useSessions } from "./sessions";
import { UiProvider } from "./ui";
import { BenchView } from "./views/Bench";
import Home from "./views/Home";
import NewRun, { NewRunInit } from "./views/NewRun";
import Palette from "./views/Palette";
import ProjectView from "./views/Project";
import RunView from "./views/Run";
import { SettingsView } from "./views/Settings";
import { SetupView } from "./views/Setup";
import { UsageView } from "./views/Usage";
import WorkList from "./views/WorkList";
import { buildFolders, countStates, useWorks } from "./works";

// 터미널(xterm)·섬은 무거워 그 화면을 열 때만 불러온다
const SessionView = lazy(() => import("./views/Session"));
const Island = lazy(() => import("./views/Island"));

export default function App() {
  const route = useRoute();
  if (route.name === "island") {                 // 데스크톱 앱의 섬 창 (36.21)
    return <UiProvider><Suspense fallback={null}><Island /></Suspense></UiProvider>;
  }
  return (
    <UiProvider>
      <Shell route={route} />
    </UiProvider>
  );
}

const RAIL: [string, string, string, (r: Route) => boolean][] = [
  ["#/", "work", "작업", (r) => r.name === "home" || r.name === "run" || r.name === "project" || r.name === "session"],
  ["#/usage", "gauge", "사용량", (r) => r.name === "usage"],
  ["#/bench", "flask", "벤치마크", (r) => r.name === "bench"],
  ["#/setup", "plug", "환경·로그인", (r) => r.name === "setup"],
  ["#/settings", "cog", "설정", (r) => r.name === "settings"],
];

/** 작업대 (36.21): 왼쪽 레일 · 작업 목록 · 본문. */
function Shell({ route }: { route: Route }) {
  const { groups, error, reload } = useGroups();
  const { works, reload: reloadWorks } = useWorks(groups);
  const { sessions, reload: reloadSessions } = useSessions();
  const folders = useMemo(() => buildFolders(works, sessions), [works, sessions]);
  const counts = useMemo(() => countStates(folders), [folders]);
  const [newRun, setNewRun] = useState<NewRunInit | null>(null);
  const [palette, setPalette] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const refresh = useCallback(() => { reload(); reloadWorks(); reloadSessions(); }, [reload, reloadWorks, reloadSessions]);
  const openNew = useCallback((init: NewRunInit = {}) => setNewRun(init), []);
  const waiting = (counts.blocked || 0) + (counts.failed || 0);

  useEffect(() => { document.title = waiting ? `(${waiting}) tenure` : "tenure"; }, [waiting]);
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((x) => !x); return; }
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable || t.closest(".xterm"))) return;
      if (e.key === "n" && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); openNew({}); }
      if (e.key === "Escape" && (route.name === "run" || route.name === "session")) location.hash = "#/";
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [openNew, route.name]);

  return (
    <div className="wb">
      <nav className="rail" aria-label="화면">
        <a className="rail-brand" href="#/" title="tenure">t</a>
        {RAIL.map(([href, icon, label, on]) => (
          <a key={href} href={href} className={`rail-btn${on(route) ? " on" : ""}`} title={label} aria-label={label} aria-current={on(route) ? "page" : undefined}>
            <Icon name={icon} />
            {icon === "work" && waiting ? <span className="rail-badge">{waiting}</span> : null}
          </a>
        ))}
        <span className="spacer" />
        <button type="button" className="rail-btn" title="명령 (Ctrl+K)" aria-label="명령 팔레트" onClick={() => setPalette(true)}><Icon name="search" /></button>
      </nav>
      <WorkList folders={folders} route={route} searchRef={searchRef} onChanged={refresh}
                onNew={(project, machine) => openNew(project ? { project, machine: machine || LOCAL } : {})} />
      <main className="main">
        {route.name === "home" && <Home groups={groups} error={error} folders={folders} onNewRun={openNew} onChanged={refresh} />}
        {route.name === "project" && <ProjectView route={route} onNewRun={openNew} onChanged={reload} onSession={reloadSessions} />}
        {route.name === "run" && <RunView key={`${route.machine}|${route.project}|${route.run}`} route={route} onSeen={reloadWorks} onSession={reloadSessions} />}
        {route.name === "session" && <Suspense fallback={<div className="empty"><span className="spinner" /></div>}>
          <SessionView key={route.id} id={route.id} sessions={sessions} onChanged={reloadSessions} /></Suspense>}
        {route.name === "usage" && <UsageView machine={route.machine} groups={groups} />}
        {route.name === "setup" && <SetupView machine={route.machine} groups={groups} />}
        {route.name === "settings" && <SettingsView />}
        {route.name === "bench" && <BenchView dir={route.dir} />}
      </main>
      {newRun && <NewRun init={newRun} groups={groups} onClose={() => setNewRun(null)}
                         onStarted={() => { setNewRun(null); refresh(); }} />}
      {palette && <Palette folders={folders} onClose={() => setPalette(false)} onNew={() => openNew({})} />}
    </div>
  );
}
