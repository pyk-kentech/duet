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
  review:i:<역할>   리뷰어가 여럿일 때 그 리뷰어의 리뷰 완료 (판정은 state.round_reviews[i][역할])

리뷰어가 여럿이면(DESIGN.md 19.3) 모두 승인해야 승인, 막는 지적 수는 합.

멈춤: 승인 → done_approved / 상한 도달 → done_unapproved(stop_reason=max_review)
      막는 지적 수가 stall_rounds 라운드 연속 최저치를 못 갱신 → done_unapproved(stop_reason=stalled)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from duet.agents.base import Mode
from duet.phases.common import PhaseContext
from duet.phases.debate import DESIGN_FILENAME
from duet import gates
from duet.packet import READ_INSTRUCTION_PACKET, READ_INSTRUCTION_PLAIN, call_sites, changed_symbols
from duet.policy import Decision, decide, stalled
from duet.prompts import TemplateError, load_template
from duet.review_json import REVIEW_SCHEMA, output_instruction, render_review
from duet.repro import parse_repros, write_repros
from duet.runner import env_drops
from duet.testing import STATUS_KO, describe_for_prompt, resolve_command, run_tests
from duet.state import DONE_APPROVED, DONE_UNAPPROVED, PHASE_BUILD, PHASE_DONE
from duet.verdict import parse_verdict
from duet.workspace import GitError, Workspace

if TYPE_CHECKING:
    from duet.verdict import Verdict
    from duet.workflow import Step

DIFF_EXCLUDES = (DESIGN_FILENAME,)
TRUNCATED_NOTE = "\n... (diff가 길어 잘림. 위의 변경 파일 요약을 보고 나머지는 파일을 직접 열어 확인)"


def truncate_diff(diff: str, max_chars: int) -> str:
    if not diff.strip():
        return "(변경 없음)"
    if len(diff) <= max_chars:
        return diff
    return diff[:max_chars] + TRUNCATED_NOTE


def diff_body(ws: Workspace, frm: str, exclude, excludes_glob, budget: int, context: bool) -> str:
    """본문 diff. context 면 함수 단위 문맥(리뷰 패킷, DESIGN.md 21.1)을 쓰되 budget 을 넘으면 예전 diff."""
    if context:
        body = ws.diff(frm, "HEAD", exclude=exclude, exclude_globs=excludes_glob, context=True)
        if body.strip() and len(body) <= budget:
            return body
    return ws.diff(frm, "HEAD", exclude=exclude, exclude_globs=excludes_glob)


def build_review_diff(ws: Workspace, base: str, excludes_glob: list[str], max_chars: int,
                      exclude: tuple[str, ...] = DIFF_EXCLUDES, context: bool = False) -> str:
    """리뷰어에게 줄 diff. 맨 앞의 파일 요약(stat)은 잘리지 않게 두고, 본문 diff 만 자른다.

    exclude: 빼는 파일(설계 문서). 변경 설계면 DESIGN.md 대신 docs/changes/<run>.md (DESIGN.md 19.5).
    """
    stat = ws.diff_stat(base, "HEAD", exclude=exclude)
    budget0 = max(1000, max_chars - len(stat) - 200)
    body = diff_body(ws, base, exclude, excludes_glob, budget0, context)
    if not stat.strip() and not body.strip():
        return "(변경 없음)"
    header = "[변경 파일 요약]\n" + stat.rstrip() + "\n"
    if excludes_glob:
        header += f"(잠금 파일 등은 아래 diff 에서 뺐음: {', '.join(excludes_glob)})\n"
    budget = max(1000, max_chars - len(header))
    return header + "\n" + truncate_diff(body, budget)


