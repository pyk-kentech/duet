// 모델 출력용 마크다운 → React 요소. innerHTML 을 쓰지 않는다(모델 출력은 신뢰하지 않음).
import { Fragment, ReactNode } from "react";

const INLINE_RE = new RegExp([
  "(`+)([\\s\\S]*?[^`])\\1(?!`)",                  // 1,2 code
  "\\*\\*([^*][\\s\\S]*?)\\*\\*",                  // 3 bold
  "\\[([^\\]\\n]+)\\]\\(([^)\\s]+)\\)",            // 4,5 link
  "(https?:\\/\\/[^\\s<>()]+[^\\s<>().,;:!?'\"])", // 6 url
  "(?<![\\w*])\\*([^*\\s][^*\\n]*?)\\*(?![\\w*])", // 7 em
  "(?<![\\w])_([^_\\s][^_\\n]*?)_(?![\\w])",       // 8 em
].join("|"));

const RE = {
  fence: /^\s{0,3}(`{3,}|~{3,})\s*([\w+#.-]*)/,
  heading: /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/,
  hr: /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/,
  quote: /^\s{0,3}>\s?/,
  list: /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/,
  tableSep: /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/,
  verdictOpen: /^\s*<verdict>\s*$/i,
  verdictClose: /^\s*<\/verdict>\s*$/i,
};

let keySeq = 0;
const k = () => `m${keySeq++}`;

function mdLink(label: string, href: string): ReactNode {
  if (/^https?:\/\//i.test(href)) {
    return <a key={k()} href={href} target="_blank" rel="noopener noreferrer">{inline(label)}</a>;
  }
  if (label === href) return <span key={k()} className="localref">{href}</span>;
  return <Fragment key={k()}>{inline(label)} <span className="localref">({href})</span></Fragment>;
}

export function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = String(text);
  while (rest) {
    const m = INLINE_RE.exec(rest);
    if (!m) { out.push(rest); break; }
    if (m.index > 0) out.push(rest.slice(0, m.index));
    if (m[1] !== undefined) out.push(<code key={k()}>{m[2]}</code>);
    else if (m[3] !== undefined) out.push(<strong key={k()}>{inline(m[3])}</strong>);
    else if (m[4] !== undefined) out.push(mdLink(m[4], m[5]));
    else if (m[6] !== undefined) out.push(mdLink(m[6], m[6]));
    else if (m[7] !== undefined) out.push(<em key={k()}>{inline(m[7])}</em>);
    else if (m[8] !== undefined) out.push(<em key={k()}>{inline(m[8])}</em>);
    rest = rest.slice(m.index + m[0].length);
  }
  return out;
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
}

function isBlockStart(line: string, next?: string): boolean {
  return RE.fence.test(line) || RE.heading.test(line) || RE.hr.test(line) || RE.quote.test(line) ||
    RE.list.test(line) || RE.verdictOpen.test(line) || (line.includes("|") && next !== undefined && RE.tableSep.test(next));
}

function VerdictBox({ body }: { body: string }) {
  const status = (/status\s*:\s*\**\s*`?(APPROVED|CHANGES_REQUESTED)/i.exec(body) || [])[1];
  const mustFix = (/must_fix\s*:\s*\**\s*`?(\d+)/i.exec(body) || [])[1];
  return (
    <div className="verdict-box">
      <span className="label">판정</span>
      {status ? <span className={`verdict v-${status.toUpperCase()}`}>{status.toUpperCase() === "APPROVED" ? "승인" : "반려"}</span>
        : <code>{body.trim()}</code>}
      {mustFix !== undefined && <span className="muted small">반드시 고칠 것 {mustFix}건</span>}
    </div>
  );
}

function parseList(lines: string[], start: number): [ReactNode, number] {
  const first = RE.list.exec(lines[start])!;
  const indent = first[1].length;
  const ordered = /\d/.test(first[2]);
  const items: ReactNode[] = [];
  let i = start;
  while (i < lines.length) {
    const m = RE.list.exec(lines[i]);
    if (!m || m[1].length !== indent || /\d/.test(m[2]) !== ordered) break;
    const body = [m[3]];
    i++;
    while (i < lines.length) {
      const l = lines[i];
      if (!l.trim()) {
        const nxt = lines[i + 1];
        if (nxt !== undefined && nxt.trim() && (nxt.match(/^\s*/)![0].length > indent)) { body.push(""); i++; continue; }
        break;
      }
      const lm = RE.list.exec(l);
      if (lm && lm[1].length <= indent) break;
      if (!lm && l.match(/^\s*/)![0].length <= indent && isBlockStart(l, lines[i + 1])) break;
      body.push(lm ? l : l.replace(/^\s+/, ""));
      i++;
    }
    let j = 0;
    const firstLines: string[] = [];
    while (j < body.length && !RE.list.test(body[j]) && !RE.fence.test(body[j])) firstLines.push(body[j++]);
    const head = firstLines.filter(Boolean).flatMap((t, n) => (n ? [<br key={k()} />, ...inline(t.trim())] : inline(t.trim())));
    const restText = j < body.length ? body.slice(j).map((l) => l.replace(new RegExp(`^\\s{0,${indent + 4}}`), "")).join("\n") : "";
    items.push(<li key={k()}>{head}{restText && <Markdown text={restText} />}</li>);
  }
  const n = ordered ? parseInt(first[2], 10) : 1;
  return [ordered ? <ol key={k()} start={n !== 1 ? n : undefined}>{items}</ol> : <ul key={k()}>{items}</ul>, i];
}

export function Markdown({ text }: { text: string }) {
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m: RegExpExecArray | null;
    if ((m = RE.fence.exec(line))) {
      const fence = m[1];
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence)) body.push(lines[i++]);
      i++;
      out.push(<pre key={k()}><code data-lang={m[2] || undefined}>{body.join("\n")}</code></pre>);
      continue;
    }
    if (RE.verdictOpen.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !RE.verdictClose.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push(<VerdictBox key={k()} body={body.join("\n")} />);
      continue;
    }
    if ((m = RE.heading.exec(line))) {
      const level = Math.min(6, m[1].length);
      const Tag = `h${level}` as "h1";
      out.push(<Tag key={k()}>{inline(m[2])}</Tag>);
      i++;
      continue;
    }
    if (RE.hr.test(line)) { out.push(<hr key={k()} />); i++; continue; }
    if (line.includes("|") && i + 1 < lines.length && RE.tableSep.test(lines[i + 1])) {
      const head = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(splitRow(lines[i++]));
      out.push(
        <div key={k()} className="table-scroll"><table>
          <thead><tr>{head.map((c) => <th key={k()}>{inline(c)}</th>)}</tr></thead>
          <tbody>{rows.map((r) => <tr key={k()}>{head.map((_, x) => <td key={k()}>{inline(r[x] || "")}</td>)}</tr>)}</tbody>
        </table></div>);
      continue;
    }
    if (RE.quote.test(line)) {
      const body: string[] = [];
      while (i < lines.length && lines[i].trim() && RE.quote.test(lines[i])) body.push(lines[i++].replace(RE.quote, ""));
      out.push(<blockquote key={k()}><Markdown text={body.join("\n")} /></blockquote>);
      continue;
    }
    if (RE.list.test(line)) {
      const [node, next] = parseList(lines, i);
      out.push(node);
      i = next;
      continue;
    }
    const para = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i], lines[i + 1])) para.push(lines[i++].trim());
    out.push(<p key={k()}>{para.flatMap((t, n) => (n ? [<br key={k()} />, ...inline(t)] : inline(t)))}</p>);
  }
  return <>{out}</>;
}

export function Diff({ text }: { text: string }) {
  if (!text) return <pre className="diff">(변경 없음)</pre>;
  return (
    <pre className="diff">
      {text.split("\n").map((line, n) => {
        let cls = "l";
        if (line.startsWith("diff --git")) cls += " file";
        else if (/^(\+\+\+|---|index |new file|deleted file|commit |similarity|rename )/.test(line)) cls += " meta";
        else if (line.startsWith("@@")) cls += " hunk";
        else if (line.startsWith("[변경 파일 요약]") || line.startsWith("(잠금 파일")) cls += " file";
        else if (line.startsWith("+")) cls += " add";
        else if (line.startsWith("-")) cls += " del";
        return <span key={n} className={cls}>{line || " "}</span>;
      })}
    </pre>
  );
}
