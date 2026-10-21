"""결과 요약 (DESIGN.md 32장): 실행이 끝나면 작은 모델이 무엇을 만들었고 어떻게 실행하는지 정리한다.

보조 호출이다. 실패해도 실행 결과를 바꾸지 않는다. 상태 키 `report`, 기록 파일 이름은 state.report.
"""

from __future__ import annotations

from tenure.agents.base import Mode
from tenure.phases.common import PhaseContext
from tenure.state import DONE_APPROVED
from tenure.workspace import GitError, Workspace

REPORT_ROLE = "report"
MAX_STAT_CHARS = 6_000
MAX_COMMITS_CHARS = 2_000
NOTES_FILE = "IMPLEMENTATION_NOTES.md"


def _outcome(ctx: PhaseContext) -> str:
    st = ctx.state
    if st.status == DONE_APPROVED:
        return "승인 (리뷰어가 통과시킴)" + (" — 중재로 승인" if st.stop_reason == "arbiter" else "")
    last = st.review_history[-1] if st.review_history else {}
    why = {"max_review": "리뷰 상한까지 승인되지 않음", "stalled": "막는 지적이 줄지 않아 멈춤",
           "arbiter_upheld": "중재 뒤에도 막는 지적이 남음", "arbiter_final": "중재 뒤에도 막는 지적이 남음"}
    text = f"미승인 — {why.get(st.stop_reason or '', st.stop_reason or '승인되지 않음')}"
    if last.get("blocking") is not None:
        text += f", 마지막 리뷰의 막는 지적 {last['blocking']}개"
    if st.last_review:
        rel = (ctx.run_dir / st.last_review).relative_to(ctx.workdir).as_posix() \
            if ctx.run_dir.is_relative_to(ctx.workdir) else str(ctx.run_dir / st.last_review)
        text += f" (마지막 리뷰 기록: {rel})"
    return text


def _tests(ctx: PhaseContext) -> str:
    st = ctx.state
    if not st.tests:
        return "tenure 가 돌린 테스트 없음"
    last = st.tests[max(st.tests, key=lambda k: int(k))]
    return f"명령: {last.get('command') or '(없음)'} / 결과: {last.get('status') or '알 수 없음'}"


def _git(ws: Workspace, base: str | None) -> tuple[str, str]:
    if not base:
        return "(기준 커밋 없음)", ""
    try:
        stat = ws.diff_stat(base)
        commits = ws.git("log", "--oneline", "--no-decorate", f"{base}..HEAD")
    except GitError as e:
        return f"(git 오류: {e})", ""
    if len(stat) > MAX_STAT_CHARS:
        stat = stat[:MAX_STAT_CHARS] + "\n... (생략)"
    return stat.strip() or "(바뀐 파일 없음)", commits.strip()[:MAX_COMMITS_CHARS]


def run_report(ctx: PhaseContext, *, force: bool = False, workspace: Workspace | None = None) -> str | None:
    """결과 요약을 만들고 기록 파일 이름을 돌려준다. 꺼져 있거나 이미 했거나 실패하면 None."""
    st, cfg = ctx.state, ctx.cfg
    if (st.is_done("report") and not force) or not cfg.report or REPORT_ROLE not in ctx.agents:
        return None
    ws = workspace or Workspace(ctx.workdir)
    stat, commits = _git(ws, st.base_commit)
    prompt = ctx.prompt(REPORT_ROLE, "report", task=ctx.task, outcome=_outcome(ctx), changed=stat,
                        commits=commits or "(없음)", tests=_tests(ctx),
                        notes=f"{NOTES_FILE} 있음 (구현자의 판단·남긴 일)" if (ctx.workdir / NOTES_FILE).is_file()
                        else f"{NOTES_FILE} 없음")
    ctx.log(f"결과 요약: {cfg.report_agent} {cfg.report_model or '기본 모델'}")
    out = ctx.call(REPORT_ROLE, "report", prompt, Mode.READ, label=f"report_{cfg.report_agent}", optional=True)
    if out is None:
        ctx.log("결과 요약을 만들지 못했습니다(실행 결과는 그대로). 나중에 `tenure report` 로 다시 만들 수 있습니다.")
    else:
        st.report = out.file
        ctx.log(f"결과 요약 → {out.file}")
    st.mark_done("report")
    ctx.save()
    return st.report if out is not None else None
