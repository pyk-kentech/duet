"""RunState — 실행 상태 직렬화. 각 스텝이 끝날 때마다 run.json 에 저장해 resume 에 쓴다."""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RUN_JSON = "run.json"
DUET_DIR = ".duet"
RUNS_DIR = "runs"

# status 값
RUNNING = "running"
DONE_APPROVED = "done_approved"
DONE_UNAPPROVED = "done_unapproved"
DONE_DESIGN = "done_design"          # --design-only 로 설계만 끝냄
STOPPED_RATE_LIMIT = "stopped_rate_limit"
STOPPED_USER = "stopped_user"        # Ctrl-C 또는 UI 의 중지(SIGTERM)
FAILED = "failed"
FINAL_STATUSES = frozenset({DONE_APPROVED, DONE_UNAPPROVED, DONE_DESIGN})

# phase 값
PHASE_INIT = "init"
PHASE_DEBATE = "debate"
PHASE_BUILD = "build"
PHASE_DONE = "done"


@dataclass
class CallRecord:
    agent: str
    step: str
    sec: float
    exit: int
    rate_limited: bool = False
    timed_out: bool = False
    file: str | None = None
    usage: dict | None = None


@dataclass
class RunState:
    run_id: str
    task: str
    config: dict[str, Any] = field(default_factory=dict)
    phase: str = PHASE_INIT
    step: str = ""
    round: int = 0
    status: str = RUNNING
    base_commit: str | None = None
    proposals: dict[str, str] = field(default_factory=dict)   # agent -> 최초 설계안 파일
    revisions: dict[str, str] = field(default_factory=dict)   # agent -> 최신 개정안 파일
    critiques: list[str] = field(default_factory=list)        # 비판 파일(순서대로)
    final_design: str | None = None
    last_impl: str | None = None
    last_review: str | None = None
    last_verdict: str | None = None
    done: list[str] = field(default_factory=list)             # 완료한 스텝 키
    tests: dict[str, dict] = field(default_factory=dict)      # round → duet 가 돌린 테스트 결과
    review_history: list[dict] = field(default_factory=list)  # 라운드별 판정·막는 지적 수
    stop_reason: str | None = None                            # "max_review" | "stalled"
    stall_baseline_round: int = 0                             # resume 때 수렴 판단을 이 라운드부터 다시
    calls: list[CallRecord] = field(default_factory=list)
    error: str | None = None
    created_at: str = field(default_factory=lambda: dt.datetime.now().isoformat(timespec="seconds"))
    updated_at: str = ""

    # ---------------------------------------------------------------- steps
    def is_done(self, key: str) -> bool:
        return key in self.done

    def mark_done(self, key: str) -> None:
        if key not in self.done:
            self.done.append(key)

    def record_call(self, agent: str, step: str, sec: float, exit_code: int, *,
                    rate_limited: bool = False, timed_out: bool = False,
                    file: str | None = None, usage: dict | None = None) -> None:
        self.calls.append(CallRecord(agent, step, round(sec, 1), exit_code,
                                     rate_limited=rate_limited, timed_out=timed_out, file=file, usage=usage))

    def usage_totals(self) -> dict[str, dict]:
        """에이전트별 사용량 합계."""
        from duet.usage import add_usage

        out: dict[str, dict] = {}
        for c in self.calls:
            if c.usage:
                add_usage(out.setdefault(c.agent, {}), c.usage)
        return out

    @property
    def finished(self) -> bool:
        return self.status in FINAL_STATUSES

    @property
    def resumable(self) -> bool:
        """그대로 이어갈 수 있는 상태. done_unapproved 는 max_review 를 늘리면 이어갈 수 있다(Orchestrator 가 판단)."""
        return self.status in (RUNNING, STOPPED_RATE_LIMIT, STOPPED_USER, FAILED)

    # ---------------------------------------------------------------- io
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunState":
        data = dict(data)
        data["calls"] = [CallRecord(**c) for c in data.get("calls", [])]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, run_dir: Path) -> Path:
        self.updated_at = dt.datetime.now().isoformat(timespec="seconds")
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / RUN_JSON
        tmp = run_dir / (RUN_JSON + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, run_dir: Path) -> "RunState":
        path = Path(run_dir) / RUN_JSON
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


# -------------------------------------------------------------------- run dirs
def runs_root(workdir: Path) -> Path:
    return Path(workdir) / DUET_DIR / RUNS_DIR


def new_run_id(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")


def create_run_dir(workdir: Path, run_id: str | None = None) -> Path:
    root = runs_root(workdir)
    root.mkdir(parents=True, exist_ok=True)
    rid = run_id or new_run_id()
    path = root / rid
    # 같은 초에 두 번 만들면 접미사
    n = 1
    while path.exists():
        n += 1
        path = root / f"{rid}-{n}"
    path.mkdir()
    return path


def list_run_dirs(workdir: Path) -> list[Path]:
    root = runs_root(workdir)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / RUN_JSON).is_file())


def latest_run_dir(workdir: Path) -> Path | None:
    dirs = list_run_dirs(workdir)
    return dirs[-1] if dirs else None
