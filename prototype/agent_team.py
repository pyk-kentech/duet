#!/usr/bin/env python3
"""
설계 토론 + 교차 리뷰 에이전트 팀

Claude Code(Claude 구독)와 Codex CLI(ChatGPT 구독)를 헤드리스로 호출해서
  1) 두 모델이 각자 설계안 제출 → 서로 비판 & 개정 → 한쪽이 최종 설계 종합
  2) 구현 담당이 코드 작성 → 리뷰 담당이 리뷰 → 승인될 때까지 수정 반복
을 자동으로 진행한다. 표준 라이브러리만 사용.

사용 예:
  python agent_team.py "마크다운 메모를 태그별로 검색하는 CLI 도구" --workdir ./memo-cli
  python agent_team.py "..." --workdir ./x --design-only        # 설계 토론만
  python agent_team.py "..." --workdir ./x --implementer codex --reviewer claude
  python agent_team.py "..." --workdir ./x --mock               # CLI 없이 흐름 테스트
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

# ------------------------------------------------------------------ 설정
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
TIMEOUT_SEC = int(os.environ.get("AGENT_TIMEOUT", "1200"))
MAX_DIFF_CHARS = 60_000  # 리뷰 프롬프트에 넣을 diff 최대 길이

# ------------------------------------------------------------------ 프롬프트
P_PROPOSE = """너는 소프트웨어 설계 토론에 참여한 시니어 엔지니어다.
과제: {task}

이 과제의 설계안을 마크다운으로 작성해라. 반드시 포함:
- 목표와 범위(하지 않을 것 포함)
- 기술 스택과 선택 이유
- 디렉터리/모듈 구조
- 핵심 데이터 구조와 인터페이스
- 구현 순서(작은 단계로)
- 예상 리스크
토이 프로젝트 규모에 맞게 과하지 않게. 설계안 본문만 출력하고 파일은 만들지 마라."""

P_CRITIQUE = """너는 설계 토론에 참여 중이다.
과제: {task}

[너의 현재 설계안]
{own}

[상대({other_name})의 설계안]
{other}

1) '## 상대 안 비판' 섹션: 상대 안의 약점, 빠진 점, 과설계를 구체적으로 지적하고, 상대 안에서 배울 점도 인정해라.
2) '## 개정안' 섹션: 비판과 배울 점을 반영한 너의 설계안 전체를 다시 작성해라.
파일은 만들지 말고 텍스트로만 답해라."""

P_SYNTH = """너는 설계 토론의 최종 결정권자다.
과제: {task}

[A 안 ({a_name})]
{a}

[B 안 ({b_name})]
{b}

[토론 중 나온 비판들]
{critiques}

두 안의 장점을 취해 하나의 최종 설계 문서를 마크다운으로 작성해라.
맨 위에 '## 결정 사항' 섹션으로 쟁점별 선택과 이유를 짧게 정리하고,
그 아래 구현자가 그대로 따라갈 수 있는 설계를 써라. 문서 본문만 출력하고 파일은 만들지 마라."""

P_IMPLEMENT = """현재 디렉터리의 DESIGN.md를 읽고 그 설계대로 프로젝트를 구현해라.
과제: {task}
- 설계에서 벗어나야 하면 이유를 IMPLEMENTATION_NOTES.md에 적어라.
- 가능하면 간단한 테스트도 작성하고 실행해 확인해라.
- DESIGN.md는 수정하지 마라.
작업이 끝나면 무엇을 만들었는지 짧게 요약해라."""

P_FIX = """현재 디렉터리의 프로젝트에 대해 다른 리뷰어가 아래 리뷰를 남겼다.
DESIGN.md를 참고해서 지적 사항을 반영해 코드를 수정해라.
동의하지 않는 지적이 있으면 반영하지 말고 IMPLEMENTATION_NOTES.md에 반론을 적어라.

[리뷰]
{review}

