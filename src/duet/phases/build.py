"""BuildPhase — 구현 + 교차 리뷰.

workspace.ensure_repo(); base = commit("duet: design")
loop i in 1..max_review:
  implementer.ask(implement 또는 fix)          # WRITE
  commit("duet: impl round i")
  (리뷰 전 남은 변경이 있으면 커밋해서 보존)
  diff = 변경 파일 요약 + workspace.diff(base, HEAD, exclude=[DESIGN.md, 잠금 파일])
  reviewer.ask(review)                          # READ
  if workspace.dirty(): 경고 + 되돌림
  verdict → APPROVED면 종료

resume 키:
  build:base        기준 커밋 완료
  impl:i:called     구현/수정 호출 성공(유료) — 커밋 전에 죽어도 다시 부르지 않는다
  impl:i            커밋까지 완료
  test:i            duet 가 테스트 실행 (결과는 state.tests[i], 기록 NN_test{i}.md)
  review:i          리뷰 + 판정 완료 (판정은 policy.decide: 심각도 기준·테스트 결과 반영)

멈춤: 승인 → done_approved / 상한 도달 → done_unapproved(stop_reason=max_review)
      막는 지적 수가 stall_rounds 라운드 연속 최저치를 못 갱신 → done_unapproved(stop_reason=stalled)
"""

from __future__ import annotations

from duet.agents.base import Mode
from duet.phases.common import PhaseContext
from duet.phases.debate import DESIGN_FILENAME
from duet.policy import decide, stalled
from duet.prompts import render
from duet.testing import STATUS_KO, describe_for_prompt, resolve_command, run_tests
from duet.state import DONE_APPROVED, DONE_UNAPPROVED, PHASE_BUILD, PHASE_DONE
from duet.verdict import parse_verdict
from duet.workspace import Workspace

DIFF_EXCLUDES = (DESIGN_FILENAME,)
TRUNCATED_NOTE = "\n... (diff가 길어 잘림. 위의 변경 파일 요약을 보고 나머지는 파일을 직접 열어 확인)"


def truncate_diff(diff: str, max_chars: int) -> str:
    if not diff.strip():
        return "(변경 없음)"
    if len(diff) <= max_chars:
        return diff
    return diff[:max_chars] + TRUNCATED_NOTE


def build_review_diff(ws: Workspace, base: str, excludes_glob: list[str], max_chars: int) -> str:
    """리뷰어에게 줄 diff. 맨 앞의 파일 요약(stat)은 잘리지 않게 두고, 본문 diff 만 자른다."""
    stat = ws.diff_stat(base, "HEAD", exclude=DIFF_EXCLUDES)
    body = ws.diff(base, "HEAD", exclude=DIFF_EXCLUDES, exclude_globs=excludes_glob)
    if not stat.strip() and not body.strip():
        return "(변경 없음)"
    header = "[변경 파일 요약]\n" + stat.rstrip() + "\n"
    if excludes_glob:
        header += f"(잠금 파일 등은 아래 diff 에서 뺐음: {', '.join(excludes_glob)})\n"
    budget = max(1000, max_chars - len(header))
    return header + "\n" + truncate_diff(body, budget)


