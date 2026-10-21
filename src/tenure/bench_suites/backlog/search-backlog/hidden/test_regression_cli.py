"""기존 동작 (README "CLI" 절)."""

import json
import os
import subprocess
import sys


def cli(tmp_path, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "findex", "--index", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(tmp_path))


def seed(tmp_path):
    cli(tmp_path, "add", "Apple pie", "--body", "sweet apples baked", "--tag", "food", "--date", "2024-01-02")
    cli(tmp_path, "add", "Apple tree", "--body", "growing apples", "--tag", "garden")
    cli(tmp_path, "add", "Banana", "--body", "yellow fruit", "--tag", "food")


def test_search_output_format(tmp_path):
    seed(tmp_path)
    lines = cli(tmp_path, "search", "apple", "--per-page", "1", "--page", "2").stdout.splitlines()
    assert lines[0] == "검색 결과 2건" and len(lines) == 2
    doc_id, score, title = lines[1].split("\t")
    # the shorter body ranks first, so page 2 holds document 1
    assert doc_id == "1" and title == "Apple pie" and len(score.split(".")[1]) == 4
    lines = cli(tmp_path, "search", "apple", "--snippets").stdout.splitlines()
    assert lines[2] == "    growing [apples]" and lines[4] == "    sweet [apples] baked"


def test_errors_exit_1_and_leave_file(tmp_path):
    seed(tmp_path)
    before = (tmp_path / "i.json").read_bytes()
    for args in (["delete", "9"], ["search", '"open'], ["update", "1", "--title", " "], ["add", "x", "--date", "2024-13-01"]):
        r = cli(tmp_path, *args)
        assert r.returncode == 1 and r.stderr.startswith("오류:"), args
    assert (tmp_path / "i.json").read_bytes() == before


def test_import_all_or_nothing(tmp_path):
    seed(tmp_path)
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"title": "ok"}\n{"title": ""}\n', encoding="utf-8")
    r = cli(tmp_path, "import", str(bad))
    assert r.returncode == 1 and r.stderr.startswith("오류:")
    assert cli(tmp_path, "stats").stdout.splitlines()[0] == "documents\t3"
    good = tmp_path / "good.jsonl"
    good.write_text('{"title": "x"}\n\n{"title": "y", "tags": ["t"]}\n', encoding="utf-8")
    assert cli(tmp_path, "import", str(good)).stdout.split() == ["4", "5"]


def test_get_facets_suggest_stats(tmp_path):
    seed(tmp_path)
    assert cli(tmp_path, "get", "2").stdout == "id: 2\ntitle: Apple tree\ntags: garden\ndate: -\n\ngrowing apples\n"
    assert cli(tmp_path, "facets").stdout.splitlines() == ["food\t2", "garden\t1"]
    assert cli(tmp_path, "facets", "apple", "--limit", "1").stdout.splitlines() == ["food\t1"]
    assert cli(tmp_path, "suggest", "app").stdout.splitlines() == ["apple\t2"]
    assert cli(tmp_path, "suggest", "gro").stdout.splitlines() == ["grow\t1"]
    cli(tmp_path, "delete", "3")
    assert cli(tmp_path, "stats").stdout.splitlines() == ["documents\t2", "terms\t6", "next_id\t4"]


def test_update_and_export(tmp_path):
    seed(tmp_path)
    assert cli(tmp_path, "update", "3", "--title", "Ripe banana", "--clear-tags").returncode == 0
    assert cli(tmp_path, "get", "3").stdout.splitlines()[1:3] == ["title: Ripe banana", "tags: -"]
    r = cli(tmp_path, "export", str(tmp_path / "out.jsonl"))
    assert r.stdout.strip() == "내보냄: 3"
    rows = [json.loads(line) for line in (tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[2] == {"id": 3, "title": "Ripe banana", "body": "yellow fruit", "tags": [], "date": None}


def test_check_command(tmp_path):
    seed(tmp_path)
    cli(tmp_path, "add", "Well-known café", "--body", "e-mail me", "--tag", "Café")
    cli(tmp_path, "delete", "2")
    r = cli(tmp_path, "check")
    assert r.returncode == 0 and r.stdout.splitlines() == ["OK"]


def test_sort_and_json(tmp_path):
    seed(tmp_path)
    lines = cli(tmp_path, "search", "apple", "--sort", "date").stdout.splitlines()
    assert [line.split("\t")[0] for line in lines[1:]] == ["1", "2"]
    data = json.loads(cli(tmp_path, "search", "food OR fruit", "--json").stdout)
    assert data["total"] == 1 and data["page"] == 1 and data["per_page"] == 10
    assert data["hits"][0]["id"] == 3 and data["hits"][0]["title"] == "Banana"
