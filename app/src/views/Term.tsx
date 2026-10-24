import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef } from "react";
import { api } from "../lib/api";
import { SessionStatus } from "../sessions";
import { useUi } from "../ui";

/** 세션 하나의 터미널 (36.19·36.22). 키 입력은 그대로 넘기고 출력은 SSE 로 받는다. 탭을 바꿔도 다시 붙으면 offset 0 부터 다시 그린다. */
export default function Term({ id, active, live, fresh, onStatus, onEnd }: {
  id: string; active: boolean; live: boolean; fresh?: boolean; onStatus?: (s: SessionStatus) => void; onEnd?: () => void;
}) {
  const { toast } = useUi();
  const box = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const cb = useRef({ onStatus, onEnd, live });
  cb.current = { onStatus, onEnd, live };

  useEffect(() => {
    if (!box.current) return;
    const css = getComputedStyle(document.documentElement);
    const v = (n: string, d: string) => css.getPropertyValue(n).trim() || d;
    const t = new Terminal({
      fontFamily: v("--mono", "monospace"), fontSize: 13, lineHeight: 1.15, cursorBlink: true, scrollback: 8000,
      theme: { background: v("--term-bg", "#0b0c0f"), foreground: v("--term-fg", "#d7dae0"), cursor: v("--term-fg", "#d7dae0"),
               selectionBackground: "rgba(120,140,200,0.35)" },
    });
    const fit = new FitAddon();
    t.loadAddon(fit);
    t.open(box.current);
    term.current = t;
    fitRef.current = fit;
    let pending = "";
    let timer = 0;
    const flush = () => {                         // 키 입력을 잠깐 모아서 보낸다(붙여넣기·빠른 타자)
      const data = pending;
      pending = "";
      timer = 0;
      if (data) api("/api/session/input", { method: "POST", body: { id, data } }).catch((e) => toast((e as Error).message, true));
    };
    // 지난 출력을 다시 그리는 동안 터미널이 내는 응답(장치 질의 답 등)은 보내지 않는다 (셸에 글자로 들어감)
    let replaying = !fresh;                       // 막 띄운 세션은 처음 질의에 바로 답해야 한다
    const sub = t.onData((d) => {
      if (replaying || !cb.current.live) return;
      pending += d;
      if (!timer) timer = window.setTimeout(flush, 15);
    });
    let lastSize = "";
    const resize = () => {
      if (!box.current || box.current.offsetWidth === 0) return;     // 숨은 탭은 크기를 바꾸지 않는다
      try { fit.fit(); } catch { return; }
      const key = `${t.rows}x${t.cols}`;
      if (key !== lastSize) {
        lastSize = key;
        api("/api/session/resize", { method: "POST", body: { id, rows: t.rows, cols: t.cols } }).catch(() => {});
      }
    };
    const ro = new ResizeObserver(() => resize());
    ro.observe(box.current);
    resize();
    let offset = 0;
    let closed = false;
    let es: EventSource | null = null;
    const connect = () => {
      if (closed) return;
      const u = new URL("/api/session/stream", location.origin);
      u.searchParams.set("id", id);
      u.searchParams.set("offset", String(offset));
      es = new EventSource(u.toString(), { withCredentials: true });
      es.addEventListener("out", (ev) => {
        const p = JSON.parse((ev as MessageEvent).data) as { data: string; offset: number; reset: boolean };
        if (p.reset) t.reset();
        const first = offset === 0;
        t.write(p.data, first ? () => { window.setTimeout(() => { replaying = false; }, 150); } : undefined);
        offset = p.offset;
      });
      es.addEventListener("status", (ev) => cb.current.onStatus?.(JSON.parse((ev as MessageEvent).data)));
      es.addEventListener("end", () => { es?.close(); cb.current.onEnd?.(); });
      es.onerror = () => { es?.close(); if (!closed) window.setTimeout(connect, 1500); };
    };
    connect();
    const safety = window.setTimeout(() => { replaying = false; }, 2500);   // 출력이 하나도 없을 때
    return () => { window.clearTimeout(safety); closed = true; es?.close(); sub.dispose(); ro.disconnect(); if (timer) flush(); t.dispose(); term.current = null; };
  }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {                                // 탭이 보이게 되면 크기 맞추고 입력 받기
    if (!active) return;
    const id2 = window.requestAnimationFrame(() => { try { fitRef.current?.fit(); } catch { /* 아직 안 그려짐 */ } term.current?.focus(); });
    return () => window.cancelAnimationFrame(id2);
  }, [active]);

  return <div className="term-fill" ref={box} onClick={() => term.current?.focus()} />;
}