class BuildPhase:
    def __init__(self, ctx: PhaseContext, workspace: Workspace | None = None, step: "Step | None" = None):
        self.ctx = ctx
        self.state = ctx.state
        self.cfg = ctx.cfg
        self.ws = workspace or Workspace(ctx.workdir)
        self.implementer = step.implementer if step is not None and step.implementer else ctx.cfg.implementer
        self.reviewers: list[str] = list(step.reviewers) if step is not None else [ctx.cfg.reviewer]
        self.reviewer = self.reviewers[0]
        self.multi = len(self.reviewers) > 1
        self.max_review = ctx.cfg.max_review
        self._single: "Verdict | None" = None
        self._downgraded: dict[str, dict] = {}     # 역할 → 이번 라운드 관문별 강등 수

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
                        prompt = ctx.prompt(self.implementer, "implement", task=ctx.task,
                                            test_hint=self._test_hint())
                    else:
                        step = "fix"
                        ctx.log(f"[{i}/{self.max_review}] 리뷰 반영: {self.implementer}")
                        prompt = ctx.prompt(self.implementer, "fix", task=ctx.task, review=self._review_texts(),
                                            reviewer_name=", ".join(self.reviewers),
                                            tests=self._tests_text(i - 1), repro=self._repro_text(i - 1))
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
            # 테스트는 그 라운드 리뷰 전에만 의미가 있다. 리뷰가 끝난 라운드(예: 테스트 단계가 없던
            # 예전 실행을 이어갈 때)는 지금 코드로 돌려 봐야 그 라운드 기록이 틀려진다.
            if not st.is_done(test_key) and not st.is_done(review_key):
                ctx.set_position(PHASE_BUILD, "test", i)
                ctx.save()
                self._run_tests(i)
                st.mark_done(test_key)
                ctx.save()

            if not st.is_done(review_key):
                ctx.set_position(PHASE_BUILD, "review", i)
                ctx.save()
                self._preserve_pending_changes(i)
                diff_title, diff = self._review_diff(i, base)
                decision, files = self._review_round(i, diff_title, diff)
                test = st.tests.get(str(i))
                st.last_verdict = "APPROVED" if decision.approved else "CHANGES_REQUESTED"
                st.review_history.append(self._history_entry(i, decision, files, test))
                st.mark_done(review_key)
                ctx.log(f"[{i}/{self.max_review}] 판정: {decision.describe()}")
                if decision.approved:
                    st.status = DONE_APPROVED
                    st.stop_reason = None
                    ctx.set_position(PHASE_DONE, "approved", i)
                    ctx.save()
                    return True
                ctx.save()
                if self.cfg.repro_tests and not st.is_done(f"repro:{i}"):
                    self._handle_repros(i, "\n\n".join(ctx.transcript.read(f) for f in files))
                    st.mark_done(f"repro:{i}")
                    ctx.save()
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

    # ---------------------------------------------------------------- review
    def _review_round(self, i: int, diff_title: str, diff: str) -> tuple[Decision, list[str]]:
        """이 라운드의 리뷰어들을 차례로 부르고 판정을 합친다. (합친 판정, 리뷰 파일들)"""
        ctx, st = self.ctx, self.state
        test = st.tests.get(str(i))
        tests_block = bool(test and test.get("status") in ("failed", "timeout"))
        parts = st.round_reviews.setdefault(str(i), {}) if self.multi else {}
        decisions: list[tuple[str, Decision]] = []
        files: list[str] = []
        sites_full: str | None = None
        self._downgraded = {}
        for role in self.reviewers:
            sub_key = f"review:{i}:{role}"
            if self.multi and st.is_done(sub_key) and role in parts:
                p = parts[role]
                decisions.append((role, Decision(p["approved"], p["blocking"], list(p["reasons"]))))
                files.append(p["file"])
                continue
            json_mode = self.cfg.review_json and self._template_has(role, "review", "{output_instruction}")
            use_gates = json_mode and self.cfg.review_gates
            repro_text = REPRO_INSTRUCTION if self.cfg.repro_tests else ""
            open_now = gates.open_issues(st, role) if use_gates else []
            if sites_full is None:
                sites_full = self._call_sites(diff)
            common = dict(task=ctx.task, implementer_name=self.implementer, tests=self._tests_text(i),
                          test_instruction=self._test_instruction(i, role),
                          read_instruction=READ_INSTRUCTION_PACKET if self.cfg.review_packet else READ_INSTRUCTION_PLAIN,
                          repro_instruction=repro_text, open_issues=gates.format_open(open_now),
                          output_instruction=output_instruction(json_mode, self.cfg.repro_tests, repro_text,
                                                                gates=use_gates))
            full_prompt = ctx.prompt(role, "review", diff=diff, diff_title=diff_title, call_sites=sites_full,
                                     previous_review=self._previous_must_fix(role), **common)
            resume_id = self._resumable_session(role, i, json_mode)
            if resume_id:
                # 이어간 리뷰도 diff 는 review_diff 설정을 따른다 (기본 incremental: 지난 리뷰 이후만)
                prompt = ctx.prompt(role, "rereview", diff=diff, diff_title=diff_title, call_sites=sites_full,
                                    previous_review=self._previous_must_fix(role), **common)
                ctx.log(f"[{i}/{self.max_review}] 리뷰: {role} (지난 세션 이어서, diff {len(diff):,}자)")
            else:
                prompt = full_prompt
                ctx.log(f"[{i}/{self.max_review}] 리뷰: {role} (diff {len(diff):,}자"
                        f"{', 지난 리뷰 이후만' if '이후' in diff_title else ''})")
            gated: dict = {}
            if use_gates:
                changed = self._changed_since_review(i)
                ids = {x["id"] for x in open_now}
                first = gates.next_number(st)

                def transform(r, changed=changed, ids=ids, first=first):
                    if r.structured is None:
                        return r.text
                    res = gates.apply_gates(r.structured, round_=i, open_ids=ids, changed_files=changed,
                                            first_number=first)
                    rendered = render_review(res.data)
                    if rendered is None:
                        return r.text
                    gated["res"] = res
                    return rendered
            else:
                transform = _render_structured if json_mode else None
            st.reviewed_commits[str(i)] = self.ws.head()
            out = ctx.call(role, "review", prompt, Mode.READ, label=f"review{i}_{role}", round_=i,
                           output_schema=REVIEW_SCHEMA if json_mode else None,
                           resume_session=resume_id, fallback_prompt=full_prompt if resume_id else None,
                           transform=transform)
            self._remember_session(role, i, out.result)
            if "res" in gated:
                gates.update_ledger(st, role, i, gated["res"].data["findings"])
                self._downgraded[role] = gated["res"].downgraded
            self._undo_reviewer_changes()
            verdict = parse_verdict(out.text)
            decision = decide(verdict, block_severity=self.cfg.block_severity, tests_block=tests_block,
                              require_tests_pass=self.cfg.require_tests_pass)
            st.last_review = out.file
            st.last_reviews[role] = out.file
            decisions.append((role, decision))
            files.append(out.file)
            if self.multi:
                parts[role] = {"file": out.file, "reviewer_status": verdict.status.value,
                               "downgraded": self._downgraded.get(role),
                               "approved": decision.approved, "blocking": decision.blocking,
                               "must_fix": verdict.must_fix, "severity": verdict.severity,
                               "parse_failed": verdict.parse_failed, "reasons": decision.reasons}
                st.mark_done(sub_key)
                ctx.log(f"[{i}/{self.max_review}] 판정({role}): {decision.describe()}")
                ctx.save()
            else:
                self._single = verdict
        if not self.multi:
            return decisions[0][1], files
        counts = [d.blocking for _, d in decisions if d.blocking is not None]
        reasons = []
        for role, d in decisions:
            reasons.append(f"{role}: {'승인' if d.approved else '반려'}"
                           + (f" (막는 지적 {d.blocking})" if d.blocking else ""))
        merged = Decision(all(d.approved for _, d in decisions), sum(counts) if counts else None, reasons)
        return merged, files

    # ---------------------------------------------------------------- review cost (DESIGN.md 21장)
    def _template_has(self, role: str, step: str, marker: str) -> bool:
        wf = self.ctx.workflow
        r = wf.roles.get(role) if wf is not None else None
        name = r.templates.get(step, step) if r is not None else step
        try:
            return marker in load_template(name, self.ctx.workdir)
        except TemplateError:
            return False

    def _changed_since_review(self, i: int) -> set[str] | None:
        """지난 리뷰 시점 이후 바뀐 파일 (범위 관문, DESIGN.md 22.2). 1라운드거나 기준을 모르면 None."""
        if i < 2:
            return None
        prev = self._reviewed_commit(i - 1)
        if not prev:
            return None
        try:
            out = self.ws.git("diff", "--name-only", prev, "HEAD")
        except GitError:
            return None
        return {ln.strip() for ln in out.splitlines() if ln.strip()}

    def _call_sites(self, diff: str) -> str:
        if not self.cfg.review_packet:
            return "(리뷰 패킷을 끈 실행)"
        sites = call_sites(self.ws, changed_symbols(diff), exclude=(self.ctx.design_doc,),
                           exclude_globs=self.cfg.diff_excludes)
        return sites or "(찾지 못함)"

    def _resumable_session(self, role: str, i: int, json_mode: bool) -> str | None:
        """2라운드부터, 직전 라운드에 쓴 자기 세션이 있고 상한 전이면 그 세션 id."""
        if self.cfg.review_session != "reuse" or i < 2:
            return None
        if not self._template_has(role, "rereview", "{diff}"):
            return None
        s = self.state.review_sessions.get(role) or {}
        if not s.get("id") or s.get("round") != i - 1 or int(s.get("rounds") or 0) >= self.cfg.review_session_rounds:
            return None
        return str(s["id"])

    def _remember_session(self, role: str, i: int, result) -> None:
        prev = self.state.review_sessions.get(role) or {}
        if not result.session_id:
            self.state.review_sessions.pop(role, None)
            return
        rounds = int(prev.get("rounds") or 0) + 1 if result.resumed and prev.get("id") == result.session_id else 1
        self.state.review_sessions[role] = {"id": result.session_id, "round": i, "rounds": rounds}

    def _history_entry(self, i: int, decision: Decision, files: list[str], test: dict | None) -> dict:
        if not self.multi:
            v = self._single
            assert v is not None
            entry = {"round": i, "file": files[0], "reviewer_status": v.status.value,
                     "approved": decision.approved, "blocking": decision.blocking,
                     "must_fix": v.must_fix, "severity": v.severity,
                     "parse_failed": v.parse_failed, "reasons": decision.reasons,
                     "tests": test.get("status") if test else None}
            if self._downgraded.get(self.reviewer):
                entry["downgraded"] = self._downgraded[self.reviewer]
            if self.state.issues:
                entry["open_issues"] = sum(1 for x in self.state.issues if x["status"] == "open")
            return entry
        parts = self.state.round_reviews.get(str(i), {})
        rows = [{"role": r, **parts[r]} for r in self.reviewers if r in parts]
        severity: dict[str, int] | None = None
        if any(row.get("severity") for row in rows):
            severity = {}
            for row in rows:
                for k, n in (row.get("severity") or {}).items():
                    severity[k] = severity.get(k, 0) + n
        must = [row["must_fix"] for row in rows if row.get("must_fix") is not None]
        all_ok = all(row["reviewer_status"] == "APPROVED" for row in rows)
        return {"round": i, "file": files[0], "files": files,
                "reviewer_status": "APPROVED" if all_ok else "CHANGES_REQUESTED",
                "approved": decision.approved, "blocking": decision.blocking,
                "must_fix": sum(must) if must else None, "severity": severity,
                "parse_failed": any(row.get("parse_failed") for row in rows), "reasons": decision.reasons,
                "tests": test.get("status") if test else None, "reviewers": rows}

    def _review_texts(self) -> str:
        """수정 프롬프트에 넣을 지난 리뷰. 리뷰어가 여럿이면 역할별로 이어 붙인다."""
        st = self.state
        if not self.multi or not st.last_reviews:
            return self.ctx.transcript.read(st.last_review)  # type: ignore[arg-type]
        chunks = []
        for role in self.reviewers:
            f = st.last_reviews.get(role)
            if f:
                chunks.append(f"### {role} 의 리뷰\n\n{self.ctx.transcript.read(f).strip()}")
        return "\n\n".join(chunks)

    # ---------------------------------------------------------------- tests
    def _env_drops(self) -> list[str]:
        return env_drops(self.cfg.env_strip, self.cfg.env_keep)

    def _run_tests(self, i: int) -> None:
        ctx, st = self.ctx, self.state
        resolved = resolve_command(ctx.workdir, self.cfg.test_command)
        if resolved is None:
            ctx.log(f"[{i}/{self.max_review}] 테스트: 명령 없음 (건너뜀)")
            return
        command, source = resolved
        ctx.log(f"[{i}/{self.max_review}] 테스트: {command} ({source})")
        result = run_tests(ctx.workdir, command, source, self.cfg.test_timeout_sec, drop_env=self._env_drops())
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

    def _test_instruction(self, i: int, role: str | None = None) -> str:
        ran = bool(self.state.tests.get(str(i)))
        if role is not None and not self.ctx.can_run_commands(role):
            # Claude 읽기 모드는 명령을 못 돌린다 (DESIGN.md 19.6)
            head = "위 테스트는 duet 가 방금 직접 실행했다. " if ran else "duet 가 테스트를 돌리지 않았다. "
            tail = ("재현 테스트로 내라." if self.cfg.repro_tests else "P3 로 적어라.")
            return (head + "너는 이 호출에서 명령을 실행할 수 없다(읽기 전용). 코드와 위 테스트 결과로 판단하고, "
                    "실행해 봐야 알 수 있는 의심은 추측으로 반려하지 말고 " + tail)
        if ran:
            return ("위 테스트는 duet 가 방금 직접 실행했다. 전체 테스트를 다시 돌리지 마라. "
                    "특정 동작을 확인해야 할 때만 그 부분만 좁게 실행해라.")
        return "duet 가 테스트를 돌리지 않았다. 필요하면 직접 실행해도 된다."

    # ---------------------------------------------------------------- diff
    def _reviewed_commit(self, i: int) -> str | None:
        """i 라운드 리뷰 시점의 HEAD. 기록이 없으면(예전 실행) 그 라운드 구현 커밋을 메시지로 찾는다."""
        c = self.state.reviewed_commits.get(str(i))
        if c:
            return c
        try:
            out = self.ws.git("log", "-1", "--format=%h", f"--grep=^duet: impl round {i}$", "HEAD")
        except GitError:
            return None
        return out.strip() or None

    def _review_diff(self, i: int, base: str) -> tuple[str, str]:
        full_title = "구현 전체 diff"
        exclude = (self.ctx.design_doc,)
        if self.cfg.review_diff != "incremental" or i <= 1:
            return full_title, build_review_diff(self.ws, base, self.cfg.diff_excludes, self.cfg.max_diff_chars,
                                                 exclude, context=self.cfg.review_packet)
        return self._incremental_diff(i, base)

    def _incremental_diff(self, i: int, base: str) -> tuple[str, str]:
        """지난 리뷰 이후 바뀐 부분. 기준을 못 찾으면 전체 diff."""
        exclude = (self.ctx.design_doc,)
        prev = self._reviewed_commit(i - 1) if i > 1 else None
        if not prev:
            return "구현 전체 diff", build_review_diff(self.ws, base, self.cfg.diff_excludes, self.cfg.max_diff_chars,
                                                     exclude, context=self.cfg.review_packet)
        stat = self.ws.diff_stat(base, "HEAD", exclude=exclude)
        body = diff_body(self.ws, prev, exclude, self.cfg.diff_excludes, self.cfg.max_diff_chars,
                         self.cfg.review_packet)
        note = (f"아래 diff 는 지난 리뷰(커밋 {prev}) 이후 바뀐 부분만이다. 처음부터의 전체 변경은 "
                f"`git diff {base} HEAD` 로 볼 수 있다. 바뀐 부분과 그 영향을 받는 코드 위주로 리뷰해라.\n\n"
                f"[처음부터의 변경 파일 요약]\n{stat.rstrip() or '(없음)'}\n")
        budget = max(1000, self.cfg.max_diff_chars - len(note))
        text = note + "\n" + (truncate_diff(body, budget) if body.strip() else "(지난 리뷰 이후 바뀐 코드 없음)")
        return f"지난 리뷰 이후 바뀐 부분 (diff)", text

    # ---------------------------------------------------------------- repro
    def _handle_repros(self, i: int, review_text: str) -> None:
        ctx, st = self.ctx, self.state
        parsed = parse_repros(review_text, ctx.workdir)
        if not parsed.files and not parsed.rejected:
            return
        record: dict = {"files": [f.path for f in parsed.files], "rejected": parsed.rejected}
        lines = [f"# 리뷰어가 낸 재현 테스트 ({i}회차 리뷰)", ""]
        if parsed.files:
            write_repros(parsed.files, ctx.workdir)
            commit = self.ws.commit_all(f"duet: repro tests from review {i}")
            record["commit"] = commit
            lines += ["저장한 파일:", *[f"- `{f}`" for f in record["files"]], ""]
            resolved = resolve_command(ctx.workdir, self.cfg.test_command)
            if resolved is None:
                record["status"] = "not_run"
                lines.append("테스트 명령이 없어 실행하지 못했다.")
            else:
                result = run_tests(ctx.workdir, resolved[0], resolved[1], self.cfg.test_timeout_sec,
                                   drop_env=self._env_drops())
                if self.ws.dirty():
                    self.ws.restore_clean()
                record.update(status=result.status, summary=result.summary, command=result.command)
                verdict = {"failed": "재현됨: 지금 코드에서 실패한다. 리뷰어의 지적이 맞다.",
                           "passed": "재현 안 됨: 지금 코드에서도 통과한다. 지적이 틀렸거나 테스트가 문제를 못 짚었다.",
                           "timeout": "시간 초과", "error": "실행 불가(환경 문제일 수 있음)"}[result.status]
                lines += [f"결과: {verdict}", "", describe_for_prompt(result)]
            ctx.log(f"[{i}/{self.max_review}] 재현 테스트 {len(record['files'])}개 저장"
                    + (f" → {STATUS_KO.get(record.get('status'), '실행 안 함')}" if record.get("status") else ""))
        if parsed.rejected:
            lines += ["", "받지 않은 블록:", *[f"- {r}" for r in parsed.rejected]]
            ctx.log(f"[{i}/{self.max_review}] 재현 테스트 거절 {len(parsed.rejected)}개: {parsed.rejected[0]}")
        path = ctx.transcript.save(f"repro{i}", "\n".join(lines), {
            "agent": "duet", "adapter": "duet", "step": "repro", "mode": "run", "round": i,
            "exit_code": 0, "ok": True, "repro_status": record.get("status", "none"),
            "repro_files": len(record["files"]), "rate_limited": False, "timed_out": False})
        record["file"] = path.name
        st.repros[str(i)] = record

    def _repro_text(self, i: int) -> str:
        r = self.state.repros.get(str(i))
        if not r or not r.get("files"):
            return "(없음)"
        status = {"failed": "지금 코드에서 실패함 — 재현됨", "passed": "지금 코드에서도 통과함 — 재현 안 됨",
                  "timeout": "시간 초과", "error": "실행 불가", "not_run": "실행 안 함"}.get(r.get("status"), "?")
        files = "\n".join(f"- {f}" for f in r["files"])
        return (f"리뷰어가 아래 테스트를 냈고 duet 가 작업 폴더에 저장했다 ({status}).\n{files}\n"
                "이 테스트가 통과하도록 코드를 고쳐라. 테스트 자체가 틀렸다고 판단되면 테스트를 고치거나 지우되, "
                "이유를 IMPLEMENTATION_NOTES.md 에 적어라.")

    def _previous_must_fix(self, role: str | None = None) -> str:
        prev = self.state.last_reviews.get(role) if self.multi and role else self.state.last_review
        if not prev:
            return "(첫 리뷰)"
        try:
            text = self.ctx.transcript.read(prev)
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


def _render_structured(result) -> str:
    """JSON 판정을 기존 마크다운 리뷰로. 못 읽으면 본문 그대로 (DESIGN.md 21.2)."""
    rendered = render_review(result.structured) if result.structured is not None else None
    return rendered or result.text


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


REPRO_INSTRUCTION = """'반드시 고칠 것' 중 코드로 재현할 수 있는 것은, 지금 코드에서 실패하는 테스트를 아래 형식으로 함께 내라.
duet 가 새 파일로 저장해 실제로 실패하는지 돌려 보고, 구현자는 이 테스트를 통과시켜야 한다.

<repro path="tests/test_repro_짧은이름.py">
(프로젝트의 테스트 방식대로 작성한, 지금은 실패하는 테스트 코드)
</repro>

- 프로젝트의 테스트 폴더와 프레임워크를 따라라. 이미 있는 파일 경로는 쓰지 마라(새 파일만).
- 한 번에 최대 5개. 코드로 재현하기 어려운 지적은 글로만 써도 된다."""
