"""워크플로의 부가 단계: explore(사전 조사), audit(승인 뒤 감사) — DESIGN.md 19.2.

explore:<id>  조사 완료. 결과 파일은 state.explores[id], 이후 propose·implement 프롬프트에 붙는다.
audit:<id>    감사 완료. 감사자별 결과는 state.audits[id]. 참고용이라 실행 상태를 바꾸지 않는다.
"""

from __future__ import annotations

from duet.agents.base import Mode
from duet.phases.build import build_review_diff
from duet.phases.common import PhaseContext
from duet.policy import decide
from duet.state import PHASE_AUDIT, PHASE_EXPLORE
from duet.testing import describe_for_prompt
from duet.verdict import parse_verdict
from duet.workflow import Step
from duet.workspace import Workspace


def run_explore(ctx: PhaseContext, step: Step) -> None:
    st = ctx.state
    key = f"explore:{step.id}"
    if st.is_done(key):
        return
    role = step.role
    assert role
    ctx.set_position(PHASE_EXPLORE, "explore", 0)
    ctx.save()
    ctx.log(f"사전 조사: {role}")
    label = f"explore_{role}" if step.id == "explore" else f"explore_{step.id}_{role}"
    out = ctx.call(role, "explore", ctx.prompt(role, "explore", task=ctx.task), Mode.READ, label=label)
    st.explores[step.id] = out.file
    st.mark_done(key)
    ctx.save()


def run_audit(ctx: PhaseContext, step: Step, workspace: Workspace | None = None) -> None:
    st, cfg = ctx.state, ctx.cfg
    key = f"audit:{step.id}"
    if st.is_done(key):
        return
    ws = workspace or Workspace(ctx.workdir)
    base = st.base_commit
    assert base
    diff = build_review_diff(ws, base, cfg.diff_excludes, cfg.max_diff_chars, (ctx.design_doc,))
    tests = _last_tests_text(ctx)
    results = st.audits.setdefault(step.id, [])
    done_roles = {r["role"] for r in results}
    for role in step.roles:
        if role in done_roles:
            continue
        ctx.set_position(PHASE_AUDIT, "audit", st.round)
        ctx.save()
        ctx.log(f"감사: {role} (diff {len(diff):,}자)")
        label = f"audit_{role}" if step.id == "audit" else f"audit_{step.id}_{role}"
        prompt = ctx.prompt(role, "audit", task=ctx.task, diff=diff, tests=tests,
                            run_instruction=_run_instruction(ctx, role))
        out = ctx.call(role, "audit", prompt, Mode.READ, label=label)
        if ws.dirty():
            ctx.log(f"경고: 감사자가 파일을 변경함 → 되돌림 ({', '.join(ws.dirty_files()[:5])})")
            ws.restore_clean()
        verdict = parse_verdict(out.text)
        decision = decide(verdict, block_severity=cfg.block_severity, tests_block=False, require_tests_pass=False)
        results.append({"role": role, "file": out.file, "approved": decision.approved,
                        "blocking": decision.blocking, "severity": verdict.severity,
                        "parse_failed": verdict.parse_failed, "reasons": decision.reasons})
        ctx.log(f"감사 결과({role}): {_audit_summary(verdict, decision)} → {out.file}")
        ctx.save()
    st.mark_done(key)
    ctx.save()


def _audit_summary(verdict, decision) -> str:
    """감사는 참고용이라 '반려'라고 쓰지 않는다 (DESIGN.md 19.2)."""
    if verdict.parse_failed:
        return "확인 필요 — 판정 블록 없음 (참고용)"
    sev = " ".join(f"{k}={(verdict.severity or {}).get(k, 0)}" for k in ("P1", "P2", "P3")) \
        if verdict.severity is not None else f"must_fix={verdict.must_fix}"
    return f"문제 없음 — {sev}" if decision.approved else f"확인 필요 — {sev} (참고용)"


def _run_instruction(ctx: PhaseContext, role: str) -> str:
    if ctx.can_run_commands(role):
        return "전체 테스트를 다시 돌리지 말고, 확인이 필요한 부분만 좁게 실행해 확인해라."
    return ("너는 이 호출에서 명령을 실행할 수 없다(읽기 전용). 코드와 위 테스트 결과를 읽고 판단하고, "
            "실행해 봐야 알 수 있는 것은 그렇다고 밝혀라.")


def _last_tests_text(ctx: PhaseContext) -> str:
    st = ctx.state
    if not st.tests:
        return describe_for_prompt(None)
    last = st.tests[max(st.tests, key=lambda k: int(k))]
    try:
        return ctx.transcript.read(last["file"]).strip()
    except (OSError, KeyError):
        return f"명령: {last.get('command')}\n결과: {last.get('status')}"
