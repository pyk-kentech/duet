from datetime import datetime

from issuetrack import query as querymod
from issuetrack.errors import InvalidTransition, NotFound
from issuetrack.models import (
    TRANSITIONS, Event, Issue, check_assignee, check_due, check_labels, check_priority, check_status, check_title,
)

_CHECKS = {"title": check_title, "priority": check_priority, "assignee": check_assignee, "due": check_due}


class Tracker:
    def __init__(self, clock=None):
        self.clock = clock or datetime.now
        self._issues: dict[int, Issue] = {}
        self._events: list[Event] = []
        self._next_id = 1

    # ------------------------------------------------------------ 내부
    def _restore(self, issues, events, next_id):
        self._issues = {i.id: i for i in issues}
        self._events = list(events)
        self._next_id = next_id

    def _new(self, title, priority, labels, assignee, due, status, now):
        issue = Issue(id=self._next_id, title=title, status=status, priority=priority, labels=labels,
                      assignee=assignee, due=due, created=now, updated=now)
        self._next_id += 1
        self._issues[issue.id] = issue
        self._events.append(Event(now, issue.id, "created", None, status))
        return issue

    def _add_imported(self, rows):
        now = self.clock()
        return [self._new(r["title"], r["priority"], r["labels"], r["assignee"], r["due"], r["status"], now).id
                for r in rows]

    # ------------------------------------------------------------ 공개
    def create(self, title, *, priority=3, labels=(), assignee=None, due=None):
        values = (check_title(title), check_priority(priority), check_labels(labels), check_assignee(assignee),
                  check_due(due))
        return self._new(*values, "open", self.clock())

    def get(self, issue_id):
        try:
            return self._issues[issue_id]
        except (KeyError, TypeError):
            raise NotFound(f"없는 이슈: {issue_id}") from None

    def issues(self):
        return [self._issues[k] for k in sorted(self._issues)]

    def update(self, issue_id, **fields):
        issue = self.get(issue_id)
        unknown = set(fields) - set(_CHECKS)
        if unknown:
            raise ValueError(f"바꿀 수 없는 필드: {', '.join(sorted(unknown))}")
        new = {k: _CHECKS[k](v) for k, v in fields.items()}
        now = None
        for k, v in new.items():
            old = getattr(issue, k)
            if old != v:
                now = now or self.clock()
                setattr(issue, k, v)
                self._events.append(Event(now, issue.id, k, old, v))
        if now is not None:
            issue.updated = now
        return issue

    def label(self, issue_id, add=(), remove=()):
        issue = self.get(issue_id)
        add, remove = check_labels(add), check_labels(remove)
        new = tuple(sorted((set(issue.labels) | set(add)) - set(remove)))
        if new != issue.labels:
            now = self.clock()
            self._events.append(Event(now, issue.id, "labels", issue.labels, new))
            issue.labels = new
            issue.updated = now
        return issue

    def move(self, issue_id, status):
        issue = self.get(issue_id)
        check_status(status)
        if status not in TRANSITIONS[issue.status]:
            raise InvalidTransition(f"{issue.status} → {status} 는 허용되지 않습니다")
        if status == "doing" and issue.assignee is None:
            raise InvalidTransition("doing 으로 가려면 담당자가 필요합니다")
        now = self.clock()
        self._events.append(Event(now, issue.id, "status", issue.status, status))
        issue.status = status
        issue.updated = now
        return issue

    def delete(self, issue_id):
        self.get(issue_id)
        del self._issues[issue_id]
        self._events = [e for e in self._events if e.issue_id != issue_id]

    def history(self, issue_id):
        self.get(issue_id)
        return [e for e in self._events if e.issue_id == issue_id]

    def events(self):
        return list(self._events)

    def search(self, text):
        q = querymod.parse(text)
        today = self.clock().date()
        return q.order([i for i in self.issues() if q.matches(i, today)])
