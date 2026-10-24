import pytest

from tenure.verdict import Status, Verdict, parse_verdict


def test_block_approved():
    v = parse_verdict("리뷰...\n<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>\n")
    assert v == Verdict(Status.APPROVED, 0, "block")
    assert v.approved and not v.parse_failed and not v.contradiction


def test_block_changes_requested():
    v = parse_verdict("<verdict>\nstatus: CHANGES_REQUESTED\nmust_fix: 3\n</verdict>")
    assert v.status is Status.CHANGES_REQUESTED and v.must_fix == 3 and v.source == "block"


def test_block_without_must_fix():
    v = parse_verdict("<verdict>\nstatus: APPROVED\n</verdict>")
    assert v.approved and v.must_fix is None


def test_block_case_and_spacing():
    v = parse_verdict("<VERDICT>\n  Status :  approved \n  Must_Fix : 0\n</VERDICT>")
    assert v.approved


def test_contradiction():
    v = parse_verdict("<verdict>\nstatus: APPROVED\nmust_fix: 2\n</verdict>")
    assert v.status is Status.CHANGES_REQUESTED
    assert v.contradiction and v.must_fix == 2
    assert "모순" in v.describe() or "반려로 처리" in v.describe()


def test_legacy_line():
    v = parse_verdict("## 반드시 고칠 것\n(없음)\n\nVERDICT: APPROVED\n")
    assert v.approved and v.source == "legacy" and not v.parse_failed


def test_legacy_bold_markdown():
    assert parse_verdict("**VERDICT: CHANGES_REQUESTED**").status is Status.CHANGES_REQUESTED
    assert parse_verdict("VERDICT: **APPROVED**").approved


def test_legacy_last_wins():
    v = parse_verdict("VERDICT: APPROVED\n...생각해보니\nVERDICT: CHANGES_REQUESTED")
    assert v.status is Status.CHANGES_REQUESTED


def test_block_beats_legacy():
    v = parse_verdict("VERDICT: CHANGES_REQUESTED\n<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>")
    assert v.approved and v.source == "block"


def test_multiple_blocks_last_wins():
    text = ("<verdict>\nstatus: CHANGES_REQUESTED\nmust_fix: 1\n</verdict>\n"
            "수정 후\n<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>")
    assert parse_verdict(text).approved


def test_missing_is_changes_requested_with_flag():
    v = parse_verdict("리뷰만 쓰고 판정을 안 씀")
    assert v.status is Status.CHANGES_REQUESTED and v.parse_failed and v.source == "none"
    assert "판정 블록 없음" in v.describe()


@pytest.mark.parametrize("text", ["", None])
def test_empty(text):
    assert parse_verdict(text).parse_failed


def test_block_with_bad_status_falls_through():
    v = parse_verdict("<verdict>\nstatus: MAYBE\n</verdict>\nVERDICT: APPROVED")
    assert v.approved and v.source == "legacy"
