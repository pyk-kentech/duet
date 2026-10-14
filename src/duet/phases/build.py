"""BuildPhase — 구현 + 교차 리뷰.

workspace.ensure_repo(); base = commit("duet: design")
loop i in 1..max_review:
  implementer.ask(implement 또는 fix)          # WRITE
  commit("duet: impl round i")
  diff = workspace.diff(base, HEAD, exclude=[DESIGN.md])
  reviewer.ask(review)                          # READ
  if workspace.dirty(): 경고 + 되돌림
  verdict → APPROVED면 종료
"""

from __future__ import annotations

from duet.agents.base import Mode
from duet.phases.common import PhaseContext
from duet.phases.debate import DESIGN_FILENAME
from duet.prompts import render
from duet.state import DONE_APPROVED, DONE_UNAPPROVED, PHASE_BUILD, PHASE_DONE
from duet.verdict import parse_verdict
from duet.workspace import Workspace

DIFF_EXCLUDES = (DESIGN_FILENAME,)
TRUNCATED_NOTE = "\n... (diff가 길어 잘림. 나머지는 파일을 직접 열어 확인)"


def truncate_diff(diff: str, max_chars: int) -> str:
    if not diff.strip():
        return "(변경 없음)"
    if len(diff) <= max_chars:
        return diff
    return diff[:max_chars] + TRUNCATED_NOTE


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
                ctx.set_position(PHASE_BUILD, "implement", i)
                ctx.save()
                if i == 1 or not st.last_review:
                    step = "implement"
                    ctx.log(f"[{i}/{self.max_review}] 구현: {self.implementer}")
                    prompt = render("implement", ctx.workdir, task=ctx.task)
                else:
                    step = "fix"
                    ctx.log(f"[{i}/{self.max_review}] 리뷰 반영: {self.implementer}")
                    review_text = ctx.transcript.read(st.last_review)
                    prompt = render("fix", ctx.workdir, task=ctx.task, review=review_text,
                                    reviewer_name=self.reviewer)
                out = ctx.call(self.implementer, step, prompt, Mode.WRITE,
                               label=f"impl{i}_{self.implementer}", round_=i)
                st.last_impl = out.file
                commit = self.ws.commit_all(f"duet: impl round {i}")
                ctx.log(f"[{i}/{self.max_review}] 커밋: {commit}")
                st.mark_done(impl_key)
                ctx.save()

            if not st.is_done(review_key):
                ctx.set_position(PHASE_BUILD, "review", i)
                ctx.save()
                diff = truncate_diff(self.ws.diff(base, "HEAD", exclude=DIFF_EXCLUDES), self.cfg.max_diff_chars)
                ctx.log(f"[{i}/{self.max_review}] 리뷰: {self.reviewer} (diff {len(diff):,}자)")
                prompt = render("review", ctx.workdir, task=ctx.task, diff=diff,
                                implementer_name=self.implementer)
                out = ctx.call(self.reviewer, "review", prompt, Mode.READ,
                               label=f"review{i}_{self.reviewer}", round_=i)
                self._undo_reviewer_changes()
                verdict = parse_verdict(out.text)
                st.last_review = out.file
                st.last_verdict = verdict.status.value
                st.mark_done(review_key)
                ctx.log(f"[{i}/{self.max_review}] 판정: {verdict.describe()}")
                if verdict.approved:
                    st.status = DONE_APPROVED
                    ctx.set_position(PHASE_DONE, "approved", i)
                    ctx.save()
                    return True
                ctx.save()

        st.status = DONE_UNAPPROVED
        ctx.set_position(PHASE_DONE, "unapproved", self.max_review)
        ctx.save()
        return False

    # ---------------------------------------------------------------- helpers
    def _undo_reviewer_changes(self) -> None:
        if not self.ws.dirty():
            return
        files = self.ws.dirty_files()
        self.ctx.log(f"경고: 리뷰어가 파일을 변경함 → 되돌림 ({', '.join(files[:5])}{' ...' if len(files) > 5 else ''})")
        self.ws.restore_clean()