끝나면 무엇을 고쳤고 무엇을 반박했는지 짧게 요약해라."""

P_REVIEW = """너는 깐깐하지만 실용적인 코드 리뷰어다. 현재 디렉터리의 프로젝트를 리뷰해라.
과제: {task}
설계 문서는 DESIGN.md, 구현자의 메모는 IMPLEMENTATION_NOTES.md(있다면)에 있다.

[구현 전체 diff]
{diff}

파일을 직접 열어봐도 된다. 단, 아무 파일도 수정하지 마라.
다음 순서로 답해라:
## 반드시 고칠 것 (버그, 설계 위반, 동작 안 함)
## 고치면 좋은 것
## 잘한 점
마지막 줄에는 정확히 아래 둘 중 하나만 써라:
VERDICT: APPROVED
VERDICT: CHANGES_REQUESTED
'반드시 고칠 것'이 비어 있으면 APPROVED다. 사소한 취향 문제로 반려하지 마라."""


# ------------------------------------------------------------------ 유틸
def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def run(cmd, cwd, stdin_text=None) -> str:
    try:
        r = subprocess.run(
            cmd, cwd=cwd, input=stdin_text, capture_output=True,
            text=True, timeout=TIMEOUT_SEC,
        )
    except FileNotFoundError:
        sys.exit(f"실행 파일을 찾을 수 없음: {cmd[0]}  (설치/로그인 확인)")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"시간 초과({TIMEOUT_SEC}s): {cmd[0]}")
    if r.returncode != 0:
        raise RuntimeError(
            f"{cmd[0]} 실패 (exit {r.returncode})\n"
            f"stderr: {r.stderr[-2000:]}\nstdout: {r.stdout[-2000:]}"
        )
    return r.stdout


def git(workdir, *args) -> str:
    return run(["git", "-c", "user.name=agent-team",
                "-c", "user.email=agent-team@local", *args], workdir)


# ------------------------------------------------------------------ 에이전트
class ClaudeAgent:
    name = "Claude"

    def ask(self, prompt: str, cwd: pathlib.Path, write: bool = False) -> str:
        cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
        if write:
            cmd += ["--permission-mode", "acceptEdits",
                    "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash"]
        else:
            cmd += ["--allowedTools", "Read,Glob,Grep"]
        out = run(cmd, cwd)
        try:
            return json.loads(out).get("result", out)
        except json.JSONDecodeError:
            return out


class CodexAgent:
    name = "Codex"

    def ask(self, prompt: str, cwd: pathlib.Path, write: bool = False) -> str:
        with tempfile.NamedTemporaryFile("r", suffix=".md", delete=False) as f:
            last_msg = f.name
        cmd = [CODEX_BIN, "exec", "--skip-git-repo-check",
               "-C", str(cwd),
               "--sandbox", "workspace-write" if write else "read-only",
               "--output-last-message", last_msg,
               prompt]
        out = run(cmd, cwd)
        try:
            text = pathlib.Path(last_msg).read_text(encoding="utf-8").strip()
        finally:
            pathlib.Path(last_msg).unlink(missing_ok=True)
        return text or out


class MockAgent:
    """CLI 없이 오케스트레이션 흐름만 검증하는 가짜 에이전트."""

    def __init__(self, name):
        self.name = f"Mock{name}"
        self.reviews = 0

    def ask(self, prompt, cwd, write=False):
        if "최종 결정권자" in prompt:
            return f"## 결정 사항\n- ({self.name}) 단순한 쪽 채택\n\n# 최종 설계\n- main.py 하나"
        if "설계 토론에 참여 중" in prompt:
            return f"## 상대 안 비판\n- 과설계\n\n## 개정안\n# {self.name} 개정안\n- 단일 파일"
        if "설계안을 마크다운으로" in prompt:
            return f"# {self.name} 설계안\n- 모듈 2개"
        if write:
            p = pathlib.Path(cwd) / "main.py"
            p.write_text(p.read_text() + "# fix\n" if p.exists() else "print('hi')\n")
            return f"{self.name}: 구현/수정 완료"
        if "코드 리뷰어" in prompt:
            self.reviews += 1
            if self.reviews >= 2:
                return "## 반드시 고칠 것\n(없음)\n\nVERDICT: APPROVED"
            return "## 반드시 고칠 것\n- 예외 처리 없음\n\nVERDICT: CHANGES_REQUESTED"
        return "ok"


def make_agent(kind: str, mock: bool):
    if mock:
        return MockAgent(kind.capitalize())
    return {"claude": ClaudeAgent, "codex": CodexAgent}[kind]()


# ------------------------------------------------------------------ 기록
class Transcript:
    def __init__(self, workdir: pathlib.Path):
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = workdir / ".agent-runs" / stamp
        self.dir.mkdir(parents=True, exist_ok=True)
        self.n = 0

    def save(self, label: str, text: str) -> pathlib.Path:
        self.n += 1
        p = self.dir / f"{self.n:02d}_{label}.md"
        p.write_text(text, encoding="utf-8")
        return p


# ------------------------------------------------------------------ 1단계: 설계 토론
def split_revision(text: str) -> str:
    m = re.search(r"^##\s*개정안\s*$", text, flags=re.M)
    return text[m.end():].strip() if m else text


def design_debate(task, a, b, synth, rounds, workdir, tr) -> str:
    log(f"설계안 작성: {a.name}")
    pa = a.ask(P_PROPOSE.format(task=task), workdir)
    tr.save(f"proposal_{a.name}", pa)
    log(f"설계안 작성: {b.name}")
    pb = b.ask(P_PROPOSE.format(task=task), workdir)
    tr.save(f"proposal_{b.name}", pb)

    critiques = []
    for r in range(1, rounds + 1):
        log(f"토론 라운드 {r}/{rounds}: {a.name} → {b.name} 비판")
        ca = a.ask(P_CRITIQUE.format(task=task, own=pa, other=pb, other_name=b.name), workdir)
        tr.save(f"r{r}_critique_{a.name}", ca)
        log(f"토론 라운드 {r}/{rounds}: {b.name} → {a.name} 비판")
        cb = b.ask(P_CRITIQUE.format(task=task, own=pb, other=pa, other_name=a.name), workdir)
        tr.save(f"r{r}_critique_{b.name}", cb)
        critiques.append(f"### R{r} {a.name}의 비판\n{ca.split('## 개정안')[0]}")
        critiques.append(f"### R{r} {b.name}의 비판\n{cb.split('## 개정안')[0]}")
        pa, pb = split_revision(ca), split_revision(cb)

    log(f"최종 설계 종합: {synth.name}")
    final = synth.ask(P_SYNTH.format(
        task=task, a=pa, b=pb, a_name=a.name, b_name=b.name,
        critiques="\n\n".join(critiques) or "(비판 라운드 없음)",
    ), workdir)
    tr.save("final_design", final)
    (workdir / "DESIGN.md").write_text(final, encoding="utf-8")
    log("DESIGN.md 저장 완료")
    return final


# ------------------------------------------------------------------ 2단계: 구현 + 교차 리뷰
def verdict_of(review: str) -> str:
    found = re.findall(r"VERDICT:\s*(APPROVED|CHANGES_REQUESTED)", review)
    return found[-1] if found else "CHANGES_REQUESTED"


def implement_and_review(task, impl, reviewer, max_rounds, workdir, tr) -> bool:
    if not (workdir / ".git").exists():
        git(workdir, "init", "-q")
    ignore = workdir / ".gitignore"
    if ".agent-runs" not in (ignore.read_text() if ignore.exists() else ""):
        with ignore.open("a") as f:
            f.write(".agent-runs/\n")
    git(workdir, "add", "-A")
    git(workdir, "commit", "-q", "--allow-empty", "-m", "design: DESIGN.md")
    base = git(workdir, "rev-parse", "HEAD").strip()

    review = None
    for i in range(1, max_rounds + 1):
        if review is None:
            log(f"[{i}/{max_rounds}] 구현: {impl.name}")
            summary = impl.ask(P_IMPLEMENT.format(task=task), workdir, write=True)
        else:
            log(f"[{i}/{max_rounds}] 리뷰 반영: {impl.name}")
            summary = impl.ask(P_FIX.format(review=review), workdir, write=True)
        tr.save(f"impl{i}_{impl.name}", summary)
        git(workdir, "add", "-A")
        git(workdir, "commit", "-q", "--allow-empty", "-m", f"impl round {i} by {impl.name}")

        diff = git(workdir, "diff", base, "HEAD", "--", ".", ":(exclude)DESIGN.md")
        if len(diff) > MAX_DIFF_CHARS:
            diff = diff[:MAX_DIFF_CHARS] + "\n... (diff가 길어 잘림. 나머지는 파일을 직접 열어 확인)"
        log(f"[{i}/{max_rounds}] 리뷰: {reviewer.name}")
        review = reviewer.ask(P_REVIEW.format(task=task, diff=diff or "(변경 없음)"), workdir)
        tr.save(f"review{i}_{reviewer.name}", review)

        # 리뷰어가 read-only를 어기고 파일을 건드렸으면 되돌린다
        if git(workdir, "status", "--porcelain").strip():
            log("경고: 리뷰어가 파일을 변경함 → 되돌림")
            git(workdir, "checkout", "--", ".")
            git(workdir, "clean", "-fdq", "-e", ".agent-runs")

        v = verdict_of(review)
        log(f"[{i}/{max_rounds}] 판정: {v}")
        if v == "APPROVED":
            return True
    return False


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="설계 토론 + 교차 리뷰 에이전트 팀")
    ap.add_argument("task", help="만들 것 (한 줄 설명, 또는 @파일경로로 긴 설명)")
    ap.add_argument("--workdir", required=True, help="프로젝트 디렉터리 (없으면 생성)")
    ap.add_argument("--implementer", choices=["claude", "codex"], default="claude")
    ap.add_argument("--reviewer", choices=["claude", "codex"], default="codex")
    ap.add_argument("--synth", choices=["claude", "codex"], default=None,
                    help="최종 설계 종합 담당 (기본: 리뷰어)")
    ap.add_argument("--debate-rounds", type=int, default=1)
    ap.add_argument("--max-review", type=int, default=3, help="구현-리뷰 최대 반복")
    ap.add_argument("--design-only", action="store_true")
    ap.add_argument("--skip-design", action="store_true", help="기존 DESIGN.md로 바로 구현")
    ap.add_argument("--mock", action="store_true", help="CLI 호출 없이 흐름만 테스트")
    args = ap.parse_args()

    task = args.task
    if task.startswith("@"):
        task = pathlib.Path(task[1:]).read_text(encoding="utf-8")

    workdir = pathlib.Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    tr = Transcript(workdir)
    log(f"기록 위치: {tr.dir}")

    agents = {k: make_agent(k, args.mock) for k in ("claude", "codex")}
    impl, reviewer = agents[args.implementer], agents[args.reviewer]
    synth = agents[args.synth or args.reviewer]

    if not args.skip_design:
        design_debate(task, agents["claude"], agents["codex"], synth,
                      args.debate_rounds, workdir, tr)
    elif not (workdir / "DESIGN.md").exists():
        sys.exit("--skip-design 인데 DESIGN.md가 없음")

    if args.design_only:
        log("설계만 완료. DESIGN.md를 확인하세요.")
        return

    ok = implement_and_review(task, impl, reviewer, args.max_review, workdir, tr)
    log("✅ 리뷰 승인으로 종료" if ok else
        f"⚠️ {args.max_review}회 안에 승인되지 않음. 마지막 리뷰를 확인하세요.")
    log(f"전체 대화 기록: {tr.dir}")


if __name__ == "__main__":
    main()
