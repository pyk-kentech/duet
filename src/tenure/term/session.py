"""대화형 터미널 세션과 관리자 (DESIGN.md 36.19).

UI 서버 프로세스가 세션을 가진다. 세션마다 `$TENURE_HOME/sessions/<id>/` 에 meta.json·output.log·hooks.jsonl.
상태는 훅 → 화면 규칙 → 출력 여부 순으로 정한다. 프로세스가 끝나면 ended.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sys
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tenure.procs import replace_file
from tenure.runner import ExecutableNotFound, PtyProcessHandle, spawn_pty
from tenure.term import hooks, rules

SESSIONS_DIR = "sessions"
AGENTS = ("claude", "codex", "shell")   # shell: 작업공간의 보통 터미널 (훅 없음, 36.22)
MAX_BUFFER = 1_000_000            # 메모리에 두는 출력 (넘으면 앞을 버림)
MAX_LOG = 2_000_000               # output.log 상한 (넘으면 뒤쪽 절반만 남김)
MAX_LIVE = 8                      # 동시에 열 수 있는 세션
HOOK_TRUST_SEC = 120              # 훅이 이만큼 조용하면 화면 규칙을 본다 (Orca)
OUTPUT_RECENT_SEC = 3.0
PASTE_ENTER_DELAY = 0.15
BRACKETED_ON = "\x1b[?2004h"
BRACKETED_OFF = "\x1b[?2004l"
SESSION_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class SessionError(Exception):
    pass


def default_shell() -> list[str]:
    """작업공간 터미널에 띄울 셸: Windows 는 PowerShell 7(pwsh) → Windows PowerShell, 그 밖은 $SHELL."""
    if sys.platform == "win32":
        return [shutil.which("pwsh") or "powershell.exe", "-NoLogo"]
    return [os.environ.get("SHELL") or "/bin/bash", "-l"]


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


@dataclass
class Meta:
    id: str
    agent: str
    cwd: str
    project: str
    run_id: str | None = None
    created: str = field(default_factory=_now)
    ended: str | None = None
    returncode: int | None = None
    rows: int = 30
    cols: int = 120
    seen_at: str | None = None
    title: str = ""


class Session:
    def __init__(self, meta: Meta, folder: Path, rule_list: list[rules.Rule], nonce: str):
        self.meta, self.dir, self.rules, self.nonce = meta, folder, rule_list, nonce
        self.handle: PtyProcessHandle | None = None
        self._lock = threading.Lock()
        self.text = ""
        self.dropped = 0
        self.last_output = 0.0
        self.bracketed = False
        self.hook_offset = 0
        self.hook_last: dict[str, Any] | None = None       # 마지막 훅 기록 (+ 해석)
        self.override: tuple[float, str, str, int] | None = None   # 화면에서 승인·보내기 직후 (시각, 상태, 이유, 출력 위치)
        self.last_turn_end: str | None = None
        self._reader: threading.Thread | None = None

    # ---------------------------------------------------------------- lifecycle
    def start(self, argv: list[str], env: dict[str, str]) -> None:
        self.handle = spawn_pty(argv, Path(self.meta.cwd), env, rows=self.meta.rows, cols=self.meta.cols)
        self._reader = threading.Thread(target=self._read_loop, name=f"term-{self.meta.id}", daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        assert self.handle is not None
        log = (self.dir / "output.log").open("a", encoding="utf-8", newline="")
        try:
            while True:
                chunk = self.handle.read()
                if not chunk:
                    if self.handle.alive():
                        time.sleep(0.05)
                        continue
                    break
                self._append(chunk)
                log.write(chunk)
                log.flush()
        finally:
            log.close()
            for _ in range(40):                   # ConPTY 는 출력을 다 준 뒤 종료 코드가 늦게 잡히기도 한다
                if self.handle.exit_code() is not None:
                    break
                time.sleep(0.05)
            self.meta.returncode = self.handle.exit_code()
            self.meta.ended = _now()
            self.handle.close()
            self.save_meta()
            _trim_log(self.dir / "output.log")

    def _append(self, s: str) -> None:
        with self._lock:
            if BRACKETED_ON in s:
                self.bracketed = True
            if BRACKETED_OFF in s:
                self.bracketed = s.rfind(BRACKETED_ON) > s.rfind(BRACKETED_OFF)
            self.text += s
            if len(self.text) > MAX_BUFFER:
                cut = len(self.text) - MAX_BUFFER
                self.text = self.text[cut:]
                self.dropped += cut
            self.last_output = time.monotonic()

    @property
    def live(self) -> bool:
        # ConPTY 는 프로세스가 끝나도 읽기가 몇 초 늦게 끝난다. 끝남은 프로세스로 판단하고, 남은 출력은 리더가 마저 읽는다
        return self.handle is not None and self.meta.ended is None and self.handle.alive()

    def save_meta(self) -> None:
        tmp = self.dir / "meta.json.tmp"
        tmp.write_text(json.dumps({**asdict(self.meta), "nonce": self.nonce}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        replace_file(tmp, self.dir / "meta.json")

    # ---------------------------------------------------------------- input
    def write(self, data: str) -> None:
        if not self.live:
            raise SessionError("이미 끝난 세션입니다.")
        assert self.handle is not None
        self.handle.write(data)

    def send(self, text: str, *, force: bool = False) -> None:
        """메시지 보내기: bracketed paste 뒤 잠깐 쉬고 Enter. 승인 대기면 거부(force 면 보냄)."""
        st = self.status()
        if st["state"] == "blocked" and not force:
            raise SessionError("에이전트가 승인을 기다리는 중이라 보내지 않았습니다. 먼저 승인·거절하거나 강제로 보내세요.")
        body = text.replace("\r\n", "\n")
        self.write(f"\x1b[200~{body}\x1b[201~" if self.bracketed else body)
        time.sleep(PASTE_ENTER_DELAY)
        self.write("\r")
        self.override = (time.monotonic(), "working", "메시지를 보냄", self._pos())

    def answer(self, approve: bool) -> str:
        """승인·거절 키를 보낸다. 맞은 규칙의 키, 없으면 에이전트 기본값."""
        st = self.status()
        rule = next((r for r in self.rules if r.id == st.get("rule")), None)
        if rule is None or rule.state != "blocked":
            rule = next((r for r in self.rules if r.state == "blocked" and r.agent == self.meta.agent), None)
        keys = (rule.approve if approve else rule.deny) if rule else ("\r" if approve else "\x1b")
        if not keys:
            raise SessionError("이 규칙에는 승인·거절 키가 없습니다. 터미널에서 직접 답하세요.")
        self.write(keys)
        self.override = (time.monotonic(), "working" if approve else "idle", "승인함" if approve else "거절함", self._pos())
        return keys

    def resize(self, rows: int, cols: int) -> None:
        self.meta.rows, self.meta.cols = rows, cols
        if self.live and self.handle is not None:
            self.handle.resize(rows, cols)

    def kill(self) -> None:
        if self.live and self.handle is not None:
            self.handle.kill()

    # ---------------------------------------------------------------- state
    def _pos(self) -> int:
        with self._lock:
            return self.dropped + len(self.text)

    def _since(self, pos: int | None) -> str:
        """출력 위치 pos 뒤의 끝부분 (그보다 앞에 그려진 질문은 이미 지나간 것)."""
        with self._lock:
            start = len(self.text) - rules.TAIL_CHARS if pos is None else pos - self.dropped
            return self.text[max(0, start):]

    def _poll_hooks(self) -> None:
        evs, self.hook_offset = hooks.read_new(self.dir, self.hook_offset, self.nonce)
        for ev in evs:
            state, reason = hooks.interpret(ev)
            self.hook_last = {**ev, "state": state, "reason": reason, "mono": time.monotonic(), "pos": self._pos()}
            if ev.get("event") in ("Stop", hooks.CODEX_EVENT):
                self.last_turn_end = ev.get("ts")
            self.override = None                 # 훅이 새로 오면 화면에서 한 일보다 우선

    def status(self) -> dict[str, Any]:
        """{state, reason, source, rule, attention}. state: working | blocked | idle | ended."""
        self._poll_hooks()
        if not self.live:
            rc = self.meta.returncode if self.meta.returncode is not None else (self.handle.exit_code() if self.handle else None)
            return {"state": "ended", "reason": f"끝남 (종료 코드 {rc})" if rc not in (None, 0) else "끝남",
                    "source": "process", "rule": None, "attention": None}
        now = time.monotonic()
        with self._lock:
            last_out = self.last_output
        h = self.hook_last
        ov = self.override if self.override and (not h or self.override[0] >= h["mono"]) else None
        # 화면 규칙은 마지막 사건(훅·승인·보내기) 뒤의 출력만 본다(그 전에 그려진 질문은 이미 지나감)
        marks = [x for x in (ov[3] if ov else None, h["pos"] if h and h["state"] != "blocked" else None) if x is not None]
        hit = rules.match(self.rules, self.meta.agent, self._since(max(marks) if marks else None))
        self._last_hit = hit                     # '왜 이 상태?'가 상태 판단에 쓴 규칙만 보이게
        screen = hit[0] if hit else None
        out = None
        if ov and now - ov[0] < HOOK_TRUST_SEC:
            out = {"state": ov[1], "reason": ov[2], "source": "action", "rule": None}
            if screen and screen.state == "blocked":
                out = None                       # 승인 뒤 또 물어봄
        if out is None and h is not None:
            age = now - h["mono"]
            if h["state"] == "blocked":
                # 훅 뒤에 출력이 꽤 이어졌는데 그 안에 질문이 없으면 다시 일하는 중 (터미널에서 직접 승인한 경우)
                after = rules.clean(self._since(h["pos"]))
                asked = rules.match(self.rules, self.meta.agent, self._since(h["pos"]))
                if len(after.strip()) > 200 and not (asked and asked[0].state == "blocked"):
                    out = {"state": "working", "reason": "승인 뒤 계속", "source": "hook+screen", "rule": None}
                else:
                    out = {"state": "blocked", "reason": h["reason"], "source": "hook", "rule": screen.id if screen else None}
            elif h["state"] == "idle" or age < HOOK_TRUST_SEC:
                if h["state"] == "idle" and screen and screen.state == "blocked":
                    out = None                   # 턴 끝 뒤에 뜬 질문은 화면이 안다
                else:
                    out = {"state": h["state"], "reason": h["reason"], "source": "hook", "rule": None}
        if out is None and screen is not None:
            out = {"state": screen.state, "reason": f"화면 규칙 {screen.id}", "source": "screen", "rule": screen.id}
        if out is None:
            recent = last_out and now - last_out < OUTPUT_RECENT_SEC
            out = {"state": "working" if recent else "idle", "reason": "출력 중" if recent else "조용함",
                   "source": "output", "rule": None}
        attention = None
        if out["state"] == "blocked":
            attention = "blocked"
        elif out["state"] == "idle" and self.last_turn_end and (not self.meta.seen_at or self.last_turn_end > self.meta.seen_at):
            attention = "done-unseen"
        return {**out, "attention": attention}

    def explain(self) -> dict[str, Any]:
        st = self.status()
        with self._lock:
            tail = self.text[-rules.TAIL_CHARS:]
        hit = getattr(self, "_last_hit", None) if st["state"] != "ended" else rules.match(self.rules, self.meta.agent, tail)
        return {"status": st, "rule": ({"id": hit[0].id, "state": hit[0].state, "regex": hit[0].regex, "source": hit[0].source,
                                        "region": hit[1]} if hit else None),
                "hook": ({k: self.hook_last.get(k) for k in ("ts", "event", "state", "reason", "data")} if self.hook_last else None),
                "tail": rules.tail_lines(tail, 15), "rules": [r.id for r in self.rules if r.agent in ("*", self.meta.agent)]}

    def snapshot(self, offset: int = 0) -> dict[str, Any]:
        with self._lock:
            start = max(0, offset - self.dropped)
            chunk = self.text[start:]
            end = self.dropped + len(self.text)
        return {**self.summary(), "data": chunk, "offset": end, "reset": offset < self.dropped}

    def summary(self) -> dict[str, Any]:
        return {**asdict(self.meta), "live": self.live, "status": self.status()}


def _trim_log(path: Path) -> None:
    try:
        if path.stat().st_size <= MAX_LOG:
            return
        data = path.read_bytes()[-MAX_LOG // 2:]
        cut = data.find(b"\n")
        path.write_bytes(data[cut + 1:] if 0 <= cut < 4096 else data)
    except OSError:
        pass


class SessionManager:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.root = self.home / SESSIONS_DIR
        self._lock = threading.Lock()
        self.sessions: dict[str, Session] = {}
        self._load_past()

    def _rules(self) -> list[rules.Rule]:
        try:
            return rules.load_rules(self.home)
        except rules.RuleError:
            return rules.load_rules(None)

    def _load_past(self) -> None:
        """서버를 다시 켜면 지난 세션은 끝난 세션으로 보인다(출력 기록으로)."""
        if not self.root.is_dir():
            return
        for d in sorted(self.root.iterdir())[-50:]:
            try:
                data = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            nonce = data.pop("nonce", "")
            keys = set(Meta.__dataclass_fields__)
            meta = Meta(**{k: v for k, v in data.items() if k in keys})
            if meta.ended is None:
                meta.ended = meta.created              # 서버와 함께 끝남
            s = Session(meta, d, self._rules(), nonce)
            try:
                raw = (d / "output.log").read_text(encoding="utf-8", errors="replace")
                s.text, s.dropped = raw[-MAX_BUFFER:], max(0, len(raw) - MAX_BUFFER)
            except OSError:
                pass
            self.sessions[meta.id] = s

    def create(self, agent: str, cwd: Path, project: str, *, run_id: str | None = None,
               rows: int = 30, cols: int = 120, title: str = "", bin: str | None = None) -> Session:
        """bin: 띄울 실행 파일 (설정의 claude.bin·codex.bin). 없으면 에이전트 이름으로 PATH 에서 찾는다."""
        if agent not in AGENTS:
            raise SessionError(f"에이전트는 {', '.join(AGENTS)} 중 하나입니다.")
        if not Path(cwd).is_dir():
            raise SessionError(f"작업 폴더가 없습니다: {cwd}")
        with self._lock:
            shell = agent == "shell"             # 셸과 에이전트 세션은 따로 센다
            if sum(1 for s in self.sessions.values() if s.live and (s.meta.agent == "shell") == shell) >= MAX_LIVE:
                what = "터미널" if shell else "에이전트 세션"
                raise SessionError(f"{what}은 동시에 {MAX_LIVE}개까지 열 수 있습니다. 끝난 것을 닫으세요.")
            sid = secrets.token_hex(6)
            folder = self.root / sid
            folder.mkdir(parents=True)
            nonce = secrets.token_hex(8)
            meta = Meta(id=sid, agent=agent, cwd=str(cwd), project=project, run_id=run_id,
                        rows=max(5, min(rows, 300)), cols=max(20, min(cols, 500)), title=title)
            s = Session(meta, folder, self._rules(), nonce)
            s.save_meta()
            self.sessions[sid] = s
        env = {"TENURE_SESSION": sid}
        exe = bin or agent
        if agent == "shell":
            argv = default_shell()
        elif agent == "claude":
            argv = [exe, "--settings", hooks.claude_settings(folder, nonce)]
        else:
            argv = [exe, *hooks.codex_args(folder, nonce)]
            chain = hooks.user_codex_notify()
            if chain:                            # 사용자의 원래 notify 를 우리 훅이 이어서 부른다
                env[hooks.CHAIN_ENV] = json.dumps(chain, ensure_ascii=False)
        try:
            s.start(argv, env)
        except (ExecutableNotFound, OSError) as e:
            s.meta.ended, s.meta.returncode = _now(), -1
            s.save_meta()
            raise SessionError(f"{agent} 를 띄우지 못했습니다: {e}") from e
        return s

    def get(self, sid: Any) -> Session:
        s = self.sessions.get(str(sid)) if isinstance(sid, str) and SESSION_ID_RE.match(sid) else None
        if s is None:
            raise SessionError("세션을 찾을 수 없습니다.")
        return s

    def list(self) -> list[dict[str, Any]]:
        items = [s.summary() for s in self.sessions.values()]
        return sorted(items, key=lambda x: (not x["live"], x["created"]), reverse=False)[::1]

    def mark_seen(self, sid: Any) -> None:
        s = self.get(sid)
        s.meta.seen_at = dt.datetime.now().isoformat(timespec="milliseconds")
        s.save_meta()

    def close(self, sid: Any) -> None:
        """끝난 세션을 목록에서 지운다(기록 폴더는 남김)."""
        s = self.get(sid)
        if s.live:
            raise SessionError("진행 중인 세션은 먼저 끝내세요.")
        with self._lock:
            self.sessions.pop(s.meta.id, None)

    def shutdown(self) -> None:
        for s in list(self.sessions.values()):
            s.kill()
