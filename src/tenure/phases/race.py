"""경쟁 초안 (DESIGN.md 36.15).

구현 담당과 맞수가 기준 커밋에서 갈라진 초안 worktree 에서 동시에 1라운드(구현 → 커밋 → 테스트 → 상대 리뷰)를
돈다. 초안마다 기록은 `<실행 폴더>/drafts/<역할>/` 의 자기 RunState·대화 기록이고, 라운드 자체는 BuildPhase 를
그대로 쓴다(리뷰 기계·지적 원장 그대로). 규칙으로 승자를 고르고(모델 호출 없음), 승자 브랜치를 코드 폴더로
fast-forward 한 뒤 승자 초안의 1라운드를 이 실행의 1라운드로 옮긴다. 이후는 BuildPhase 가 승자=구현, 패자=리뷰로 잇는다.
"""

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from tenure import worktree
from tenure.phases.common import PhaseContext, PhaseStop
from tenure.state import DONE_APPROVED, DONE_UNAPPROVED, RUN_JSON, RunState
from tenure.transcript import Transcript
from tenure.workspace import GitError, Workspace

if TYPE_CHECKING:
    from tenure.phases.build import BuildPhase

DRAFTS_DIR = "drafts"
TESTS_RANK = {"passed": 2, None: 1}          # 그 밖(실패·시간 초과·오류)은 0
# 1라운드 키: 승자 초안에서 이미 한 일이라 이 실행에서 다시 하지 않는다
ROUND1_KEYS = ("impl:1:called", "impl:1", "test:1", "guard:1", "revert:1", "review:1", "repro:1")


class RaceError(Exception):
    pass


def draft_branch(run_id: str, role: str) -> str:
    return f"{worktree.BRANCH_PREFIX}{run_id}-{role}"


def draft_path(code: Path, run_id: str, role: str) -> Path:
    return Path(code) / ".tenure" / DRAFTS_DIR / f"{run_id}-{role}"


def _prefix(role: str, name: str | None) -> str | None:
    return f"{DRAFTS_DIR}/{role}/{name}" if name else name


