from pathlib import Path

from duet.transcript import Transcript, read_header, render_header, split_header


def test_save_numbering_and_header(tmp_path: Path):
    tr = Transcript(tmp_path / "run")
    p1 = tr.save("propose_claude", "# 설계안\n본문", {"agent": "claude", "step": "propose",
                                                   "duration_sec": 41.23, "exit_code": 0, "rate_limited": False})
    p2 = tr.save("propose codex!", "two")
    assert p1.name == "01_propose_claude.md"
    assert p2.name == "02_propose_codex.md"
    content = p1.read_text(encoding="utf-8")
    assert content.startswith("<!-- duet\n")
    meta, body = split_header(content)
    assert meta["agent"] == "claude" and meta["duration_sec"] == "41.2"
    assert meta["exit_code"] == "0" and meta["rate_limited"] == "false"
    assert "timestamp" in meta
    assert body == "# 설계안\n본문\n"


def test_entries_and_read(tmp_path: Path):
    tr = Transcript(tmp_path)
    tr.save("a", "A", {"step": "propose"})
    tr.save("b", "B", {"step": "critique"})
    (tmp_path / "run.json").write_text("{}")  # 무시돼야 함
    es = tr.entries()
    assert [e.name for e in es] == ["01_a.md", "02_b.md"]
    assert [e.meta["step"] for e in es] == ["propose", "critique"]
    assert es[0].body() == "A\n"
    assert tr.read("02_b.md") == "B\n"
    assert read_header(tmp_path / "01_a.md")["step"] == "propose"


def test_resume_continues_numbering(tmp_path: Path):
    Transcript(tmp_path).save("x", "1")
    Transcript(tmp_path).save("y", "2")
    tr = Transcript(tmp_path)
    assert tr.n == 2
    assert tr.save("z", "3").name == "03_z.md"


def test_split_header_without_header():
    assert split_header("plain text") == ({}, "plain text")
    assert split_header("<!-- duet\nno end") == ({}, "<!-- duet\nno end")


def test_render_header_escapes_newlines():
    h = render_header({"task": "줄1\n줄2"})
    assert "task: 줄1 줄2" in h
