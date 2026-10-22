// 엔진 API. 토큰은 서버가 index.html 의 meta 에 넣어 준다(쿠키로도 열리지만 API 는 헤더 토큰).

export const LOCAL = "local";

const meta = document.querySelector('meta[name="tenure-token"]') as HTMLMetaElement | null;
export const TOKEN = meta && !meta.content.startsWith("__") ? meta.content : (import.meta.env.VITE_TENURE_TOKEN as string) || "";
if (/[?&]t=/.test(location.search)) history.replaceState(null, "", location.pathname + location.hash);

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

type Query = Record<string, string | number | boolean | undefined | null>;

export interface ApiOptions {
  method?: "GET" | "POST" | "DELETE";
  body?: Record<string, unknown>;
  query?: Query;
  machine?: string;
}

export async function api<T = any>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, query, machine } = opts;
  const url = new URL(path, location.origin);
  const q: Query = { ...(query || {}) };
  const remote = machine && machine !== LOCAL;
  if (remote && (method === "GET" || method === "DELETE")) q.machine = machine;
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  const init: RequestInit = { method, headers: { "X-Tenure-Token": TOKEN } };
  if (body !== undefined || method === "POST") {
    const b = { ...(body || {}) } as Record<string, unknown>;
    if (remote) b.machine = machine;
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    init.body = JSON.stringify(b);
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError("서버에 연결할 수 없습니다. 터미널에서 tenure ui 가 켜져 있는지 확인하세요.", 0);
  }
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* 본문 없음 */
  }
  if (!res.ok) throw new ApiError((data && data.error) || `요청 실패 (${res.status})`, res.status);
  return data as T;
}

export interface RunEvent {
  seq: number;
  ts: string;
  kind: "state" | "step_start" | "step_end" | "log" | "attention" | string;
  [k: string]: any;
}

/** 실행 이벤트 구독. 이 머신은 SSE(/api/stream), 원격은 /api/events 폴링. 돌려준 함수로 끊는다. */
export function subscribeEvents(machine: string, project: string, run: string, since: number,
                                onEvents: (evs: RunEvent[]) => void, onEnd?: () => void): () => void {
  let closed = false;
  let last = since;
  if (!machine || machine === LOCAL) {
    let es: EventSource | null = null;
    const open = () => {
      if (closed) return;
      const u = new URL("/api/stream", location.origin);
      u.searchParams.set("project", project);
      u.searchParams.set("run", run);
      u.searchParams.set("since", String(last));
      es = new EventSource(u.toString(), { withCredentials: true });
      const handler = (ev: MessageEvent) => {
        try {
          const e = JSON.parse(ev.data) as RunEvent;
          if (e.seq > last) {
            last = e.seq;
            onEvents([e]);
          }
        } catch { /* 무시 */ }
      };
      for (const k of ["state", "step_start", "step_end", "log", "attention", "message"]) es.addEventListener(k, handler as EventListener);
      es.addEventListener("end", () => { es?.close(); onEnd?.(); });
      es.onerror = () => {                     // 서버가 30분마다 끊는다 → since 로 다시 붙는다
        es?.close();
        if (!closed) setTimeout(open, 2000);
      };
    };
    open();
    return () => { closed = true; es?.close(); };
  }
  const tick = async () => {
    if (closed) return;
    try {
      const r = await api<{ events: RunEvent[]; last_seq: number }>("/api/events", { query: { project, run, since: last }, machine });
      if (r.events.length) {
        last = r.last_seq;
        onEvents(r.events);
      }
    } catch { /* 다음에 다시 */ }
    if (!closed) setTimeout(tick, 3000);
  };
  tick();
  return () => { closed = true; };
}