class BuildPhase:
    def __init__(self, ctx: PhaseContext, workspace: Workspace | None = None):
        self.ctx = ctx
        self.state = ctx.state
        self.cfg = ctx.cfg
        self.ws = workspace or Workspace(ctx.workdir)
        self.implementer = ctx.cfg.implementer
        self.reviewer = ctx.cfg.reviewer
        self.max_review = ctx.cfg.max_review

    # ---------------------------------------------------------------- run
    def run(self) -> bool:
        ctx, st = self.ctx, self.state

        if not st.is_done("build:base"):
            ctx.set_position(PHASE_BUILD, "base", 0)
            self.ws.ensure_repo()
            st.base_commit = self.ws.commit_all("duet: design")
            st.mark_done("build:base")
            ctx.save()
            ctx.log(f"기준 커밋: {st.base_commit}")
        base = st.base_commit
        assert base

        for i in range(1, self.max_review + 1):
            impl_key, review_key = f"impl:{i}", f"review:{i}"

            if not st.is_done(impl_key):
                if not st.is_done(f"{impl_key}:called"):
                    ctx.set_position(PHASE_BUILD, "implement", i)
                    ctx.save()
                    if i == 1 or not st.last_review:
                        step = "implement"
                        ctx.log(f"[{i}/{self.max_review}] 구현: {self.implementer}")
                        prompt = render("implement", ctx.workdir, task=ctx.task, test_hint=self._test_hint())
                    else:
                        step = "fix"
                        ctx.log(f"[{i}/{self.max_review}] 리뷰 반영: {self.implementer}")
                        review_text = ctx.transcript.read(st.last_review)
                        prompt = render("fix", ctx.workdir, task=ctx.task, review=review_text,
                                        reviewer_name=self.reviewer, tests=self._tests_text(i - 1))
                    out = ctx.call(self.implementer, step, prompt, Mode.WRITE,
                                   label=f"impl{i}_{self.implementer}", round_=i)
                    st.last_impl = out.file
                    st.mark_done(f"{impl_key}:called")
                    ctx.save()
                commit = self.ws.commit_all(f"duet: impl round {i}")
                ctx.log(f"[{i}/{self.max_review}] 커밋: {commit}")
                st.mark_done(impl_key)
                ctx.save()

            test_key = f"test:{i}"
            if not st.is_done(test_key):
                ctx.set_position(PHASE_BUILD, "test", i)
                ctx.save()
                self._run_tests(i)
                st.mark_done(test_key)
                ctx.save()

            if not st.is_done(review_key):
                ctx.set_position(PHASE_BUILD, "review", i)
                ctx.save()
                self._preserve_pending_changes(i)
                diff = build_review_diff(self.ws, base, self.cfg.diff_excludes, self.cfg.max_diff_chars)
                ctx.log(f"[{i}/{self.max_review}] 리뷰: {self.reviewer} (diff {len(diff):,}자)")
                prompt = render("review", ctx.workdir, task=ctx.task, diff=diff,
                                implementer_name=self.implementer,
                                tests=self._tests_text(i), previous_review=self._previous_must_fix())
                out = ctx.call(self.reviewer, "review", prompt, Mode.READ,
                               label=f"review{i}_{self.reviewer}", round_=i)
                self._undo_reviewer_changes()
                verdict = parse_verdict(out.text)
                test = st.tests.get(str(i))
                decision = decide(verdict, block_severity=self.cfg.block_severity,
                                  tests_block=bool(test and test.get("status") in ("failed", "timeout")),
                                  require_tests_pass=self.cfg.require_tests_pass)
                st.last_review = out.file
                st.last_verdict = "APPROVED" if decision.approved else "CHANGES_REQUESTED"
                st.review_history.append({
                    "round": i, "file": out.file, "reviewer_status": verdict.status.value,
                    "approved": decision.approved, "blocking": decision.blocking,
                    "must_fix": verdict.must_fix, "severity": verdict.severity,
                    "parse_failed": verdict.parse_failed, "reasons": decision.reasons,
                    "tests": test.get("status") if test else None,
                })
                st.mark_done(review_key)
                ctx.log(f"[{i}/{self.max_review}] 판정: {decision.describe()}")
                if decision.approved:
                    st.status = DONE_APPROVED
                    st.stop_reason = None
                    ctx.set_position(PHASE_DONE, "approved", i)
                    ctx.save()
                    return True
                if self._is_stalled():
                    st.status = DONE_UNAPPROVED
                    st.stop_reason = "stalled"
                    ctx.set_position(PHASE_DONE, "stalled", i)
                    ctx.save()
                    ctx.log(f"⚠️ 수렴 안 됨: 막는 지적 수가 {self.cfg.stall_rounds}라운드 연속 줄지 않아 멈춥니다 "
                            f"({self._blocking_series()}). 마지막 리뷰를 보고 직접 판단하세요.")
                    return False
                ctx.save()

        st.status = DONE_UNAPPROVED
        st.stop_reason = "max_review"
        ctx.set_position(PHASE_DONE, "unapproved", self.max_review)
        ctx.save()
        return False

    # ---------------------------------------------------------------- tests
    def _run_tests(self, i: int) -> None:
        ctx, st = self.ctx, self.state
        resolved = resolve_command(ctx.workdir, self.cfg.test_command)
        if resolved is None:
            ctx.log(f"[{i}/{self.max_review}] 테스트: 명령 없음 (건너뜀)")
            return
        command, source = resolved
        ctx.log(f"[{i}/{self.max_review}] 테스트: {command} ({source})")
        result = run_tests(ctx.workdir, command, source, self.cfg.test_timeout_sec)
        # 테스트가 만든 부산물(캐시·임시 파일)은 커밋하지 않는다. 구현은 이미 커밋돼 있다.
        if self.ws.dirty():
            self.ws.restore_clean()
        body = describe_for_prompt(result)
        path = ctx.transcript.save(f"test{i}", body, {
            "agent": "duet", "adapter": "duet", "step": "test", "mode": "run", "round": i,
            "duration_sec": result.duration_sec, "exit_code": result.exit_code,
            "ok": result.status == "passed", "test_status": result.status, "command": command,
            "rate_limited": False, "timed_out": result.status == "timeout"})
        st.tests[str(i)] = {**result.to_dict(), "file": path.name}
        st.tests[str(i)].pop("output_tail", None)
        ctx.log(f"[{i}/{self.max_review}] 테스트 {STATUS_KO[result.status]}: {result.summary} → {path.name}")

    def _tests_text(self, i: int) -> str:
        t = self.state.tests.get(str(i))
        if not t:
            return describe_for_prompt(None)
        try:
            return self.ctx.transcript.read(t["file"]).strip()
        except (OSError, KeyError):
            return f"명령: {t.get('command')}\n결과: {STATUS_KO.get(t.get('status'), t.get('status'))}"

    def _previous_must_fix(self) -> str:
        if not self.state.last_review:
            return "(첫 리뷰)"
        try:
            text = self.ctx.transcript.read(self.state.last_review)
        except OSError:
            return "(이전 리뷰를 읽을 수 없음)"
        section = extract_section(text, "반드시 고칠 것")
        return section or "(이전 리뷰에서 '반드시 고칠 것' 섹션을 찾지 못함)"

    # ---------------------------------------------------------------- stall
    def _blocking_series(self) -> list[int | None]:
        base = self.state.stall_baseline_round
        return [h.get("blocking") for h in self.state.review_history if h["round"] >= base]

    def _is_stalled(self) -> bool:
        return stalled(self._blocking_series(), self.cfg.stall_rounds)

    def _test_hint(self) -> str:
        c = (self.cfg.test_command or "auto").strip()
        if c.lower() == "none":
            return "(이번 실행은 duet 테스트를 끄도록 설정되어 있다. 그래도 테스트는 작성해라.)"
        if c.lower() != "auto":
            return f"(이번 실행은 설정에 따라 `{c}` 로 테스트한다. duet.toml 의 값보다 이것이 우선한다.)"
        return ""

    # ---------------------------------------------------------------- helpers
    def _preserve_pending_changes(self, i: int) -> None:
        """리뷰 직전에 커밋 안 된 변경이 있으면 커밋해 둔다.

        resume 전에 사용자가 고친 파일 등. 그대로 두면 리뷰 후 '리뷰어가 바꾼 것'으로 오인되어 지워진다.
        """
        if not self.ws.dirty():
            return
        files = self.ws.dirty_files()
        commit = self.ws.commit_all(f"duet: uncommitted changes before review {i}")
        self.ctx.log(f"리뷰 전에 커밋되지 않은 변경 {len(files)}개를 보존 커밋함 ({commit}): "
                     f"{', '.join(files[:5])}{' ...' if len(files) > 5 else ''}")

    def _undo_reviewer_changes(self) -> None:
        if not self.ws.dirty():
            return
        files = self.ws.dirty_files()
        self.ctx.log(f"경고: 리뷰어가 파일을 변경함 → 되돌림 ({', '.join(files[:5])}{' ...' if len(files) > 5 else ''})")
        self.ws.restore_clean()


def extract_section(text: str, title: str) -> str:
    """'## <title>' 섹션 본문 (다음 '## ' 전까지)."""
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    for ln in lines:
        if ln.startswith("## "):
            if inside:
                break
            inside = title in ln
            continue
        if inside:
            out.append(ln)
    return "\n".join(out).strip()
