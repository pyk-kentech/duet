import json
import subprocess
import sys


def run(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "stock", "--db", str(tmp_path / "s.json"), *args],
                          capture_output=True, text=True)


def test_add_receive_list_value(tmp_path):
    assert run(tmp_path, "add", "A-1", "Apple", "--cost", "0.50").returncode == 0
    assert run(tmp_path, "receive", "A-1", "4").returncode == 0
    r = run(tmp_path, "list")
    assert r.stdout.splitlines() == ["A-1\tApple\t4"]
    assert run(tmp_path, "value").stdout.strip() == "TOTAL\t2.00"
    data = json.loads((tmp_path / "s.json").read_text())
    assert data["version"] == 1


def test_error_exit_code(tmp_path):
    r = run(tmp_path, "ship", "NOPE", "1")
    assert r.returncode == 1 and "오류" in r.stderr