class Race:
    def __init__(self, bp: "BuildPhase", rival: str):
        self.bp, self.ctx, self.state = bp, bp.ctx, bp.state
        self.lead, self.rival = bp.implementer, rival
        self.drafters = [self.lead, rival]
        self.code = Workspace(self.ctx.workdir)

    # ---------------------------------------------------------------- run
    def run(self) -> tuple[str, str]:
        """초안 둘 → 판정 → 승자를 코드 폴더로. (승자, 패자)"""
        ctx, st = self.ctx, self.state
        base = st.base_commit
        assert base
        race = st.race = st.race or {"drafters": self.drafters, "base": base, "drafts": {}}
        ctx.save()
        paths = {r: self._ensure_draft(r, base) for r in self.drafters}
        ctx.log(f"경쟁 초안: {self.lead} 대 {self.rival} (각자 worktree 에서 동시에 구현 → 서로 리뷰)")
        children = {r: self._child(r, self._other(r), paths[r]) for r in self.drafters}
        errors: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=len(children), thread_name_prefix="draft") as pool:
            futures = {r: pool.submit(child.run) for r, (child, _) in children.items()}
            for r, f in futures.items():
                try:
                    f.result()
                except BaseException as e:      # noqa: BLE001 — 둘 다 끝날 때까지 기다린 뒤 첫 오류를 올린다
                    errors.append(e)
        for r, (_, cst) in children.items():     # 초안 라운드의 비용을 이 실행의 사용량에 합친다
            self._absorb_calls(r, cst)
        if errors:
            ctx.save()
            err = errors[0]
            if isinstance(err, PhaseStop):
                raise err
            raise RaceError(f"초안 라운드 실패: {err}") from err
        for r in self.drafters:                  # 재현 테스트 등 리뷰 뒤 남은 파일도 초안 브랜치에 남긴다
            ws = Workspace(paths[r])
            if ws.dirty():
                ws.commit_all("tenure: 초안 리뷰 뒤 남은 변경")
        scores = {r: self._summary(r, children[r][1]) for r in self.drafters}
        race["drafts"] = scores
        winner, reason = judge(scores, self.drafters)
        loser = self._other(winner)
        race.update(winner=winner, loser=loser, reason=reason)
        ctx.log(f"판정: {winner} 초안 채택 — {reason}")
        self.code.git("merge", "--ff-only", draft_branch(st.run_id, winner))
        self._adopt(winner, loser, children[winner][1])
        for r in self.drafters:
            self._remove_draft(r)
        st.mark_done("race")
        ctx.save()
        return winner, loser

    def _other(self, role: str) -> str:
        return self.rival if role == self.lead else self.lead

    # ---------------------------------------------------------------- drafts
    def _ensure_draft(self, role: str, base: str) -> Path:
        st = self.state
        path = draft_path(self.ctx.workdir, st.run_id, role)
        branch = draft_branch(st.run_id, role)
        if not path.is_dir():
            exists = self.code.git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).strip()
            try:
                if exists:
                    self.code.git("worktree", "add", str(path), branch)
                else:
                    self.code.git("worktree", "add", "-b", branch, str(path), base)
            except GitError as e:
                raise RaceError(f"초안 worktree 를 만들지 못했습니다: {e}") from e
            worktree.copy_includes(self.ctx.workdir, path)
        doc = self.ctx.design_doc                  # 과제 원문(TASK.md)은 기록 폴더(.tenure)에 있어 초안으로 복사한다
        src, dst = Path(self.ctx.workdir) / doc, path / doc
        if src.is_file() and not dst.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return path

    def _remove_draft(self, role: str) -> None:
        path = draft_path(self.ctx.workdir, self.state.run_id, role)
        if path.is_dir():
            self.code.git("worktree", "remove", "--force", str(path), check=False)
        self.code.git("worktree", "prune", check=False)

    def _child(self, role: str, other: str, path: Path) -> tuple["BuildPhase", RunState]:
        from tenure.phases.build import BuildPhase
        from tenure.workflow import Step

        ctx, st = self.ctx, self.state
        d = ctx.run_dir / DRAFTS_DIR / role
        d.mkdir(parents=True, exist_ok=True)
        if (d / RUN_JSON).is_file():
            cst = RunState.load(d)                 # 이어하기: 초안의 완료 키로 이어 간다
        else:
            cst = RunState(run_id=f"{st.run_id}-{role}", task=st.task, config=dict(st.config), workflow=st.workflow)
            cst.design_doc = st.design_doc
            cst.attachments = [f"../../{a}" for a in st.attachments]
            cst.base_commit = st.base_commit
            cst.mark_done("build:base")
            cst.save(d)
        # 초안 라운드는 1라운드만, 중재·브라우저 확인 없이 (병렬로 앱 서버를 둘 띄우지 않게)
        ccfg = replace(ctx.cfg, max_review=1, arbiter=False, browser_check="off")
        cctx = PhaseContext(task=ctx.task, workdir=path, cfg=ccfg, agents=ctx.agents, state=cst,
                            transcript=Transcript(d), run_dir=d, log=lambda m, r=role: ctx.log(f"[초안 {r}] {m}"),
                            workflow=ctx.workflow)
        step = Step(kind="build", id=f"draft-{role}", implementer=role, reviewers=[other], max_review=1)
        return BuildPhase(cctx, step=step), cst

    def _summary(self, role: str, cst: RunState) -> dict:
        branch = draft_branch(self.state.run_id, role)
        lines, files = 0, 0
        for ln in self.code.git("diff", "--numstat", self.state.base_commit, branch).splitlines():
            parts = ln.split("\t")
            if len(parts) >= 3:
                files += 1
                lines += sum(int(x) for x in parts[:2] if x.isdigit())
        h = cst.review_history[-1] if cst.review_history else {}
        t = cst.tests.get("1") or {}
        return {"branch": branch, "head": self.code.git("rev-parse", branch).strip(),
                "status": cst.status, "approved": bool(h.get("approved")), "blocking": h.get("blocking"),
                "tests": t.get("status"), "tests_summary": t.get("summary"), "lines": lines, "files": files,
                "review_file": _prefix(role, h.get("file")), "reviewer": self._other(role),
                "calls": len(cst.calls), "sec": round(sum(c.sec for c in cst.calls), 1)}

    def _absorb_calls(self, role: str, cst: RunState) -> None:
        st = self.state
        seen = {c.file for c in st.calls if c.file}
        for c in cst.calls:
            f = _prefix(role, c.file)
            if f and f in seen:
                continue
            st.calls.append(replace(c, file=f))

    # ---------------------------------------------------------------- adopt
    def _adopt(self, winner: str, loser: str, cst: RunState) -> None:
        """승자 초안의 1라운드를 이 실행의 1라운드로 옮긴다."""
        st = self.state
        p = lambda name: _prefix(winner, name)     # noqa: E731
        if cst.tests.get("1"):
            st.tests["1"] = {**cst.tests["1"], "file": p(cst.tests["1"].get("file"))}
        for k in ("test_guard", "reverts"):
            src = getattr(cst, k).get("1")
            if src:
                getattr(st, k)["1"] = {**src, **({"file": p(src["file"])} if src.get("file") else {})}
        for h in cst.review_history:
            st.review_history.append({**h, "file": p(h.get("file")), "draft": winner})
        st.issues = [dict(x) for x in cst.issues]
        st.repros = dict(cst.repros)
        st.reviewed_commits.update(cst.reviewed_commits)
        st.last_impl = p(cst.last_impl)
        st.last_review = p(cst.last_review)
        st.last_reviews = {loser: p(f) for f in [cst.last_reviews.get(loser) or cst.last_review] if f}
        st.last_verdict = cst.last_verdict
        st.round = 1
        for k in ROUND1_KEYS:
            st.mark_done(k)


