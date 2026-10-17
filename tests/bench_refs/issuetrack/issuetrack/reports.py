from datetime import timedelta

from issuetrack.models import FINISHED, STATUSES


def summary(tracker):
    out = {s: 0 for s in STATUSES}
    for i in tracker.issues():
        out[i.status] += 1
    return out


def workload(tracker):
    counts: dict = {}
    none = 0
    for i in tracker.issues():
        if i.status in FINISHED:
            continue
        if i.assignee is None:
            none += 1
        else:
            counts[i.assignee] = counts.get(i.assignee, 0) + 1
    out = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if none:
        out.append(("(none)", none))
    return out


def _first(events, status):
    return next((e.at for e in events if e.field == "status" and e.new == status), None)


def cycle_time(tracker, issue_id):
    events = tracker.history(issue_id)
    start, end = _first(events, "doing"), _first(events, "done")
    if start is None or end is None:
        return None
    return end - start


def throughput(tracker, start, end):
    out = {}
    d = start
    while d <= end:
        out[d] = 0
        d += timedelta(days=1)
    for e in tracker.events():
        if e.field == "status" and e.new == "done" and e.at.date() in out:
            out[e.at.date()] += 1
    return out
