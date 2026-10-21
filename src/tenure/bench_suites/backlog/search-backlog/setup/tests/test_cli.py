import json
import os
import subprocess
import sys


def run(tmp_path, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "findex", "--index", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def test_add_and_search(tmp_path):
    assert run(tmp_path, "add", "Apple pie", "--body", "sweet apples", "--tag", "food").stdout.strip() == "1"
    assert run(tmp_path, "add", "Banana", "--body", "yellow").stdout.strip() == "2"
    r = run(tmp_path, "search", "apple")
    lines = r.stdout.splitlines()
    assert r.returncode == 0 and lines[0] == "검색 결과 1건"
    doc_id, score, title = lines[1].split("\t")
    assert doc_id == "1" and title == "Apple pie" and len(score.split(".")[1]) == 4


def test_search_no_results_on_missing_file(tmp_path):
    r = run(tmp_path, "search", "anything")
    assert r.returncode == 0 and r.stdout.splitlines() == ["검색 결과 0건"]
    assert not (tmp_path / "i.json").exists()


def test_get(tmp_path):
    run(tmp_path, "add", "Title", "--body", "Body text", "--tag", "a", "--tag", "b", "--date", "2024-01-02")
    assert run(tmp_path, "get", "1").stdout == "id: 1\ntitle: Title\ntags: a, b\ndate: 2024-01-02\n\nBody text\n"


def test_errors(tmp_path):
    r = run(tmp_path, "delete", "7")
    assert r.returncode == 1 and r.stderr.startswith("오류:")
    r = run(tmp_path, "add", "x", "--date", "2024-13-01")
    assert r.returncode == 1 and "오류" in r.stderr
    assert not (tmp_path / "i.json").exists()


def test_import_and_facets(tmp_path):
    src = tmp_path / "docs.jsonl"
    src.write_text("\n".join(json.dumps(d) for d in [
        {"title": "One", "tags": ["x", "y"]}, {"title": "Two", "tags": ["x"]}]) + "\n", encoding="utf-8")
    assert run(tmp_path, "import", str(src)).stdout.split() == ["1", "2"]
    assert run(tmp_path, "facets").stdout.splitlines() == ["x\t2", "y\t1"]


def test_stats(tmp_path):
    run(tmp_path, "add", "hello world")
    assert run(tmp_path, "stats").stdout.splitlines() == ["documents\t1", "terms\t2", "next_id\t2"]


def test_correct_and_info(tmp_path):
    run(tmp_path, "add", "Python programming")
    assert run(tmp_path, "correct", "pyhton").stdout.strip() == "python"
    assert run(tmp_path, "correct", "python").stdout == ""
    assert run(tmp_path, "info").stdout.splitlines() == ["stopwords\tdefault", "stem\tyes", "boosts\ttitle=2 body=1"]


def test_check_and_parse(tmp_path):
    run(tmp_path, "add", "hello world")
    r = run(tmp_path, "check")
    assert r.returncode == 0 and r.stdout.strip() == "OK"
    assert run(tmp_path, "parse", "a OR b").stdout.strip() == "(a OR b)"