def judge(scores: dict[str, dict], order: list[str]) -> tuple[str, str]:
    """테스트 → 리뷰 승인 → 막는 지적 적음 → 바뀐 줄 적음 → 앞 순서(구현 담당). (승자, 이유)"""
    def key(r: str):
        s = scores[r]
        blocking = s["blocking"] if s["blocking"] is not None else 99
        return (-TESTS_RANK.get(s["tests"], 0), not s["approved"], blocking, s["lines"], order.index(r))

    ranked = sorted(order, key=key)
    w, lo = ranked[0], ranked[1]
    a, b = scores[w], scores[lo]
    tests_ko = {"passed": "통과", None: "명령 없음"}
    if TESTS_RANK.get(a["tests"], 0) != TESTS_RANK.get(b["tests"], 0):
        why = f"테스트 {tests_ko.get(a['tests'], '실패')} 대 {tests_ko.get(b['tests'], '실패')}"
    elif a["approved"] != b["approved"]:
        why = "상대 리뷰에서 승인받음"
    elif (a["blocking"] or 0) != (b["blocking"] or 0):
        why = f"막는 지적 {a['blocking'] or 0}개 대 {b['blocking'] or 0}개"
    elif a["lines"] != b["lines"]:
        why = f"바뀐 줄 {a['lines']} 대 {b['lines']} (더 작은 변경)"
    else:
        why = "모든 기준이 같아 구현 담당 초안"
    return w, why


def pick(code: Path, run_dir: Path, role: str) -> dict:
    """사람이 다른 초안을 고른다: 코드 폴더를 그 초안 브랜치로 바꾸고, 바꾸기 전 HEAD 는 브랜치로 남긴다."""
    st = RunState.load(run_dir)
    race = st.race or {}
    if role not in (race.get("drafts") or {}):
        raise RaceError(f"이 실행에 {role} 초안이 없습니다.")
    if st.status not in (DONE_APPROVED, DONE_UNAPPROVED):
        raise RaceError("끝난 실행에서만 초안을 바꿀 수 있습니다.")
    ws = Workspace(code)
    if [f for f in ws.dirty_files() if not f.startswith(".tenure")]:
        raise RaceError("코드 폴더에 커밋 안 한 변경이 있습니다. 먼저 커밋하거나 치우세요.")
    draft = race["drafts"][role]
    n = len(race.get("picks") or []) + 1
    keep = f"{worktree.BRANCH_PREFIX}{st.run_id}-prev-{n}"
    prev = ws.head(short=False)
    ws.git("branch", "-f", keep, prev)
    ws.git("reset", "-q", "--hard", draft["branch"])
    race.setdefault("picks", []).append({"role": role, "prev": prev, "kept": keep})
    race["picked"] = role
    st.race = race
    st.status = DONE_APPROVED if draft.get("approved") else DONE_UNAPPROVED
    st.stop_reason = "picked"
    st.last_verdict = "APPROVED" if draft.get("approved") else "CHANGES_REQUESTED"
    st.save(run_dir)
    return {"role": role, "branch": draft["branch"], "kept": keep, "status": st.status}
