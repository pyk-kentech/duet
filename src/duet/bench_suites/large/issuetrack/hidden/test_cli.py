import json
import subprocess
import sys


def cli(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "issuetrack", "--file", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, timeout=30, cwd=tmp_path)


def test_new_show_list(tmp_path):
    r = cli(tmp_path, "new", "Fix login", "--priority", "1", "--label", "bug", "--label", "UI", "--assignee", "kim",
            "--due", "2026-05-09")
    assert r.returncode == 0 and r.stdout.strip() == "1"
    assert cli(tmp_path, "new", "Docs").stdout.strip() == "2"
    show = cli(tmp_path, "show", "1").stdout.splitlines()
    assert show == ["id: 1", "title: Fix login", "status: open", "priority: 1", "labels: bug,ui", "assignee: kim",
                    "due: 2026-05-09"]
    assert cli(tmp_path, "show", "2").stdout.splitlines()[4:] == ["labels: -", "assignee: -", "due: -"]
    assert cli(tmp_path, "list").stdout.splitlines() == ["1\topen\tP1\tFix login", "2\topen\tP3\tDocs"]
    assert cli(tmp_path, "list", "label:bug").stdout.splitlines() == ["1\topen\tP1\tFix login"]
    assert cli(tmp_path, "list", "label:docs", "OR", "docs").stdout.splitlines() == ["2\topen\tP3\tDocs"]


def test_move_assign_label_delete_summary(tmp_path):
    cli(tmp_path, "new", "a")
    cli(tmp_path, "new", "b")
    assert cli(tmp_path, "assign", "1", "lee").returncode == 0
    assert cli(tmp_path, "move", "1", "doing").returncode == 0
    assert cli(tmp_path, "label", "2", "+x", "+y", "-y").returncode == 0
    assert "labels: x" in cli(tmp_path, "show", "2").stdout
    assert cli(tmp_path, "assign", "1", "-").returncode == 0
    assert "assignee: -" in cli(tmp_path, "show", "1").stdout
    assert cli(tmp_path, "delete", "2").returncode == 0
    assert cli(tmp_path, "summary").stdout.splitlines() == ["open\t0", "doing\t1", "review\t0", "done\t0", "closed\t0"]
    assert cli(tmp_path, "new", "c").stdout.strip() == "3"


def test_errors_leave_file_unchanged(tmp_path):
    cli(tmp_path, "new", "a")
    before = (tmp_path / "i.json").read_text(encoding="utf-8")
    for args in (["move", "1", "doing"], ["show", "9"], ["new", "  "], ["new", "x", "--due", "2026-02-30"],
                 ["list", "foo:bar"], ["move", "1", "blocked"], ["new", "x", "--priority", "7"]):
        r = cli(tmp_path, *args)
        assert r.returncode == 1 and r.stderr.startswith("오류:"), (args, r.stderr)
    assert (tmp_path / "i.json").read_text(encoding="utf-8") == before


def test_read_commands_do_not_create_file(tmp_path):
    assert cli(tmp_path, "list").returncode == 0
    assert cli(tmp_path, "summary").returncode == 0
    assert not (tmp_path / "i.json").exists()


def test_export_import(tmp_path):
    cli(tmp_path, "new", "one", "--label", "x")
    cli(tmp_path, "new", "two")
    r = cli(tmp_path, "export")
    assert r.stdout.splitlines()[0] == "id,title,status,priority,labels,assignee,due"
    out = tmp_path / "out.csv"
    assert cli(tmp_path, "export", str(out)).returncode == 0
    other = tmp_path / "other"
    other.mkdir()
    r = subprocess.run([sys.executable, "-m", "issuetrack", "--file", str(other / "j.json"), "import", str(out)],
                       capture_output=True, text=True, timeout=30, cwd=tmp_path)
    assert r.returncode == 0 and r.stdout.strip() == "imported 2"
    data = json.loads((other / "j.json").read_text(encoding="utf-8"))
    assert data["version"] == 2


def test_default_file_in_cwd(tmp_path):
    r = subprocess.run([sys.executable, "-m", "issuetrack", "new", "here"], capture_output=True, text=True,
                       timeout=30, cwd=tmp_path)
    assert r.returncode == 0 and (tmp_path / "issues.json").is_file()
