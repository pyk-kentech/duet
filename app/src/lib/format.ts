// 화면에 보이는 숫자·시간·문자열 형식. 모두 한국어.

export function fmtDur(sec: number | undefined | null): string {
  let s = Math.max(0, Math.round(Number(sec) || 0));
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  s = s % 60;
  if (m < 60) return s ? `${m}분 ${s}초` : `${m}분`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}시간 ${m % 60}분`;
  return `${Math.floor(h / 24)}일 ${h % 24}시간`;
}

export function fmtDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function fmtWhen(iso: string | undefined | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff >= 0 && diff < 60) return "방금";
  if (diff >= 0 && diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff >= 0 && diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return fmtDate(d);
}

export function fmtTok(n: number | undefined | null): string {
  const v = Number(n) || 0;
  if (v < 1000) return String(v);
  if (v < 1e6) return (v / 1000).toFixed(v < 10000 ? 1 : 0) + "k";
  return (v / 1e6).toFixed(v < 1e7 ? 2 : 1) + "M";
}

export function fmtUsd(v: number | undefined | null): string {
  return v ? `$${Number(v).toFixed(2)}` : "";
}

export function oneLine(s: string | undefined | null, n = 120): string {
  const t = String(s || "").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

export function baseName(p: string): string {
  return String(p).split(/[\\/]/).filter(Boolean).pop() || p;
}

export function hhmm(iso: string | undefined | null): string {
  if (!iso) return "";
  const t = String(iso);
  return t.length >= 16 ? t.slice(11, 16) : t;
}
