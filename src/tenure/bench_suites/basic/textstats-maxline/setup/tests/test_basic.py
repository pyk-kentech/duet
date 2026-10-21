import subprocess
import sys

from textstats import count


def test_count_basic():
    c = count(b"one two\nthree\n")
    assert (c.lines, c.words, c.chars, c.bytes) == (2, 3, 14, 14)


def test_count_utf8():
    c = count("한글\n".encode())
    assert (c.chars, c.bytes) == (3, 7)


def test_cli_stdin():
    r = subprocess.run([sys.executable, "-m", "textstats"], input=b"a b\n", capture_output=True)
    assert r.returncode == 0 and r.stdout.decode().strip() == "1 2 4"
