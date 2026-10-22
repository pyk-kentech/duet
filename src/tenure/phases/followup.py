"""끝난 실행에 덧붙이는 한 번의 구현 라운드 (DESIGN.md 36.14).

- resolve: worktree 에서 기준 브랜치를 병합해 충돌 표시를 만들고, 구현 담당에게 풀게 한 뒤 커밋·테스트.
- notes:   사람이 남긴 줄 메모를 구현 담당에게 보내 고치게 한 뒤 커밋·테스트.

기록은 state.followups 에 {kind, n, file, commit, tests} 로 남는다. 다시 리뷰할지는 사람이 정한다.
"""

from __future__ import annotations

import datetime as dt

from tenure import notes as notelib
from tenure.agents.base import Mode
from tenure.phases.common import PhaseContext, PhaseStop
from tenure.runner import env_drops
from tenure.state import FAILED
from tenure.testing import STATUS_KO, describe_for_prompt, resolve_command, run_tests
from tenure.workspace import Workspace

RESOLVE, NOTES = "resolve", "notes"
MARKERS = ("<<<<<<< ", ">>>>>>> ")


def conflicted_files(ws: Workspace) -> list[str]:
    return [f for f in ws.git("diff", "--name-only", "--diff-filter=U").splitlines() if f.strip()]


def files_with_markers(ws: Workspace, files: list[str]) -> list[str]:
    left = []
    for f in files:
        try:
            text = (ws.workdir / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(ln.startswith(m) for ln in text.splitlines() for m in MARKERS):
            left.append(f)
    return left


class FollowupPhase:
    def __init__(self, ctx: PhaseContext, implementer: str):
        self.ctx, self.state, self.cfg = ctx, ctx.state, ctx.cfg
        self.implementer = implementer
        self.ws = Workspace(ctx.workdir)

    @property
    def n(self) -> int:
        return len(self.state.followups) + 1

    # ---------------------------------------------------------------- resolve
    def resolve(self, base_branch: str) -> dict:
        ctx, ws = self.ctx, self.ws
        if ws.dirty():
            ws.commit_all(f"tenure: 남은 변경 보존 (후속 {self.n})")
        ws.git("merge", "--no-ff", "--no-commit", base_branch, check=False)   # 충돌이면 exit 1 — 아래에서 파일로 본다
        conflicts = conflicted_files(ws)
        if not conflicts:
            if ws.git("rev-parse", "--verify", "--quiet", "MERGE_HEAD", check=False).strip():
                commit = ws.commit_all(f"tenure: {base_branch} 병합 (충돌 없음)")
                ctx.log(f"기준 브랜치 {base_branch} 를 충돌 없이 병합: {commit}")
            else:
                commit = ws.head()
                ctx.log(f"기준 브랜치 {base_branch} 의 변경이 이미 들어 있습니다.")
            return self._finish(RESOLVE, None, commit, extra={"conflicts": []})
        ctx.log(f"충돌 {len(conflicts)}개: {', '.join(conflicts[:8])} → 구현 담당({self.implementer})에게 맡김")
        prompt = ctx.prompt(self.implementer, "resolve", task=ctx.task, base_branch=base_branch,
                            conflicts="\n".join(f"- {f}" for f in conflicts))
        out = self._call("resolve", prompt)
        left = files_with_markers(ws, conflicts)
        if left:
            ws.git("merge", "--abort", check=False)
            raise PhaseStop(f"충돌 표시가 남아 병합을 되돌렸습니다: {', '.join(left[:8])}", FAILED)
        commit = ws.commit_all(f"tenure: {base_branch} 병합 충돌 해결")
        ctx.log(f"충돌 해결 커밋: {commit}")
        return self._finish(RESOLVE, out, commit, extra={"conflicts": conflicts})

    # ---------------------------------------------------------------- notes
    def send_notes(self) -> dict:
        ctx, ws = self.ctx, self.ws
        items = notelib.open_notes(ctx.run_dir)
        if not items:
            raise PhaseStop("보낼 메모가 없습니다.", self.state.status)
        if ws.dirty():
            ws.commit_all(f"tenure: 남은 변경 보존 (후속 {self.n})")
        ctx.log(f"줄 메모 {len(items)}개 → 구현 담당({self.implementer})")
        prompt = ctx.prompt(self.implementer, "notes", task=ctx.task, notes=notelib.format_for_prompt(items),
                            tests=self._last_tests_text())
        out = self._call("notes", prompt)
        commit = ws.commit_all(f"tenure: 줄 메모 반영 (후속 {self.n})")
        ctx.log(f"메모 반영 커밋: {commit}")
        notelib.mark_sent(ctx.run_dir, {n["id"] for n in items}, self.n)
        return self._finish(NOTES, out, commit, extra={"notes": [n["id"] for n in items]})

    # ---------------------------------------------------------------- helpers
    def _call(self, step: str, prompt: str) -> str:
        out = self.ctx.call(self.implementer, step, prompt, Mode.WRITE,
                            label=f"followup{self.n}_{step}_{self.implementer}", round_=self.state.round)
        return out.file

    def _finish(self, kind: str, file: str | None, commit: str, extra: dict) -> dict:
        rec = {"kind": kind, "n": self.n, "file": file, "commit": commit,
               "at": dt.datetime.now().isoformat(timespec="seconds"), **extra}
        rec["tests"] = self._run_tests()
        self.state.followups.append(rec)
        self.ctx.save()
        return rec

    def _run_tests(self) -> dict | None:
        ctx = self.ctx
        resolved = resolve_command(ctx.workdir, self.cfg.test_command)
        if resolved is None:
            ctx.log("테스트: 명령 없음 (건너뜀)")
            return None
        command, source = resolved
        ctx.log(f"테스트: {command} ({source})")
        result = run_tests(ctx.workdir, command, source, self.cfg.test_timeout_sec,
                           drop_env=env_drops(self.cfg.env_strip, self.cfg.env_keep))
        if self.ws.dirty():
            self.ws.restore_clean()
        path = ctx.transcript.save(f"followup{self.n}_test", describe_for_prompt(result), {
            "agent": "tenure", "adapter": "tenure", "step": "test", "mode": "run", "round": self.state.round,
            "duration_sec": result.duration_sec, "exit_code": result.exit_code,
            "ok": result.status == "passed", "test_status": result.status, "command": command,
            "rate_limited": False, "timed_out": result.status == "timeout"})
        ctx.log(f"테스트 {STATUS_KO[result.status]}: {result.summary} → {path.name}")
        rec = {**result.to_dict(), "file": path.name}
        rec.pop("output_tail", None)
        return rec

    def _last_tests_text(self) -> str:
        st = self.state
        last = latest_tests(st.tests, st.followups)
        if not last or not last.get("file"):
            return describe_for_prompt(None)
        try:
            return self.ctx.transcript.read(last["file"]).strip()
        except OSError:
            return describe_for_prompt(None)


def latest_tests(tests: dict, followups: list[dict]) -> dict | None:
    """마지막으로 돈 테스트 결과: 후속 라운드가 있으면 그것, 없으면 리뷰 라운드의 마지막."""
    for f in reversed(followups or []):
        if f.get("tests"):
            return f["tests"]
    if tests:
        return tests[max(tests, key=lambda k: int(k) if str(k).isdigit() else -1)]
    return None
