"""DebatePhase — 설계 토론.

propose(A), propose(B)
for r in 1..debate_rounds: critique(A←B), critique(B←A)   # 각자 개정안 반환
synthesize(synth) → <workdir>/DESIGN.md

resume: state.done 에 있는 스텝은 건너뛰고, 필요한 텍스트는 transcript 파일에서 다시 읽는다.
"""

from __future__ import annotations

import re

from duet.agents.base import Mode
from duet.phases.common import PhaseContext
from duet.prompts import render
from duet.state import PHASE_DEBATE

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
    def __init__(self, ctx: PhaseContext):
        self.ctx = ctx
        self.state = ctx.state
        self.cfg = ctx.cfg
        self.rounds = ctx.cfg.debate_rounds
        self.synth = ctx.cfg.synth_name

    # ---------------------------------------------------------------- run
    def run(self) -> str:
        ctx, st = self.ctx, self.state
        a, b = PARTICIPANTS

        for name in (a, b):
            key = f"propose:{name}"
            if not st.is_done(key):
                ctx.set_position(PHASE_DEBATE, "propose", 0)
                ctx.save()
                ctx.log(f"설계안 작성: {name}")
                out = ctx.call(name, "propose", render("propose", ctx.workdir, task=ctx.task),
                               Mode.READ, label=f"propose_{name}")
                st.proposals[name] = out.file
                st.revisions[name] = out.file
                st.mark_done(key)
                ctx.save()

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
                prompt = render("critique", ctx.workdir, task=ctx.task,
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
            prompt = render(
                "synthesize", ctx.workdir, task=ctx.task,
                a=self._revision_text(a, self.rounds), b=self._revision_text(b, self.rounds),
                a_name=a, b_name=b, critiques=self._critique_summary() or "(비판 라운드 없음)",
            )
            out = ctx.call(self.synth, "synthesize", prompt, Mode.READ, label=f"synthesize_{self.synth}")
            st.final_design = out.file
            st.mark_done("synthesize")
            ctx.save()

        final = ctx.transcript.read(st.final_design)  # type: ignore[arg-type]
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
    def _revision_text(self, name: str, round_: int) -> str:
        """round_ 라운드까지 반영된 name 의 설계안 텍스트."""
        if round_ <= 0:
            return self.ctx.transcript.read(self.state.proposals[name]).strip()
        for entry in self.ctx.transcript.entries():
            m = entry.meta
            if m.get("step") == "critique" and m.get("agent") == name and m.get("round") == str(round_) \
                    and m.get("exit_code") == "0":
                return split_revision(entry.body())
        raise RuntimeError(f"기록을 찾을 수 없음: {name} 라운드 {round_} 비판")

    def _critique_summary(self) -> str:
        parts = []
        for entry in self.ctx.transcript.entries():
            m = entry.meta
            if m.get("step") != "critique" or m.get("exit_code") != "0":
                continue
            parts.append(f"### R{m.get('round')} {m.get('agent')}의 비판\n{split_critique(entry.body())}")
        return "\n\n".join(parts)
