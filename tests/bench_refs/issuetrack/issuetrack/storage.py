"""JSON 저장. 버전 2 를 쓰고, 버전 1 도 읽는다."""

import json
import os
from datetime import date, datetime
from pathlib import Path

from issuetrack.errors import StorageError
from issuetrack.models import Event, Issue, check_labels, check_priority, check_status
from issuetrack.tracker import Tracker

VERSION = 2


def _enc(v):
    if isinstance(v, datetime):
        return {"dt": v.isoformat()}
    if isinstance(v, date):
        return {"date": v.isoformat()}
    if isinstance(v, tuple):
        return {"tuple": list(v)}
    return v


def _dec(v):
    if isinstance(v, dict):
        if "date" in v:
            return date.fromisoformat(v["date"])
        if "dt" in v:
            return datetime.fromisoformat(v["dt"])
        if "tuple" in v:
            return tuple(v["tuple"])
        raise ValueError(f"알 수 없는 값: {v!r}")
    return v


def save(tracker, path):
    path = Path(path)
    data = {
        "version": VERSION,
        "next_id": tracker._next_id,
        "issues": [{"id": i.id, "title": i.title, "status": i.status, "priority": i.priority,
                    "labels": list(i.labels), "assignee": i.assignee,
                    "due": i.due.isoformat() if i.due else None,
                    "created": i.created.isoformat(), "updated": i.updated.isoformat()} for i in tracker.issues()],
        "events": [{"at": e.at.isoformat(), "issue_id": e.issue_id, "field": e.field,
                    "old": _enc(e.old), "new": _enc(e.new)} for e in tracker.events()],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _due(v):
    return date.fromisoformat(v) if v else None


def _v1(data):
    issues = []
    for d in data.get("issues", []):
        created = datetime.fromisoformat(d["created"])
        labels = check_labels([x.strip() for x in str(d.get("labels") or "").split(",") if x.strip()])
        issues.append(Issue(id=int(d["id"]), title=str(d["title"]), status=check_status(d["status"]),
                            priority=check_priority(d.get("priority", 3)), labels=labels,
                            assignee=d.get("assignee"), due=_due(d.get("due")), created=created, updated=created))
    next_id = max((i.id for i in issues), default=0) + 1
    return issues, [], next_id


def _v2(data):
    issues = [Issue(id=int(d["id"]), title=str(d["title"]), status=check_status(d["status"]),
                    priority=check_priority(d["priority"]), labels=tuple(d["labels"]), assignee=d.get("assignee"),
                    due=_due(d.get("due")), created=datetime.fromisoformat(d["created"]),
                    updated=datetime.fromisoformat(d["updated"])) for d in data.get("issues", [])]
    events = [Event(at=datetime.fromisoformat(e["at"]), issue_id=int(e["issue_id"]), field=str(e["field"]),
                    old=_dec(e["old"]), new=_dec(e["new"])) for e in data.get("events", [])]
    return issues, events, int(data["next_id"])


def load(path, clock=None):
    path = Path(path)
    tracker = Tracker(clock=clock)
    if not path.exists():
        return tracker
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StorageError(f"{path} 를 읽을 수 없습니다: {e}") from e
    if not isinstance(data, dict):
        raise StorageError("형식 오류: 최상위가 객체가 아닙니다")
    version = data.get("version")
    if version not in (1, 2):
        raise StorageError(f"지원하지 않는 형식 버전: {version!r}")
    try:
        issues, events, next_id = (_v1 if version == 1 else _v2)(data)
    except (KeyError, TypeError, ValueError) as e:
        raise StorageError(f"{path} 형식 오류: {e}") from e
    tracker._restore(issues, events, next_id)
    return tracker
