"""DebatePhase — 설계 토론.

propose(A), propose(B)
for r in 1..debate_rounds: critique(A←B), critique(B←A)   # 각자 개정안 반환
synthesize(synth) → <workdir>/DESIGN.md

A, B, synth 는 워크플로 단계의 역할(classic 은 claude, codex, 설정의 synth).
제안자가 1명이면 비판·종합 없이 그 제안이 DESIGN.md 가 된다 (DESIGN.md 19.2).

resume: state.done 에 있는 스텝은 건너뛰고, 필요한 텍스트는 transcript 파일에서 다시 읽는다.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

from tenure.agents.base import Mode
from tenure.phases.common import PhaseContext
from tenure.state import PHASE_DEBATE
from tenure.transcript import Entry

if TYPE_CHECKING:
    from tenure.workflow import Step

DESIGN_FILENAME = "DESIGN.md"
BACKUP_FILENAME = "DESIGN.prev.md"
REVISION_HEADER_RE = re.compile(r"^##\s*개정안\s*$", re.MULTILINE)
CRITIQUE_HEADER_RE = re.compile(r"^##\s*상대 안 비판\s*$", re.MULTILINE)

PARTICIPANTS = ("claude", "codex")


def split_revision(text: str) -> str:
    """'## 개정안' 헤더 뒤를 개정안으로. 없으면 응답 전체."""
    m = REVISION_HEADER_RE.search(text)
    return text[m.end():].strip() if m else text.strip()


def split_critique(text: str) -> str:
    """'## 개정안' 앞부분(비판)을 돌려준다. 헤더가 없으면 전체. 맨 앞의 '## 상대 안 비판' 헤더는 뗀다."""
    m = REVISION_HEADER_RE.search(text)
    part = (text[: m.start()] if m else text).strip()
    h = CRITIQUE_HEADER_RE.match(part)
    return part[h.end():].strip() if h else part


class DebatePhase:
    def __init__(self, ctx: PhaseContext, step: "Step | None" = None):
        self.ctx = ctx
        self.state = ctx.state
        self.cfg = ctx.cfg
        self.proposers: list[str] = list(step.proposers) if step is not None else list(PARTICIPANTS)
        solo = len(self.proposers) == 1
        self.rounds = 0 if solo else ctx.cfg.debate_rounds
        self.synth: str | None = None if solo else (step.synth if step is not None else ctx.cfg.synth_name)

    # ---------------------------------------------------------------- run
    def run(self) -> str:
        ctx, st = self.ctx, self.state

        for name in self.proposers:
            key = f"propose:{name}"
            if not st.is_done(key):
                ctx.set_position(PHASE_DEBATE, "propose", 0)
                ctx.save()
                ctx.log(f"설계안 작성: {name}")
                out = ctx.call(name, "propose", ctx.prompt(name, "propose", task=ctx.task),
                               Mode.READ, label=f"propose_{name}")
                st.proposals[name] = out.file
                st.revisions[name] = out.file
                st.mark_done(key)
                ctx.save()

        if self.synth is None:
            # 제안자 1명: 그 제안을 그대로 최종 설계로
            st.final_design = st.proposals[self.proposers[0]]
            return self._write_design()
        a, b = self.proposers

        for r in range(1, self.rounds + 1):
            # 이 라운드의 비판은 둘 다 '이전 라운드까지의 개정안'을 본다
            prev = {name: self._revision_text(name, r - 1) for name in (a, b)}
            for me, other in ((a, b), (b, a)):
                key = f"critique:{r}:{me}"
                if st.is_done(key):
                    continue
                ctx.set_position(PHASE_DEBATE, "critique", r)
                ctx.save()
                ctx.log(f"토론 라운드 {r}/{self.rounds}: {me} → {other} 비판")
                prompt = ctx.prompt(me, "critique", task=ctx.task,
                                    own=prev[me], other=prev[other], other_name=other)
                out = ctx.call(me, "critique", prompt, Mode.READ,
                               label=f"r{r}_critique_{me}", round_=r)
                st.critiques.append(out.file)
                st.revisions[me] = out.file
                st.mark_done(key)
                ctx.save()

        if not st.is_done("synthesize"):
            ctx.set_position(PHASE_DEBATE, "synthesize", self.rounds)
            ctx.save()
            ctx.log(f"최종 설계 종합: {self.synth}")
            prompt = ctx.prompt(
                self.synth, "synthesize", task=ctx.task,
                a=self._revision_text(a, self.rounds), b=self._revision_text(b, self.rounds),
                a_name=a, b_name=b, critiques=self._critique_summary() or "(비판 라운드 없음)",
            )
            out = ctx.call(self.synth, "synthesize", prompt, Mode.READ, label=f"synthesize_{self.synth}")
            st.final_design = out.file
            st.mark_done("synthesize")
            ctx.save()
        return self._write_design()

    def _write_design(self) -> str:
        ctx, st = self.ctx, self.state
        final = ctx.transcript.read(st.final_design)  # type: ignore[arg-type]
        if ctx.change_mode:
            # 기존 프로젝트의 변경 설계: DESIGN.md 는 그대로 두고 따로 저장 (DESIGN.md 19.5)
            path = ctx.workdir / ctx.design_doc
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(final, encoding="utf-8")
            ctx.log(f"변경 설계 저장: {ctx.design_doc} ({DESIGN_FILENAME} 는 그대로)")
            return final
        design_path = ctx.workdir / DESIGN_FILENAME
        if design_path.is_file():
            old = design_path.read_text(encoding="utf-8")
            if old != final:
                backup = ctx.run_dir / BACKUP_FILENAME
                backup.write_text(old, encoding="utf-8")
                ctx.log(f"기존 {DESIGN_FILENAME} 를 덮어씁니다 (백업: {backup})")
        design_path.write_text(final, encoding="utf-8")
        ctx.log(f"{DESIGN_FILENAME} 저장 완료")
        return final

    # ---------------------------------------------------------------- helpers
    def _successful_critiques(self) -> dict[tuple[str, int], Entry]:
        """(agent, round) → 성공한 비판 기록. 재시도·resume 로 여러 개면 마지막 것."""
        found: dict[tuple[str, int], Entry] = {}
        for entry in self.ctx.transcript.entries():
            m = entry.meta
            if m.get("step") != "critique" or not is_success(entry):
                continue
            try:
                found[(m.get("role") or m.get("agent", ""), int(m.get("round", "0")))] = entry
            except ValueError:
                continue
        return found

    def _revision_text(self, name: str, round_: int) -> str:
        """round_ 라운드까지 반영된 name 의 설계안 텍스트."""
        if round_ <= 0:
            return self.ctx.transcript.read(self.state.proposals[name]).strip()
        entry = self._successful_critiques().get((name, round_))
        if entry is None:
            raise RuntimeError(f"기록을 찾을 수 없음: {name} 라운드 {round_} 비판")
        return split_revision(entry.body())

    def _critique_summary(self) -> str:
        items = sorted(self._successful_critiques().items(), key=lambda kv: (kv[0][1], kv[1].seq))
        return "\n\n".join(
            f"### R{rnd} {agent}의 비판\n{split_critique(entry.body())}" for (agent, rnd), entry in items
        )


def is_success(entry: Entry) -> bool:
    """성공한 호출의 기록인가. 실패 기록은 exit 0 이어도(한도·타임아웃) `_failed` 로 저장된다."""
    if entry.label.endswith("_failed"):
        return False
    m = entry.meta
    if "ok" in m:
        return m["ok"] == "true"
    return m.get("exit_code") == "0" and m.get("rate_limited") != "true" and m.get("timed_out") != "true"
