"""worktree 실행의 병합 준비 점검·병합·버리기 (DESIGN.md 36.14).

점검은 보여 주기만 하고, 병합은 사람이 누른다. 병합·버리기가 끝나면 worktree 를 지우되 실행 기록은 프로젝트의
`.tenure/runs/` 로 옮기고 브랜치는 남긴다.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tenure import worktree
from tenure.lock import read_lock
from tenure.phases.followup import latest_tests
from tenure.state import (DONE_APPROVED, DONE_DESIGN, DONE_UNAPPROVED, FAILED, RUNNING, STOPPED_RATE_LIMIT,
                          STOPPED_USER, RunState, project_dir, runs_root)
from tenure.workspace import GitError, Workspace

BLOCK, WARN, OK = "block", "warn", "ok"
SQUASH, MERGE = "squash", "merge"
DISCARDED_DIR = "discarded"
STATUS_KO = {RUNNING: "진행 중", STOPPED_USER: "중지됨", STOPPED_RATE_LIMIT: "한도로 멈춤", FAILED: "실패"}


class MergeError(Exception):
    pass


@dataclass
class Check:
    key: str
    level: str          # block | warn | ok
    label: str
    detail: str = ""


@dataclass
class Readiness:
    run_id: str
    tree: dict
    checks: list[Check] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    ahead: int = 0      # 작업 브랜치에만 있는 커밋
    behind: int = 0     # 기준 브랜치에만 있는 커밋 (만든 뒤 앞서 감)
    files: list[str] = field(default_factory=list)   # 기준 대비 바뀐 파일

    @property
    def can_merge(self) -> bool:
        return self.tree.get("status") == worktree.OPEN and not any(c.level == BLOCK for c in self.checks)

    def to_dict(self) -> dict:
        return {**asdict(self), "can_merge": self.can_merge}


def _own_files(ws: Workspace) -> list[str]:
    return [f for f in ws.dirty_files() if not f.startswith(".tenure")]


def _main_changes(ws: Workspace) -> tuple[list[str], list[str]]:
    """프로젝트 폴더의 (추적 파일 변경, 추적하지 않는 파일). .tenure 는 뺀다."""
    tracked, untracked = [], []
    for ln in ws.status_lines():
        path = ln[3:].split(" -> ", 1)[-1].strip('"')
        if path.startswith(".tenure"):
            continue
        (untracked if ln.startswith("??") else tracked).append(path)
    return tracked, untracked


def _tree_or_error(project: Path, run_id: str) -> worktree.Tree:
    t = worktree.find(project, run_id)
    if t is None:
        raise MergeError(f"이 실행은 worktree 에서 돌지 않았습니다: {run_id}")
    return t


def _run_dir(tree: worktree.Tree, project: Path) -> Path | None:
    for base in (Path(tree.path), project):
        d = runs_root(base) / tree.run_id
        if (d / "run.json").is_file():
            return d
    return None


def readiness(project: Path, run_id: str) -> Readiness:
    project = Path(project)
    tree = _tree_or_error(project, run_id)
    r = Readiness(run_id=run_id, tree=asdict(tree))
    add = lambda key, level, label, detail="": r.checks.append(Check(key, level, label, detail))   # noqa: E731
    if tree.status != worktree.OPEN:
        add("status", BLOCK, "이미 병합됨" if tree.status == worktree.MERGED else "버려짐",
            tree.merged_commit or tree.patch or "")
        return r
    if not Path(tree.path).is_dir():
        add("missing", BLOCK, "worktree 폴더가 없습니다", tree.path)
        return r
    main, wt = Workspace(project), Workspace(Path(tree.path))
    target = tree.base_branch

    # 실행 상태
    rd = _run_dir(tree, project)
    st = RunState.load(rd) if rd is not None else None
    live = read_lock(Path(tree.path))
    if st is None:
        add("run", WARN, "실행 기록을 찾을 수 없습니다")
    elif live is not None or st.status == RUNNING:
        add("run", BLOCK, "실행이 끝나지 않았습니다", "진행 중" if live is not None else "멈춘 채 남음 — 이어하거나 버리세요")
    elif st.status not in (DONE_APPROVED, DONE_UNAPPROVED, DONE_DESIGN):
        add("run", BLOCK, "실행이 끝나지 않았습니다", STATUS_KO.get(st.status, st.status))
    else:
        add("run", OK, "실행 끝남")
    if st is not None and st.status in (DONE_APPROVED, DONE_UNAPPROVED):
        add("review", OK if st.status == DONE_APPROVED else WARN,
            "리뷰 승인" if st.status == DONE_APPROVED else "리뷰 미승인", st.last_verdict or "")
    if st is not None and st.status in (DONE_APPROVED, DONE_UNAPPROVED):
        last = latest_tests(st.tests, st.followups)
        if last is None:
            add("tests", WARN, "테스트를 돌리지 않았습니다")
        elif last.get("status") == "passed":
            add("tests", OK, "마지막 테스트 통과", str(last.get("summary") or ""))
        else:
            add("tests", BLOCK, "마지막 테스트 실패", str(last.get("summary") or last.get("status") or ""))

    # 작업 트리
    try:
        loose = _own_files(wt)
        if loose:
            add("tree_dirty", WARN, f"worktree 에 커밋 안 한 변경 {len(loose)}개", "병합에는 커밋된 것만 들어갑니다: "
                + ", ".join(loose[:5]))
        if not target:
            add("base", BLOCK, "기준 브랜치가 없습니다", "만들 때 분리된 HEAD 였습니다. 직접 병합하세요: " + tree.branch)
            return r
        current = main.git("rev-parse", "--abbrev-ref", "HEAD").strip()
        if current != target:
            add("checkout", BLOCK, f"프로젝트 폴더가 {current} 에 있습니다", f"{target} 를 체크아웃해야 병합할 수 있습니다")
        if main.git("rev-parse", "--verify", "--quiet", f"refs/heads/{target}", check=False).strip() == "":
            add("base", BLOCK, f"기준 브랜치 {target} 가 없습니다")
            return r
        r.ahead = int(main.git("rev-list", "--count", f"{target}..{tree.branch}").strip() or 0)
        r.behind = int(main.git("rev-list", "--count", f"{tree.branch}..{target}").strip() or 0)
        r.files = [f for f in main.git("diff", "--name-only", f"{target}...{tree.branch}").splitlines() if f.strip()]
        tracked, untracked = _main_changes(main)
        clash = sorted(set(untracked) & set(r.files))
        if tracked or clash:
            shown = tracked + clash
            add("main_dirty", BLOCK, f"프로젝트 폴더에 커밋 안 한 변경 {len(shown)}개",
                "병합이 그 폴더를 바꾸므로 먼저 커밋하거나 치우세요: " + ", ".join(shown[:5]))
        elif untracked:
            add("main_dirty", WARN, f"프로젝트 폴더에 추적하지 않는 파일 {len(untracked)}개", "병합과 겹치지 않습니다")
        if r.ahead == 0 or not r.files:
            add("empty", BLOCK, "합칠 변경이 없습니다")
        if r.behind:
            add("behind", WARN, f"기준 브랜치가 {r.behind}커밋 앞서 있습니다", "충돌이 없으면 그대로 합칠 수 있습니다")
        r.conflicts = conflicts(main, target, tree.branch)
        if r.conflicts:
            add("conflicts", BLOCK, f"충돌 {len(r.conflicts)}개", ", ".join(r.conflicts[:8]))
        elif r.ahead:
            add("conflicts", OK, "충돌 없음")
    except GitError as e:
        add("git", BLOCK, "git 확인 실패", str(e)[-300:])
    return r


def conflicts(ws: Workspace, ours: str, theirs: str) -> list[str]:
    """`git merge-tree --write-tree` 로 실제 병합 없이 충돌 파일을 본다 (git 2.38+)."""
    out = ws.git("merge-tree", "--write-tree", "--name-only", "--no-messages", ours, theirs, check=False)
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[1:]     # 첫 줄은 트리 id. 충돌이 없으면 그것만 나온다


def _message(project: Path, tree: worktree.Tree) -> str:
    rd = _run_dir(tree, project)
    task = ""
    if rd is not None:
        try:
            task = RunState.load(rd).task
        except (OSError, ValueError):
            task = ""
    first = next((ln.strip() for ln in task.splitlines() if ln.strip()), "") or tree.run_id
    return f"{first[:72]}\n\ntenure 실행 {tree.run_id} (브랜치 {tree.branch})"


def merge(project: Path, run_id: str, mode: str = SQUASH) -> dict:
    project = Path(project)
    if mode not in (SQUASH, MERGE):
        raise MergeError(f"병합 방식은 squash 또는 merge 입니다: {mode}")
    ready = readiness(project, run_id)
    if not ready.can_merge:
        blocks = [c.label + (f" ({c.detail})" if c.detail else "") for c in ready.checks if c.level == BLOCK]
        raise MergeError("병합할 수 없습니다: " + "; ".join(blocks))
    tree = _tree_or_error(project, run_id)
    ws = Workspace(project)
    msg = _message(project, tree)
    try:
        if mode == SQUASH:
            ws.git("merge", "--squash", tree.branch)
            ws.git("commit", "-q", "--no-verify", "-m", msg, as_user=True)
        else:
            ws.git("merge", "--no-ff", "--no-verify", "-m", msg, tree.branch, as_user=True)
    except GitError as e:
        ws.git("merge", "--abort", check=False)
        ws.git("reset", "--merge", check=False)
        raise MergeError(f"병합에 실패해 되돌렸습니다: {e}") from e
    commit = ws.head(short=False)
    _finish(project, tree, worktree.MERGED, merged_commit=commit)
    return {"run_id": run_id, "mode": mode, "commit": commit, "branch": tree.branch, "into": tree.base_branch}


def discard(project: Path, run_id: str) -> dict:
    """기준 대비 변경(커밋 안 한 것 포함)을 패치로 남기고 worktree 를 지운다. 브랜치는 남긴다."""
    project = Path(project)
    tree = _tree_or_error(project, run_id)
    if tree.status != worktree.OPEN:
        raise MergeError(f"이미 {'병합' if tree.status == worktree.MERGED else '버린'} 실행입니다.")
    if read_lock(Path(tree.path)) is not None:
        raise MergeError("실행이 진행 중입니다. 먼저 중지하세요.")
    patch_rel = None
    if Path(tree.path).is_dir():
        patch_rel = save_patch(project, tree, f"{run_id}.patch")
    _finish(project, tree, worktree.DISCARDED, patch=patch_rel)
    return {"run_id": run_id, "patch": patch_rel, "branch": tree.branch}


def save_patch(project: Path, tree: worktree.Tree, name: str) -> str | None:
    wt = Workspace(Path(tree.path))
    wt.git("add", "-A")              # .tenure/ 는 info/exclude 로 무시된다
    text = wt.git("diff", "--cached", "--binary", tree.base_commit)
    if not text.strip():
        return None
    out = project_dir(project) / DISCARDED_DIR / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out.relative_to(project).as_posix()


def _finish(project: Path, tree: worktree.Tree, status: str, **changes) -> None:
    """실행 기록을 프로젝트로 옮기고 worktree 를 지운 뒤 색인을 갱신한다."""
    src = runs_root(Path(tree.path)) / tree.run_id
    if src.is_dir():
        dst = runs_root(project) / tree.run_id
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.move(str(src), str(dst))
    if status == worktree.MERGED and Path(tree.path).is_dir() and _own_files(Workspace(Path(tree.path))):
        changes["patch"] = save_patch(project, tree, f"{tree.run_id}-uncommitted.patch")
    try:
        worktree.remove(project, tree, force=True)
    except worktree.WorktreeError as e:
        changes.setdefault("note", dict(tree.note))["remove_error"] = str(e)[-300:]
    worktree.update(project, tree.run_id, status=status, **changes)
