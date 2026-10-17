import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

STATUSES = ("open", "doing", "review", "done", "closed")
TRANSITIONS = {
    "open": frozenset({"doing", "closed"}),
    "doing": frozenset({"open", "review"}),
    "review": frozenset({"doing", "done"}),
    "done": frozenset({"doing", "closed"}),
    "closed": frozenset({"open"}),
}
FINISHED = frozenset({"done", "closed"})
LABEL_RE = re.compile(r"^[a-z0-9-]{1,20}$")


@dataclass
class Issue:
    id: int
    title: str
    status: str
    priority: int
    labels: tuple
    assignee: str | None
    due: date | None
    created: datetime
    updated: datetime


@dataclass
class Event:
    at: datetime
    issue_id: int
    field: str
    old: Any
    new: Any


def check_title(title):
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= 120):
        raise ValueError(f"제목은 1~120자여야 합니다: {title!r}")
    return title.strip()


def check_priority(priority):
    if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 4:
        raise ValueError(f"우선순위는 1~4 정수: {priority!r}")
    return priority


def check_labels(labels):
    if isinstance(labels, str):
        labels = [labels]
    out = set()
    for raw in labels:
        if not isinstance(raw, str):
            raise ValueError(f"라벨 형식 오류: {raw!r}")
        lab = raw.lower()
        if not LABEL_RE.match(lab):
            raise ValueError(f"라벨 형식 오류: {raw!r}")
        out.add(lab)
    return tuple(sorted(out))


def check_assignee(assignee):
    if assignee is None:
        return None
    if not isinstance(assignee, str) or not assignee.strip():
        raise ValueError(f"담당자 형식 오류: {assignee!r}")
    return assignee.strip()


def check_due(due):
    if due is None:
        return None
    if isinstance(due, datetime) or not isinstance(due, date):
        raise ValueError(f"기한은 date 여야 합니다: {due!r}")
    return due


def check_status(status):
    if status not in STATUSES:
        raise ValueError(f"없는 상태: {status!r}")
    return status
