"""작업마다 git worktree (DESIGN.md 36.6·36.14).

실행마다 `<프로젝트>/.tenure/worktrees/<실행 id>` 에 브랜치 `tenure/<실행 id>` 로 worktree 를 만든다. 실행 기록은
worktree 안에 두고, 프로젝트의 `.tenure/worktrees.json` 에 색인한다. 병합·버리기는 merge.py.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tenure import procs
from tenure.state import list_run_dirs, new_run_id, project_dir, runs_root
from tenure.workspace import GitError, Workspace

INDEX_FILE = "worktrees.json"
TREES_DIR = "worktrees"
BRANCH_PREFIX = "tenure/"
INCLUDE_FILE = ".tenureinclude"
DEFAULT_INCLUDES = (".env", ".env.*")
INCLUDE_MAX_BYTES = 5 * 1024 * 1024

OPEN, MERGED, DISCARDED = "open", "merged", "discarded"


class WorktreeError(Exception):
    pass


@dataclass
class Tree:
    run_id: str
    path: str
    branch: str
    base_branch: str          # 만들 때 체크아웃돼 있던 브랜치 (분리된 HEAD 면 "")
    base_commit: str
    created: str
    status: str = OPEN
    merged_commit: str | None = None
    patch: str | None = None
    note: dict = field(default_factory=dict)


def _index_path(project: Path) -> Path:
    return project_dir(project) / INDEX_FILE


def load_index(project: Path) -> list[Tree]:
    try:
        data = json.loads(_index_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    keys = set(Tree.__dataclass_fields__)
    return [Tree(**{k: v for k, v in d.items() if k in keys}) for d in data if isinstance(d, dict) and d.get("run_id")]


def save_index(project: Path, trees: list[Tree]) -> None:
    path = _index_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(INDEX_FILE + ".tmp")
    tmp.write_text(json.dumps([asdict(t) for t in trees], ensure_ascii=False, indent=1), encoding="utf-8")
    procs.replace_file(tmp, path)


def update(project: Path, run_id: str, **changes) -> Tree | None:
    trees = load_index(project)
    hit = None
    for t in trees:
        if t.run_id == run_id:
            for k, v in changes.items():
                setattr(t, k, v)
            hit = t
    if hit is not None:
        save_index(project, trees)
    return hit


def find(project: Path, run_id: str) -> Tree | None:
    return next((t for t in load_index(project) if t.run_id == run_id), None)


def is_tenure_worktree(path: Path) -> bool:
    """이 폴더가 tenure 가 만든 worktree 안인가 (worktree 안에서 또 worktree 를 만들지 않게)."""
    parts = [p.lower() for p in Path(path).resolve().parts]
    return any(parts[i] == ".tenure" and i + 1 < len(parts) and parts[i + 1] == TREES_DIR for i in range(len(parts)))


def should_use(workdir: Path, mode: str) -> bool:
    if mode != "auto" or is_tenure_worktree(workdir):
        return False
    ws = Workspace(workdir)
    try:
        if not ws.is_repo() or not ws.has_commits():
            return False
        top = Path(ws.git("rev-parse", "--show-toplevel").strip())
    except GitError:
        return False
    return top.resolve() == Path(workdir).resolve()        # 하위 폴더를 작업 폴더로 준 경우는 그대로


def _ensure_excluded(ws: Workspace) -> None:
    """`.tenure/` 를 저장소의 info/exclude 에 둔다(사용자 .gitignore 는 건드리지 않음). 모든 worktree 에 적용된다."""
    common = Path(ws.git("rev-parse", "--git-common-dir").strip())
    if not common.is_absolute():
        common = (ws.workdir / common).resolve()
    exclude = common / "info" / "exclude"
    try:
        lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.is_file() else []
    except OSError:
        lines = []
    if ".tenure/" not in lines:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join([*lines, ".tenure/"]) + "\n", encoding="utf-8")


def include_patterns(project: Path) -> list[str]:
    pats = list(DEFAULT_INCLUDES)
    try:
        for line in (Path(project) / INCLUDE_FILE).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pats.append(line)
    except OSError:
        pass
    return pats


def copy_includes(project: Path, dest: Path) -> list[str]:
    """`.gitignore` 된 파일 중 패턴에 맞는 것(최상위·하위 폴더 상대 경로)을 새 worktree 로 복사한다."""
    ws = Workspace(project)
    try:
        ignored = ws.git("ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "--no-empty-directory").splitlines()
    except GitError:
        return []
    pats = include_patterns(project)
    copied: list[str] = []
    for rel in ignored:
        rel = rel.strip().rstrip("/")
        if not rel or rel.startswith(".tenure") or rel.startswith(".git"):
            continue
        name = rel.split("/")[-1]
        if not any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in pats):
            continue
        src = Path(project) / rel
        if not src.is_file() or src.stat().st_size > INCLUDE_MAX_BYTES:
            continue
        target = Path(dest) / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(rel)
    return copied


def create(project: Path, run_id: str) -> Tree:
    project = Path(project)
    ws = Workspace(project)
    try:
        base_commit = ws.head(short=False)
        base_branch = ws.git("rev-parse", "--abbrev-ref", "HEAD").strip()
        if base_branch == "HEAD":
            base_branch = ""
        _ensure_excluded(ws)
        path = project_dir(project) / TREES_DIR / run_id
        branch = BRANCH_PREFIX + run_id
        path.parent.mkdir(parents=True, exist_ok=True)
        ws.git("worktree", "add", "-b", branch, str(path), base_commit)
    except GitError as e:
        raise WorktreeError(f"worktree 를 만들지 못했습니다: {e}") from e
    tree = Tree(run_id=run_id, path=str(path), branch=branch, base_branch=base_branch, base_commit=base_commit,
                created=dt.datetime.now().isoformat(timespec="seconds"))
    copied = copy_includes(project, path)
    if copied:
        tree.note["included"] = copied
    trees = [t for t in load_index(project) if t.run_id != run_id]
    save_index(project, [*trees, tree])
    return tree


def remove(project: Path, tree: Tree, *, force: bool = False) -> None:
    ws = Workspace(Path(project))
    try:
        if Path(tree.path).exists():
            ws.git("worktree", "remove", *(["--force"] if force else []), tree.path)
        ws.git("worktree", "prune", check=False)
    except GitError as e:
        raise WorktreeError(f"worktree 를 지우지 못했습니다: {e}") from e


def locate(project: Path, run_id: str) -> Path | None:
    """실행이 worktree 에 있으면 그 worktree 경로 (없으면 None)."""
    t = find(Path(project), run_id)
    return Path(t.path) if t is not None and Path(t.path).is_dir() else None


def all_run_dirs(project: Path) -> list[Path]:
    """프로젝트 폴더의 실행과 그 프로젝트가 만든 worktree 들의 실행 (실행 id 순)."""
    project = Path(project)
    dirs = list(list_run_dirs(project))
    seen = {d.name for d in dirs}
    for t in load_index(project):
        if t.run_id in seen:
            continue
        for d in list_run_dirs(Path(t.path)):
            if d.name == t.run_id:
                dirs.append(d)
                seen.add(d.name)
    return sorted(dirs, key=lambda d: d.name)


def code_dir(run_dir: Path) -> Path:
    """실행 기록 폴더(`<코드 폴더>/.tenure/runs/<id>`)의 코드 폴더 — 프로젝트 또는 worktree."""
    return Path(run_dir).parents[2]


def project_of(path: Path) -> Path:
    """worktree 경로면 그 프로젝트, 아니면 그대로 (`<프로젝트>/.tenure/worktrees/<id>`)."""
    path = Path(path)
    return path.parents[2] if is_tenure_worktree(path) and path.parent.name == TREES_DIR else path


def _taken(project: Path, run_id: str, ws: Workspace | None) -> bool:
    if (runs_root(project) / run_id).exists() or (project_dir(project) / TREES_DIR / run_id).exists():
        return True
    if any(t.run_id == run_id for t in load_index(project)):
        return True
    if ws is not None:
        return ws.git("rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH_PREFIX}{run_id}", check=False).strip() != ""
    return False


def unique_run_id(project: Path, wanted: str | None = None, *, git: bool = True) -> str:
    """프로젝트 기록·worktree·브랜치와 겹치지 않는 실행 id. wanted 가 이미 쓰였으면 WorktreeError."""
    ws = Workspace(Path(project)) if git else None
    if wanted:
        if _taken(project, wanted, ws):
            raise WorktreeError(f"실행 id 가 이미 쓰였습니다: {wanted}")
        return wanted
    base = new_run_id()
    rid, n = base, 1
    while _taken(project, rid, ws):
        n += 1
        rid = f"{base}-{n}"
    return rid
