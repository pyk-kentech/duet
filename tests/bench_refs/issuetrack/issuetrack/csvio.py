import csv
from datetime import date

from issuetrack.errors import CsvFormatError
from issuetrack.models import check_assignee, check_due, check_labels, check_priority, check_status, check_title

COLUMNS = ("id", "title", "status", "priority", "labels", "assignee", "due")


def export_csv(tracker, file):
    w = csv.writer(file)
    w.writerow(COLUMNS)
    for i in tracker.issues():
        w.writerow([i.id, i.title, i.status, i.priority, ";".join(i.labels), i.assignee or "",
                    i.due.isoformat() if i.due else ""])


def _row(rec):
    get = lambda k: (rec.get(k) or "").strip()
    priority = get("priority")
    if priority and not priority.isdigit():
        raise ValueError(f"우선순위 형식 오류: {priority!r}")
    due = get("due")
    try:
        due_v = date.fromisoformat(due) if due else None
    except ValueError:
        raise ValueError(f"날짜 형식 오류: {due!r}") from None
    return {
        "title": check_title(rec.get("title") or ""),
        "status": check_status(get("status") or "open"),
        "priority": check_priority(int(priority) if priority else 3),
        "labels": check_labels([x.strip() for x in get("labels").split(";") if x.strip()]),
        "assignee": check_assignee(get("assignee") or None),
        "due": check_due(due_v),
    }


def import_csv(tracker, file):
    reader = csv.DictReader(file)
    header = reader.fieldnames
    if not header:
        raise CsvFormatError("줄 1: 헤더가 없습니다")
    unknown = [h for h in header if h not in COLUMNS]
    if unknown:
        raise CsvFormatError(f"줄 1: 모르는 열: {', '.join(unknown)}")
    if "title" not in header:
        raise CsvFormatError("줄 1: title 열이 없습니다")
    rows = []
    for rec in reader:
        line = reader.line_num
        if None in rec:
            raise CsvFormatError(f"줄 {line}: 열 수가 헤더보다 많습니다")
        try:
            rows.append(_row(rec))
        except ValueError as e:
            raise CsvFormatError(f"줄 {line}: {e}") from None
    return tracker._add_imported(rows)
