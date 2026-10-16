import subprocess
import sys

import pytest

from textstats import count


@pytest.mark.parametrize("data,lines,words,chars,nbytes", [
    (b"", 0, 0, 0, 0),
    (b"hello", 0, 1, 5, 5),
    (b"hello\n", 1, 1, 6, 6),
    (b"one two\nthree\n", 2, 3, 14, 14),
    (b"  lead and   trail  \n", 1, 3, 21, 21),
    (b"a\tb\rc\x0bd\x0ce\n", 1, 5, 10, 10),
    (b"\n\n\n", 3, 0, 3, 3),
    ("한글 단어\n".encode(), 1, 2, 6, 14),
    (b"bad \xff\xfe bytes", 0, 3, 12, 12),
    (b"no newline at end", 0, 4, 17, 17),
])
def test_count(data, lines, words, chars, nbytes):
    c = count(data)
    assert (c.lines, c.words, c.chars, c.bytes) == (lines, words, chars, nbytes)


def run(args, stdin=b"", cwd=None):
    return subprocess.run([sys.executable, "-m", "textstats", *args], input=stdin, capture_output=True,
                          cwd=cwd, timeout=30)


def out(r):
    return r.stdout.decode().splitlines()


def test_stdin_default_columns():
    r = run([], b"one two\nthree\n")
    assert r.returncode == 0 and out(r) == ["2 3 14"]


def test_stdin_dash_and_all_options_fixed_order():
    r = run(["-c", "-m", "-w", "-l", "-"], "가 나\n".encode())
    assert out(r) == ["1 2 4 8"]
    r = run(["-wl"], b"a b\n")
    assert out(r) == ["1 2"]


def test_files_and_total(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x y\n")
    (tmp_path / "b.txt").write_bytes(b"1\n2\n3")
    r = run(["a.txt", "b.txt"], cwd=tmp_path)
    assert r.returncode == 0
    assert out(r) == ["1 2 4 a.txt", "2 3 5 b.txt", "3 5 9 total"]


def test_single_file_no_total(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x\n")
    r = run(["-l", "a.txt"], cwd=tmp_path)
    assert out(r) == ["1 a.txt"]


def test_missing_file(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x y\n")
    r = run(["-w", "a.txt", "nope.txt"], cwd=tmp_path)
    assert r.returncode == 1
    assert out(r) == ["2 a.txt", "2 total"]
    err = r.stderr.decode()
    assert "textstats: nope.txt:" in err


def test_bad_option():
    r = run(["--bogus"])
    assert r.returncode == 2
