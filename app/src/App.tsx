import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useGroups } from "./data";
import { api, LOCAL } from "./lib/api";
import { Route, useRoute } from "./lib/router";
import { useSessions } from "./sessions";
import { UiProvider, useUi } from "./ui";
import { BenchView } from "./views/Bench";
import Home from "./views/Home";
import NewRun, { NewRunInit } from "./views/NewRun";
import Palette from "./views/Palette";
import { SettingsView } from "./views/Settings";
import { SetupView } from "./views/Setup";
import Sidebar from "./views/Sidebar";
import StatusBar from "./views/StatusBar";
import { UsageView } from "./views/Usage";
import Workspace from "./views/Workspace";
import { buildFolders, countStates, useWorks } from "./works";
import { hrefSessionWs, usePref, WsRef } from "./ws";

// 섬은 데스크톱 앱의 따로 창에서만
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

function routeWs(route: Route): WsRef | null {
  if (route.name === "run") return { machine: route.machine, project: route.project, run: route.run };
  if (route.name === "project") return { machine: route.machine, project: route.project, run: null };
  return null;
}

/** 드래그로 폭 조절 (오르카: 끄는 동안만 바뀌고 놓을 때 저장). */
function useDrag(width: number, set: (w: number) => void, min: number, max: number, dir: 1 | -1) {
  return useCallback((startX: number) => {
    const start = width;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const move = (e: MouseEvent) => set(Math.max(min, Math.min(max, start + dir * (e.clientX - startX))));
    const up = () => {
      document.body.style.cursor = ""; document.body.style.userSelect = "";
      window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }, [width, set, min, max, dir]);
}

/** 오르카 식 작업공간 틀 (36.22): 왼쪽 목록 · 가운데 · 오른쪽 판 · 아래 막대. */
function Shell({ route }: { route: Route }) {
  const { toast } = useUi();
  const { groups, error, reload } = useGroups();
  const { works, reload: reloadWorks } = useWorks(groups);
  const { sessions, loaded: sessionsLoaded, reload: reloadSessions } = useSessions();
  const folders = useMemo(() => buildFolders(works, sessions), [works, sessions]);
  const counts = useMemo(() => countStates(folders), [folders]);
  const [newRun, setNewRun] = useState<NewRunInit | null>(null);
  const [palette, setPalette] = useState(false);
  const [sbOpen, setSbOpen] = usePref("sbOpen", true);
  const [sbW, setSbW] = usePref("sbW", 280);
  const [rpW, setRpW] = usePref("rpW", 350);
  const refresh = useCallback(() => { reload(); reloadWorks(); reloadSessions(); }, [reload, reloadWorks, reloadSessions]);
  const openNew = useCallback((init: NewRunInit = {}) => setNewRun(init), []);
  const waiting = (counts.blocked || 0) + (counts.failed || 0);
  const ws = routeWs(route);
  const dragSb = useDrag(sbW, setSbW, 220, 500, 1);
  const dragRp = useDrag(rpW, setRpW, 220, Math.max(320, window.innerWidth - 600), -1);

  // 옛 세션 주소 (#/s/<id>) → 그 세션의 작업공간 탭
  useEffect(() => {
    if (route.name !== "session" || !sessionsLoaded) return;
    const s = sessions.find((x) => x.id === route.id);
    if (s) location.replace(hrefSessionWs(s));
    else { toast("세션을 찾을 수 없습니다. 닫혔거나 다른 머신의 세션입니다.", true); location.replace("#/"); }
  }, [route, sessionsLoaded]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { document.title = waiting ? `(${waiting}) tenure` : "tenure"; }, [waiting]);
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((x) => !x); return; }
      if (mod && !e.shiftKey && e.key.toLowerCase() === "b") { e.preventDefault(); setSbOpen(!sbOpen); return; }
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable || t.closest(".xterm"))) return;
      if (e.key === "n" && !mod && !e.altKey) { e.preventDefault(); openNew(ws ? { machine: ws.machine, project: ws.project } : {}); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [openNew, sbOpen, setSbOpen, ws?.machine, ws?.project]);   // eslint-disable-line react-hooks/exhaustive-deps

  const addFolder = async () => {
    try {
      toast("폴더 선택 창을 열었습니다. 안 보이면 작업 표시줄을 확인하세요.");
      const r = await api<{ path?: string }>("/api/fs/pick", { method: "POST", body: {} });
      if (!r.path) return;
      await api("/api/projects", { method: "POST", body: { path: r.path } });
      toast("폴더를 추가했습니다.");
      refresh();
    } catch (e) {
      toast(`${(e as Error).message} '할 일' 화면 아래에서 경로를 직접 넣어 추가할 수 있습니다.`, true);
      location.hash = "#/";
    }
  };

  const page = route.name === "home" ? "home" : route.name === "usage" ? "usage" : route.name === "bench" ? "bench"
    : route.name === "setup" ? "setup" : route.name === "settings" ? "settings" : "";
  return (
    <div className="ide">
      <div className="ide-row">
        {sbOpen ? <>
          <Sidebar folders={folders} groups={groups} current={ws} currentTab={route.name === "run" || route.name === "project" ? route.tab : ""} page={page}
                   width={sbW} onNew={(project, machine) => openNew(project ? { project, machine: machine || LOCAL } : {})}
                   onPalette={() => setPalette(true)} onChanged={refresh} onAddFolder={addFolder} />
          <div className="resizer"><span onMouseDown={(e) => { e.preventDefault(); dragSb(e.clientX); }} /></div>
        </> : null}
        {ws ? (
          <Workspace key={`${ws.machine}|${ws.project}|${ws.run || ""}`} ws={ws} tabParam={(route as { tab: string }).tab || null}
                     panelParam={(route as { panel?: string }).panel || null} sessions={sessions} rpWidth={rpW}
                     onSeen={reloadWorks} onSessions={reloadSessions} onNewRun={openNew} onRpResize={dragRp} />
        ) : (
          <main className="ide-center">
            <div className="ide-page">
              {route.name === "home" || route.name === "session" ? <Home groups={groups} error={error} folders={folders} onNewRun={openNew} onChanged={refresh} /> : null}
              {route.name === "usage" && <UsageView machine={route.machine} groups={groups} />}
              {route.name === "setup" && <SetupView machine={route.machine} groups={groups} />}
              {route.name === "settings" && <SettingsView />}
              {route.name === "bench" && <BenchView dir={route.dir} />}
            </div>
          </main>
        )}
      </div>
      <StatusBar />
      {newRun && <NewRun init={newRun} groups={groups} onClose={() => setNewRun(null)}
                         onStarted={() => { setNewRun(null); refresh(); }} />}
      {palette && <Palette folders={folders} onClose={() => setPalette(false)} onNew={() => openNew({})} />}
    </div>
  );
}
