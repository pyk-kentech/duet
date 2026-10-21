import json
import os
import subprocess
import sys

NOW = "2026-10-19T09:00"


def run(tmp_path, *args, now=NOW):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "booking", "--db", str(tmp_path / "b.json"), "--now", now, *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def setup_space(tmp_path):
    assert run(tmp_path, "resource-add", "room-a", "Room A", "--capacity", "6").returncode == 0
    assert run(tmp_path, "member-add", "alice", "Alice").returncode == 0


def test_resources_and_members(tmp_path):
    setup_space(tmp_path)
    assert run(tmp_path, "resources").stdout.splitlines() == ["room-a\troom\t6\t4\t0\tmon-fri 08:00-20:00"]
    assert run(tmp_path, "members").stdout.splitlines() == ["alice\tAlice\tbasic"]


def test_book_and_list(tmp_path):
    setup_space(tmp_path)
    r = run(tmp_path, "book", "room-a", "alice", "2026-10-20T10:00", "2026-10-20T11:30")
    assert r.returncode == 0 and r.stdout.strip() == "1\t2026-10-20T10:00\t2026-10-20T11:30\t6"
    lines = run(tmp_path, "list").stdout.splitlines()
    assert lines == ["1\troom-a\talice\t2026-10-20T10:00\t2026-10-20T11:30\tactive\t6"]
    assert run(tmp_path, "balance", "alice").stdout.strip() == "alice\t2026-10\t40\t6\t34"


def test_cancel(tmp_path):
    setup_space(tmp_path)
    run(tmp_path, "book", "room-a", "alice", "2026-10-21T10:00", "2026-10-21T11:00")
    r = run(tmp_path, "cancel", "1")
    assert r.stdout.strip() == "1\t0\t4"


def test_error_leaves_file(tmp_path):
    setup_space(tmp_path)
    before = (tmp_path / "b.json").read_text(encoding="utf-8")
    r = run(tmp_path, "book", "room-a", "alice", "2026-10-20T07:00", "2026-10-20T09:00")
    assert r.returncode == 1 and r.stderr.startswith("오류:")
    assert (tmp_path / "b.json").read_text(encoding="utf-8") == before

