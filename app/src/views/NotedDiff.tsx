import { useState } from "react";

/** 줄 번호가 붙은 diff. 줄을 누르면 메모를 단다 (DESIGN.md 36.14, Daintree·Orca·Schaltwerk 의 아이디어). */
export interface Note {
  id: string; file: string; line: number; side: "new" | "old"; text: string; line_text: string | null;
  status: "open" | "sent"; sent_round: number | null; created: string; stale?: boolean;
}
interface Row { text: string; cls: string; file?: string; oldNo?: number; newNo?: number }

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

export function parseDiff(text: string): Row[] {
  const rows: Row[] = [];
  let file = "", oldNo = 0, newNo = 0, inHunk = false;
  for (const line of text.split("\n")) {
    if (line.startsWith("diff --git")) {
      const m = / b\/(.+)$/.exec(line);
      file = m ? m[1] : ""; inHunk = false;
      rows.push({ text: line, cls: "file" });
    } else if (line.startsWith("+++ ")) {
      if (line.startsWith("+++ b/")) file = line.slice(6);
      rows.push({ text: line, cls: "meta" });
    } else if (/^(---|index |new file|deleted file|commit |similarity|rename |Binary )/.test(line) && !inHunk) {
      rows.push({ text: line, cls: "meta" });
    } else if (HUNK.test(line)) {
      const m = HUNK.exec(line)!;
      oldNo = Number(m[1]); newNo = Number(m[2]); inHunk = true;
      rows.push({ text: line, cls: "hunk" });
    } else if (inHunk && line.startsWith("+")) {
      rows.push({ text: line, cls: "add", file, newNo: newNo++ });
    } else if (inHunk && line.startsWith("-")) {
      rows.push({ text: line, cls: "del", file, oldNo: oldNo++ });
    } else if (inHunk && line.startsWith(" ")) {
      rows.push({ text: line, cls: "", file, oldNo: oldNo++, newNo: newNo++ });
    } else {
      rows.push({ text: line, cls: line.startsWith("[변경 파일 요약]") || line.startsWith("(잠금 파일") ? "file" : inHunk ? "meta" : "" });
    }
  }
  return rows;
}

function anchor(r: Row): { side: "new" | "old"; line: number } | null {
  if (!r.file) return null;
  if (r.newNo != null) return { side: "new", line: r.newNo };
  if (r.oldNo != null) return { side: "old", line: r.oldNo };
  return null;
}

export function NotedDiff({ text, notes, canEdit, onAdd, onDelete }: {
  text: string; notes: Note[]; canEdit: boolean;
  onAdd: (n: { file: string; line: number; side: "new" | "old"; text: string }) => Promise<boolean>;
  onDelete: (id: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  if (!text) return <pre className="diff">(변경 없음)</pre>;
  const rows = parseDiff(text);
  const key = (file: string, side: string, line: number) => `${file}\u0000${side}\u0000${line}`;
  const byLine = new Map<string, Note[]>();
  for (const n of notes) {
    const k = key(n.file, n.side, n.line);
    byLine.set(k, [...(byLine.get(k) || []), n]);
  }
  const save = async (file: string, side: "new" | "old", line: number) => {
    if (!draft.trim()) return;
    if (await onAdd({ file, line, side, text: draft.trim() })) { setEditing(null); setDraft(""); }
  };
  return (
    <div className="diff noted" role="table" aria-label="변경 사항">
      {rows.map((r, i) => {
        const a = anchor(r);
        const k = a ? key(r.file!, a.side, a.line) : "";
        const here = a ? byLine.get(k) || [] : [];
        return (
          <div key={i}>
            <div className={`dl ${r.cls}${a && canEdit ? " notable" : ""}`} role="row"
                 onClick={a && canEdit ? () => { setEditing(editing === k ? null : k); setDraft(""); } : undefined}
                 title={a && canEdit ? "눌러서 이 줄에 메모" : undefined}>
              <span className="ln">{r.oldNo ?? ""}</span><span className="ln">{r.newNo ?? ""}</span>
              <span className="code">{r.text || " "}</span>
            </div>
            {here.map((n) => (
              <div key={n.id} className={`dnote${n.status === "sent" ? " sent" : ""}`}>
                <span className="who">메모</span>
                <span className="body">{n.text}</span>
                {n.stale ? <span className="badge warn" title="메모를 단 뒤 이 줄이 바뀌었습니다">오래됨</span> : null}
                {n.status === "sent" ? <span className="badge ok">보냄 · 후속 {n.sent_round}</span>
                  : canEdit ? <button className="btn btn-sm" type="button" onClick={() => onDelete(n.id)} aria-label="메모 지우기">지우기</button> : null}
              </div>
            ))}
            {a && editing === k ? (
              <div className="dnote editing">
                <textarea autoFocus rows={2} value={draft} placeholder={`${r.file}:${a.line}${a.side === "old" ? " (바뀌기 전)" : ""} 에 대한 메모`}
                          onChange={(e) => setDraft(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save(r.file!, a.side, a.line); if (e.key === "Escape") setEditing(null); }} />
                <div className="row">
                  <button className="btn btn-sm btn-primary" type="button" disabled={!draft.trim()} onClick={() => save(r.file!, a.side, a.line)}>메모 달기</button>
                  <button className="btn btn-sm" type="button" onClick={() => setEditing(null)}>취소</button>
                  <span className="faint small">Ctrl+Enter 로 저장</span>
                </div>
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
