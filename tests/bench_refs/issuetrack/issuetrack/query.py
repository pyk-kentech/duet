"""질의 언어: 그룹(OR) 안의 항(AND), 부정, 따옴표 구절, 필드 항, 정렬 항."""

import re
from dataclasses import dataclass, field
from datetime import date

from issuetrack.errors import QueryError
from issuetrack.models import FINISHED, STATUSES

FIELD_RE = re.compile(r"^([A-Za-z]+)(<=|>=|:|=|<|>)(.*)$")
OPS = {
    ":": lambda a, b: a == b, "=": lambda a, b: a == b, "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
}
SORT_KEYS = ("priority", "id", "due", "updated")


@dataclass
class Query:
    groups: list = field(default_factory=list)     # list[list[callable(issue, today) -> bool]]
    sort: tuple | None = None                       # (key, descending)

    def matches(self, issue, today):
        if not self.groups:
            return True
        return any(all(t(issue, today) for t in g) for g in self.groups)

    def order(self, issues):
        if self.sort is None:
            return sorted(issues, key=lambda i: (i.priority, i.id))
        key, desc = self.sort
        if key == "due":
            with_due = sorted((i for i in issues if i.due is not None), key=lambda i: i.id)
            with_due.sort(key=lambda i: i.due, reverse=desc)
            return with_due + sorted((i for i in issues if i.due is None), key=lambda i: i.id)
        out = sorted(issues, key=lambda i: i.id)
        out.sort(key=lambda i: getattr(i, key), reverse=desc)
        return out


def _tokens(text):
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        start = i
        neg = text[i] == "-" and i + 1 < n and text[i + 1] == '"'
        if text[i] == '"' or neg:
            q = i + (2 if neg else 1)
            end = text.find('"', q)
            if end < 0:
                raise QueryError("닫히지 않은 따옴표")
            out.append(("phrase", neg, text[q:end]))
            i = end + 1
            continue
        while i < n and not text[i].isspace():
            i += 1
        out.append(("word", False, text[start:i]))
    return out


def _parse_int(v):
    if not re.fullmatch(r"[1-4]", v):
        raise QueryError(f"우선순위 값 오류: {v!r}")
    return int(v)


def _parse_date(v):
    try:
        return date.fromisoformat(v) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None
    except ValueError:
        return None


def _field_term(name, op, value):
    if not value:
        raise QueryError(f"빈 값: {name}{op}")
    if name == "status":
        if op != ":":
            raise QueryError("status 는 ':' 만 씁니다")
        vals = value.split(",")
        if any(v not in STATUSES for v in vals):
            raise QueryError(f"없는 상태: {value!r}")
        s = set(vals)
        return lambda i, today: i.status in s
    if name == "label":
        if op != ":":
            raise QueryError("label 은 ':' 만 씁니다")
        lab = value.lower()
        return lambda i, today: lab in i.labels
    if name == "assignee":
        if op != ":":
            raise QueryError("assignee 는 ':' 만 씁니다")
        if value.lower() == "none":
            return lambda i, today: i.assignee is None
        who = value.lower()
        return lambda i, today: i.assignee is not None and i.assignee.lower() == who
    if name == "priority":
        p = _parse_int(value)
        f = OPS[op]
        return lambda i, today: f(i.priority, p)
    if name == "due":
        if op == ":" and value == "none":
            return lambda i, today: i.due is None
        d = _parse_date(value)
        if d is None:
            raise QueryError(f"날짜 형식 오류: {value!r}")
        f = OPS[op]
        return lambda i, today: i.due is not None and f(i.due, d)
    if name == "is":
        if op != ":":
            raise QueryError("is 는 ':' 만 씁니다")
        if value == "open":
            return lambda i, today: i.status not in FINISHED
        if value == "overdue":
            return lambda i, today: i.due is not None and i.due < today and i.status not in FINISHED
        raise QueryError(f"알 수 없는 is 값: {value!r}")
    raise QueryError(f"알 수 없는 필드: {name!r}")


def parse(text):
    q = Query()
    group: list = []
    groups: list = []
    pending_or = False
    tokens = _tokens(text or "")
    for kind, neg, raw in tokens:
        if kind == "word" and raw == "OR":
            if not groups and not group or pending_or:
                raise QueryError("OR 위치가 잘못되었습니다")
            groups.append(group)
            group = []
            pending_or = True
            continue
        pending_or = False
        if kind == "phrase":
            needle = raw.lower()
            term = (lambda i, today, s=needle: s in i.title.lower())
        else:
            if raw.startswith("-"):
                neg, raw = True, raw[1:]
                if not raw:
                    raise QueryError("'-' 뒤에 항이 없습니다")
            m = FIELD_RE.match(raw)
            if m and m.group(1) == "sort":
                if neg:
                    raise QueryError("정렬 항은 부정할 수 없습니다")
                if m.group(2) != ":":
                    raise QueryError("sort 는 ':' 만 씁니다")
                if q.sort is not None:
                    raise QueryError("정렬 항이 둘 이상입니다")
                v = m.group(3)
                desc = v.startswith("-")
                key = v[1:] if desc else v
                if key not in SORT_KEYS:
                    raise QueryError(f"알 수 없는 정렬 키: {v!r}")
                q.sort = (key, desc)
                group.append(None)        # 그룹 자리만 차지 (조건 아님)
                continue
            if m:
                term = _field_term(m.group(1), m.group(2), m.group(3))
            else:
                needle = raw.lower()
                term = (lambda i, today, s=needle: s in i.title.lower())
        if neg:
            term = (lambda i, today, t=term: not t(i, today))
        group.append(term)
    if pending_or:
        raise QueryError("OR 위치가 잘못되었습니다")
    if group or groups:
        groups.append(group)
    q.groups = [[t for t in g if t is not None] for g in groups]
    return q
