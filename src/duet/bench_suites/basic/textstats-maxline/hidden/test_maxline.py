import subprocess
import sys

import pytest

from textstats import count


@pytest.mark.parametrize("data,want", [
    (b"", 0),
    (b"abc", 3),
    (b"ab\nabcd\n", 4),
    (b"abcd\nab", 4),
    (b"\n\n", 0),
    (b"a\tb\r\n", 4),
    ("한글\n".encode(), 2),
    (b"x\n" + b"y" * 50 + b"\nz", 50),
    (b"\xff\xfe\n", 2),
])
def test_max_line_length(data, want):
    assert count(data).max_line_length == want


def test_add_keeps_other_fields():
    c = count(b"one two\nthree\n")
    assert (c.lines, c.words, c.chars, c.bytes, c.max_line_length) == (2, 3, 14, 14, 7)


def run(args, stdin=b"", cwd=None):
    return subprocess.run([sys.executable, "-m", "textstats", *args], input=stdin, capture_output=True,
                          cwd=cwd, timeout=30)


def out(r):
    return r.stdout.decode().splitlines()


def test_cli_short_and_long():
    assert out(run(["-L"], b"ab\nabcd\n")) == ["4"]
    assert out(run(["--max-line-length"], b"ab\nabcd\n")) == ["4"]


def test_cli_column_order():
    assert out(run(["-L", "-l"], b"ab\nabcd\n")) == ["2 4"]
    assert out(run(["-L", "-c", "-m", "-w", "-l"], b"ab\nabcd\n")) == ["2 2 8 8 4"]


def test_default_unchanged():
    assert out(run([], b"ab\nabcd\n")) == ["2 2 8"]


def test_total_is_max(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"abcdef\n")
    (tmp_path / "b.txt").write_bytes(b"ab\nabc\n")
    r = run(["-lL", "a.txt", "b.txt"], cwd=tmp_path)
    assert r.returncode == 0
    assert out(r) == ["1 6 a.txt", "2 3 b.txt", "3 6 total"]
