"""git 조작 래퍼. 모든 git 호출은 tenure.runner 를 지난다."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from tenure.runner import ExecutableNotFound, run_process
from tenure.state import TENURE_DIR

GIT_IDENTITY = ["-c", "user.name=tenure", "-c", "user.email=tenure@local",
                # 한글 등 비ASCII 파일 이름을 "\355\225..." 로 이스케이프하지 않게
                "-c", "core.quotepath=off",
                # 사용자 전역 설정의 commit.gpgsign=true 때문에 tenure 커밋이 실패하지 않게
                "-c", "commit.gpgsign=false"]
GITIGNORE_LINE = f"{TENURE_DIR}/"
# tenure 가 .gitignore 를 새로 만들 때만 넣는 빌드·테스트 부산물 (DESIGN.md 6장).
# 에이전트가 직접 돌린 테스트가 만든 캐시가 'tenure: impl round i' 커밋에 섞이지 않게 한다.
# build/, dist/, target/ 처럼 소스 폴더 이름과 겹칠 수 있는 것은 넣지 않는다.
GITIGNORE_ARTIFACTS = (
    "__pycache__/", "*.py[cod]", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
    ".coverage", "htmlcov/", "*.egg-info/", ".venv/", "node_modules/", ".DS_Store",
)


class GitError(Exception):
    pass


class WorkdirRefused(Exception):
    """작업 폴더 가드에 걸림. 메시지는 사용자에게 그대로 보여준다."""


class Workspace:
    def __init__(self, workdir: Path, *, git_bin: str = "git", timeout_sec: int = 120):
        self.workdir = Path(workdir)
        self.git_bin = git_bin
        self.timeout_sec = timeout_sec

    # ---------------------------------------------------------------- git
    def git(self, *args: str, check: bool = True) -> str:
        try:
            r = run_process([self.git_bin, *GIT_IDENTITY, *args], cwd=self.workdir, timeout_sec=self.timeout_sec)
        except ExecutableNotFound as e:
            raise GitError("git 을 찾을 수 없습니다. git 을 설치하세요.") from e
        if check and not r.ok:
            raise GitError(f"git {' '.join(args)} 실패 (exit {r.exit_code}): {r.stderr.strip()[-1000:]}")
        return r.stdout

    def is_repo(self) -> bool:
        if not (self.workdir / ".git").exists():
            return False
        return self.git("rev-parse", "--is-inside-work-tree", check=False).strip() == "true"

    def has_commits(self) -> bool:
        return self.is_repo() and bool(self.git("rev-parse", "--verify", "-q", "HEAD", check=False).strip())

    def ensure_repo(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        if not self.is_repo():
            self.git("init", "-q")
            # 에이전트가 쓴 바이트를 그대로 커밋·복원한다 (Windows 의 전역 autocrlf=true 대비, DESIGN.md 27.4)
            self.git("config", "core.autocrlf", "false")
        self.ensure_gitignore()

    def ensure_gitignore(self) -> None:
        """.tenure/ 를 무시하게 한다. 파일이 없으면 부산물 규칙과 함께 새로 만들고, 있으면 .tenure/ 만 덧붙인다."""
        path = self.workdir / ".gitignore"
        if not path.exists():
            path.write_text("\n".join([GITIGNORE_LINE, "", "# 빌드·테스트 부산물 (tenure 가 만듦)",
                                        *GITIGNORE_ARTIFACTS]) + "\n", encoding="utf-8")
            return
        existing = path.read_text(encoding="utf-8")
        lines = {ln.strip() for ln in existing.splitlines()}
        if GITIGNORE_LINE in lines or TENURE_DIR in lines:
            return
        sep = "" if (not existing or existing.endswith("\n")) else "\n"
        path.write_text(existing + sep + GITIGNORE_LINE + "\n", encoding="utf-8")

    # ---------------------------------------------------------------- status
    def status_lines(self) -> list[str]:
        out = self.git("status", "--porcelain", "--untracked-files=all")
        return [ln for ln in out.splitlines() if ln.strip()]

    def dirty_files(self) -> list[str]:
        files = []
        for ln in self.status_lines():
            path = ln[3:]
            if " -> " in path:  # rename: "old -> new"
                path = path.split(" -> ", 1)[1]
            files.append(path.strip('"'))
        return files

    def dirty(self) -> bool:
        return bool(self.status_lines())

    # ---------------------------------------------------------------- commit / diff
    def head(self, short: bool = True) -> str:
        args = ["rev-parse", "--short", "HEAD"] if short else ["rev-parse", "HEAD"]
        return self.git(*args).strip()

    def commit_all(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "--no-verify", "-m", message)
        return self.head()

    def commit_count(self) -> int:
        if not self.has_commits():
            return 0
        return int(self.git("rev-list", "--count", "HEAD").strip())

    @staticmethod
    def _pathspec(exclude: Iterable[str], exclude_globs: Iterable[str]) -> list[str]:
        spec = [".", *(f":(exclude,literal){e}" for e in exclude)]
        for g in exclude_globs:
            spec.append(f":(exclude,glob){g}" if "/" in g else f":(exclude,glob)**/{g}")
        return spec

    def diff(self, base: str, head: str = "HEAD", exclude: Iterable[str] = (),
             exclude_globs: Iterable[str] = (), context: bool = False) -> str:
        """context=True 면 바뀐 함수 전체를 보여 준다(--function-context, 리뷰 패킷용)."""
        extra = ["--function-context"] if context else []
        return self.git("diff", "--no-color", *extra, base, head, "--", *self._pathspec(exclude, exclude_globs))

    def diff_stat(self, base: str, head: str = "HEAD", exclude: Iterable[str] = ()) -> str:
        return self.git("diff", "--no-color", "--stat=200,150", base, head, "--", *self._pathspec(exclude, ()))

    # ---------------------------------------------------------------- restore
    def revert_paths(self, paths: Iterable[str]) -> None:
        """지금 HEAD 기준으로 이 파일들만 되돌린다: 추적 파일은 복원, 새 파일은 삭제 (DESIGN.md 29.2)."""
        for p in paths:
            if self.git("ls-tree", "--name-only", "HEAD", "--", p).strip():
                self.git("checkout", "HEAD", "--", p)
            else:
                target = self.workdir / p
                if target.is_file():
                    target.unlink()

    def restore_clean(self, keep: Sequence[str] = (TENURE_DIR, ".duet")) -> None:
        """추적 파일 되돌리기 + 미추적 파일 삭제(keep 은 제외)."""
        self.git("checkout", "--", ".")
        args = ["clean", "-fdq"]
        for k in keep:
            args += ["-e", k]
        self.git(*args)


# -------------------------------------------------------------------- guard
def check_workdir(workdir: Path, *, force: bool = False, allow: Sequence[str] = ()) -> Path:
    """작업 폴더 가드. 문제가 있으면 WorkdirRefused.

    `.tenure/` 아래 변경은 항상 무시한다(이전 실행의 기록). allow 에 든 경로(예: --skip-design 의
    DESIGN.md)도 무시한다.
    """
    wd = Path(workdir).expanduser().resolve()
    home = Path.home().resolve()
    if wd == Path(wd.anchor):
        raise WorkdirRefused(f"루트 디렉터리({wd})는 작업 폴더로 쓸 수 없습니다.")
    if wd == home:
        raise WorkdirRefused(f"홈 디렉터리({wd})는 작업 폴더로 쓸 수 없습니다. 하위 폴더를 지정하세요.")
    if wd.exists() and not wd.is_dir():
        raise WorkdirRefused(f"작업 폴더가 디렉터리가 아닙니다: {wd}")
    if wd.is_dir() and not force:
        ws = Workspace(wd)
        ignored = {*allow}
        files = [f for f in ws.dirty_files() if not f.startswith(GITIGNORE_LINE) and f not in ignored] \
            if ws.is_repo() else []
        if files:
            shown = "\n".join(f"  {f}" for f in files[:10]) + ("\n  ..." if len(files) > 10 else "")
            raise WorkdirRefused(
                f"작업 폴더에 커밋되지 않은 변경이 있습니다 ({len(files)}개):\n{shown}\n"
                "먼저 커밋하거나 --force 로 무시할 수 있습니다."
            )
    return wd
