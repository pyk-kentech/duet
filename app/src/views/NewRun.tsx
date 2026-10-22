// 새 실행 창. 위에는 꼭 필요한 칸(폴더·과제·첨부·워크플로), 아래 '자세히'에 나머지(역할·라운드·모델·고급 설정).
import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Group } from "../data";
import { api, LOCAL } from "../lib/api";
import { WORKFLOW_NOTE } from "../lib/labels";
import { hrefProject, hrefRun } from "../lib/router";
import { Modal, useUi } from "../ui";
import { FolderButton } from "./FolderPicker";

export interface NewRunInit { machine?: string; project?: string; defaults?: Record<string, any>; hasDesign?: boolean }

interface OptionDef { key: string; label: string; help: string; kind: "bool" | "int" | "choice" | "text"; group: string; group_label: string;
  choices: string[]; min: number | null; max: number | null; run_dialog: boolean; effective: any; default: any }
interface SettingsView { settings: { workspace_roots?: string[] }; effective: Record<string, any>; options: OptionDef[];
  suggestions: Record<string, any> }
interface WorkflowItem { id: string; description?: string; summary?: string; source?: string; error?: string }

const ATTACH_MAX_FILES = 10;
const ATTACH_MAX_BYTES = 20 * 1024 * 1024;
const EFFORTS = ["", "low", "medium", "high", "xhigh"];
const EFFORT_LABEL: Record<string, string> = { "": "기본", low: "낮음", medium: "보통", high: "높음", xhigh: "아주 높음" };
const fmtBytes = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`);

function readAsBase64(file: File): Promise<{ name: string; data: string }> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve({ name: file.name, data: String(r.result).split(",", 2)[1] || "" });
    r.onerror = () => reject(r.error || new Error(file.name));
    r.readAsDataURL(file);
  });
}

export default function NewRun({ init, groups, onClose, onStarted }: {
  init: NewRunInit; groups: Group[] | null; onClose: () => void; onStarted: () => void;
}) {
  const { toast } = useUi();
  const fixed = !!init.project;
  const [machine, setMachine] = useState(init.machine || LOCAL);
  const [project, setProject] = useState(init.project || "");
  const [task, setTask] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [workflow, setWorkflow] = useState("auto");
  const [workflows, setWorkflows] = useState<WorkflowItem[]>([]);
  const [sv, setSv] = useState<SettingsView | null>(null);
  const [nativeOk, setNativeOk] = useState(false);
  const [adv, setAdv] = useState<Record<string, any>>({});
  const [opts, setOpts] = useState<Record<string, any>>({});
  const [mock, setMock] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    api<SettingsView>("/api/settings").then(setSv).catch(() => {});
    api<{ native_picker?: boolean }>("/api/server").then((s) => setNativeOk(!!s.native_picker)).catch(() => {});
  }, []);
  useEffect(() => {
    api<{ workflows: WorkflowItem[]; default: string }>("/api/workflows", { query: { project: project || undefined }, machine })
      .then((r) => setWorkflows(r.workflows.filter((w) => w.source !== "error"))).catch(() => setWorkflows([]));
  }, [machine, project]);

  const eff = useMemo(() => (init.defaults && !init.defaults.error ? init.defaults : sv?.effective || {}), [init.defaults, sv]);
  const classic = workflow === "classic";
  const set = (k: string, v: any) => setAdv((a) => ({ ...a, [k]: v }));
  const runOptions = (sv?.options || []).filter((o) => o.run_dialog);
  const optGroups = [...new Set(runOptions.map((o) => o.group_label))];
  const suggest = (agent: string): { id: string; label?: string; note?: string }[] => {
    const s = sv?.suggestions?.[agent];
    return Array.isArray(s) ? s : Array.isArray(s?.models) ? s.models : [];
  };

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const next = [...files];
    for (const f of Array.from(list)) {
      if (next.length >= ATTACH_MAX_FILES) { toast(`첨부는 ${ATTACH_MAX_FILES}개까지입니다.`, true); break; }
      if (next.reduce((a, x) => a + x.size, 0) + f.size > ATTACH_MAX_BYTES) { toast("첨부는 합쳐서 20MB 까지입니다.", true); break; }
      next.push(f);
    }
    setFiles(next);
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const p = project.trim();
    const why = !p ? "작업 폴더를 정하세요." : !/^([/~]|[A-Za-z]:[\\/]|\\\\)/.test(p) ? "작업 폴더는 절대 경로여야 합니다 (/…, ~/…, C:\\…)."
      : !task.trim() ? "과제를 입력하세요." : classic && adv.implementer && adv.reviewer && adv.implementer === adv.reviewer ? "구현 담당과 리뷰 담당은 달라야 합니다." : "";
    if (why) { setProblem(why); return; }
    setBusy(true);
    setProblem("");
    try {
      const body: Record<string, unknown> = {
        project: p, task, workflow: workflow === "auto" ? "auto" : workflow, mock,
        ...(classic ? { implementer: adv.implementer || undefined, reviewer: adv.reviewer || undefined, synth: adv.synth || undefined } : {}),
        debate_rounds: adv.debate_rounds ?? "", max_review: adv.max_review ?? "",
        claude_model: (adv.claude_model || "").trim(), claude_effort: adv.claude_effort || "",
        codex_model: (adv.codex_model || "").trim(), codex_effort: adv.codex_effort || "",
        test_command: (adv.test_command || "").trim(), block_severity: adv.block_severity || "", stall_rounds: adv.stall_rounds ?? "",
        design_only: !!adv.design_only, skip_design: !!adv.skip_design, force: !!adv.force, options: opts,
      };
      if (files.length) body.attachments = await Promise.all(files.map(readAsBase64));
      const job = await api<{ id: string; project: string; run_id?: string; worktree?: boolean }>("/api/actions/run", { method: "POST", body, machine });
      toast(job.worktree ? "실행을 시작했습니다. 이 작업은 따로 만든 worktree·브랜치에서 돕니다." : "실행을 시작했습니다.");
      onStarted();
      follow(machine, job.project || p, job.run_id);
    } catch (e) {
      setProblem((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal onClose={onClose} label="새 실행" wide>
      <form onSubmit={submit}>
        <div className="dialog-head"><h2>새 실행</h2><span className="spacer" />
          <button type="button" className="btn btn-sm" onClick={onClose}>닫기</button></div>
        <div className="dialog-body col" style={{ gap: 14 }}>
          {(groups || []).length > 1 ? (
            <label className="field">머신
              <select value={machine} disabled={fixed} onChange={(e) => setMachine(e.target.value)}>
                {(groups || []).map((g) => <option key={g.id} value={g.id}>{g.local ? "이 머신" : g.name}</option>)}
              </select></label>
          ) : null}
          <label className="field">작업 폴더
            <div className="row">
              <input type="text" value={project} readOnly={fixed} onChange={(e) => setProject(e.target.value)} spellCheck={false}
                     placeholder="절대 경로 (없으면 만듭니다)" autoFocus={!fixed} />
              {!fixed ? <FolderButton machine={machine} value={project} onPick={setProject} nativeOk={nativeOk} /> : null}
            </div>
            {!fixed && (sv?.settings.workspace_roots || []).length ? (
              <div className="chips">{(sv!.settings.workspace_roots || []).map((r) => (
                <button key={r} type="button" className="chip" style={{ cursor: "pointer", border: "none" }}
                        onClick={() => setProject(r.replace(/[\\/]+$/, "") + (r.includes("\\") ? "\\" : "/"))}>{r}</button>))}</div>
            ) : null}
          </label>
          <label className="field">과제
            <textarea value={task} onChange={(e) => setTask(e.target.value)} autoFocus={fixed} rows={8}
                      placeholder="무엇을 만들거나 고칠지 적어 주세요. 요구가 분명할수록 빠르고 싸게 끝납니다." />
          </label>
          <div className="field">첨부
            <div className="row" style={{ flexWrap: "wrap" }}>
              <label className="btn btn-sm" style={{ cursor: "pointer" }}>파일 추가
                <input type="file" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} /></label>
              <span className="faint small">{files.length ? `${files.length}개 · ${fmtBytes(files.reduce((a, f) => a + f.size, 0))}` : "화면 시안·참고 문서·스크린샷을 붙이면 설계·구현 모델이 함께 봅니다."}</span>
            </div>
            {files.length ? <div className="chips">{files.map((f, i) => (
              <span key={i} className="chip">{f.name} <span className="faint">{fmtBytes(f.size)}</span>
                <button type="button" aria-label={`${f.name} 빼기`} style={{ border: "none", background: "none", cursor: "pointer" }}
                        onClick={() => setFiles(files.filter((_, k) => k !== i))}>×</button></span>))}</div> : null}
          </div>
          <label className="field">워크플로
            <select value={workflow} onChange={(e) => setWorkflow(e.target.value)}>
              <option value="auto">auto — {WORKFLOW_NOTE.auto} (추천)</option>
              {workflows.map((w) => <option key={w.id} value={w.id}>{w.id} — {WORKFLOW_NOTE[w.id] || w.description || ""}</option>)}
            </select>
            <span className="faint small">{workflows.find((w) => w.id === workflow)?.summary || (workflow === "auto" ? "기존 프로젝트·요구가 분명한 일은 quick, 짧고 열린 새 과제는 classic." : "")}</span>
          </label>

          <details>
            <summary className="muted" style={{ cursor: "pointer" }}>자세히 — 역할·라운드·모델·고급 설정</summary>
            <div className="col" style={{ marginTop: 12 }}>
              {classic ? (
                <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                  {(["implementer", "reviewer"] as const).map((k) => (
                    <label key={k} className="field" style={{ minWidth: 160 }}>{k === "implementer" ? "구현 담당" : "리뷰 담당"}
                      <select value={adv[k] ?? eff[k] ?? ""} onChange={(e) => set(k, e.target.value)}>
                        <option value="claude">claude</option><option value="codex">codex</option></select></label>
                  ))}
                  <label className="field" style={{ minWidth: 160 }}>설계 종합
                    <select value={adv.synth ?? ""} onChange={(e) => set("synth", e.target.value)}>
                      <option value="">설정값 ({eff.synth || "-"})</option><option value="claude">claude</option><option value="codex">codex</option></select></label>
                </div>
              ) : null}
              <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                <label className="field" style={{ width: 140 }}>설계 토론 라운드
                  <input type="number" min={0} max={5} placeholder={String(eff.debate_rounds ?? "")} value={adv.debate_rounds ?? ""} onChange={(e) => set("debate_rounds", e.target.value)} /></label>
                <label className="field" style={{ width: 140 }}>리뷰 최대 횟수
                  <input type="number" min={1} max={10} placeholder={String(eff.max_review ?? "")} value={adv.max_review ?? ""} onChange={(e) => set("max_review", e.target.value)} /></label>
                <label className="field" style={{ width: 160 }}>반려 기준
                  <select value={adv.block_severity ?? ""} onChange={(e) => set("block_severity", e.target.value)}>
                    <option value="">설정값 ({eff.block_severity || "P2"})</option><option value="P1">P1 만</option><option value="P2">P1·P2</option><option value="P3">P1·P2·P3</option></select></label>
                <label className="field" style={{ flex: 1, minWidth: 220 }}>테스트 명령
                  <input type="text" value={adv.test_command ?? ""} onChange={(e) => set("test_command", e.target.value)} spellCheck={false}
                         placeholder={eff.test_command && eff.test_command !== "auto" ? `설정값: ${eff.test_command}` : "자동 감지 (예: python -m pytest -q)"} /></label>
              </div>
              {(["claude", "codex"] as const).map((a) => (
                <div key={a} className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                  <label className="field" style={{ flex: 1, minWidth: 240 }}>{a} 모델
                    <input type="text" list={`models-${a}`} value={adv[`${a}_model`] ?? ""} onChange={(e) => set(`${a}_model`, e.target.value)}
                           placeholder={(eff[a] || {}).model || "CLI 기본"} spellCheck={false} />
                    <datalist id={`models-${a}`}>{suggest(a).map((s) => <option key={s.id} value={s.id}>{s.label || s.id}{s.note ? ` · ${s.note}` : ""}</option>)}</datalist>
                  </label>
                  <label className="field" style={{ width: 160 }}>{a} 추론 강도
                    <select value={adv[`${a}_effort`] ?? ""} onChange={(e) => set(`${a}_effort`, e.target.value)}>
                      {EFFORTS.map((x) => <option key={x} value={x}>{x ? EFFORT_LABEL[x] : `기본 (${(eff[a] || {}).effort_label || "설정값"})`}</option>)}</select></label>
                </div>
              ))}
              <div className="row" style={{ gap: 16, flexWrap: "wrap" }}>
                <label className="row small"><input type="checkbox" checked={!!adv.design_only} onChange={(e) => { set("design_only", e.target.checked); if (e.target.checked) set("skip_design", false); }} /> 설계만</label>
                <label className="row small" title={fixed && init.hasDesign === false ? "DESIGN.md 가 없어서 고를 수 없습니다" : undefined}>
                  <input type="checkbox" disabled={fixed && init.hasDesign === false} checked={!!adv.skip_design} onChange={(e) => { set("skip_design", e.target.checked); if (e.target.checked) set("design_only", false); }} /> 설계 생략 (DESIGN.md 사용)</label>
                <label className="row small"><input type="checkbox" checked={!!adv.force} onChange={(e) => set("force", e.target.checked)} /> 비어 있지 않은 폴더도 진행</label>
              </div>
              {optGroups.map((g) => (
                <fieldset key={g} className="card card-pad" style={{ border: "1px solid var(--line)" }}>
                  <legend className="small muted" style={{ padding: "0 6px" }}>{g}</legend>
                  <div className="col">{runOptions.filter((o) => o.group_label === g).map((o) => (
                    <OptionField key={o.key} o={o} value={opts[o.key]} onChange={(v) => setOpts((x) => {
                      const n = { ...x };
                      if (v === undefined) delete n[o.key]; else n[o.key] = v;
                      return n;
                    })} />
                  ))}</div>
                </fieldset>
              ))}
            </div>
          </details>

          <label className="row small"><input type="checkbox" checked={mock} onChange={(e) => setMock(e.target.checked)} /> mock — 실제 모델을 부르지 않고 흐름만 확인</label>
          {!mock ? <div className="faint small">실제 Claude·Codex 를 부르므로 구독 사용량을 씁니다.</div> : null}
          {problem ? <div className="alert alert-bad"><span>{problem}</span></div> : null}
        </div>
        <footer className="dialog-foot">
          <button className="btn" type="button" onClick={onClose}>취소</button>
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "시작하는 중…" : "시작"}</button>
        </footer>
      </form>
    </Modal>
  );
}

function OptionField({ o, value, onChange }: { o: OptionDef; value: any; onChange: (v: any) => void }) {
  const shown = value === undefined ? o.effective : value;
  const changed = value !== undefined;
  return (
    <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="small"><b>{o.label}</b>{changed ? <span className="badge info" style={{ marginLeft: 6 }}>이번 실행만</span> : null}</div>
        <div className="faint small">{o.help}</div>
      </div>
      <div style={{ width: 200 }}>
        {o.kind === "bool" ? (
          <label className="row small"><input type="checkbox" checked={!!shown} onChange={(e) => onChange(e.target.checked)} />{shown ? "켬" : "끔"}</label>
        ) : o.kind === "choice" ? (
          <select value={String(shown ?? "")} onChange={(e) => onChange(e.target.value)}>{o.choices.map((c) => <option key={c} value={c}>{c}</option>)}</select>
        ) : o.kind === "int" ? (
          <input type="number" min={o.min ?? undefined} max={o.max ?? undefined} value={shown ?? ""} onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />
        ) : (
          <input type="text" value={shown ?? ""} onChange={(e) => onChange(e.target.value)} spellCheck={false} />
        )}
        {changed ? <button type="button" className="btn btn-sm" style={{ marginTop: 4 }} onClick={() => onChange(undefined)}>설정값으로</button> : null}
      </div>
    </div>
  );
}

/** 시작한 실행이 잡히면 그 화면으로 이동한다(30초까지). */
async function follow(machine: string, project: string, runId?: string) {
  location.hash = hrefProject(machine, project);
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 900));
    try {
      const d = await api<{ live: { run_id?: string } | null; runs: { run_id: string }[] }>("/api/runs", { query: { project }, machine });
      // 화면이 실행 id 를 미리 정한다(여러 작업이 동시에 돌아도 이 실행을 따라가게, 36.14)
      if (runId ? d.runs.some((r) => r.run_id === runId) : d.live?.run_id) { location.hash = hrefRun(machine, project, runId || d.live!.run_id!); return; }
    } catch { /* 폴더가 아직 등록 전 */ }
  }
}
