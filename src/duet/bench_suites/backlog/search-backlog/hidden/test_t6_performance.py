"""FX-106: 문서 30,000개 색인에서 작업별 시간 제한.

각 측정은 별도 프로세스에서 한다(느린 구현이 채점 전체 시간을 다 쓰지 않게, 측정 도중에도 제한을 넘으면
바로 멈춘다). 측정 대상이 아닌 준비 단계(문서 add)는 넉넉한 제한(PREP_LIMIT)만 둔다.
"""

import json
import os
import random
import subprocess
import sys

import pytest

from findex import Index

ADD_LIMIT = 10.0
PREP_LIMIT = 15.0

SCRIPT = r'''
import json, random, sys, time
from findex import Index

SYLLABLES = ["ka", "lo", "mi", "ne", "ru", "sa", "to", "vi", "pe", "zu", "ba", "do", "fe", "gi", "ho", "ju"]

def make_docs(n=30000):
    rng = random.Random(2026)

    def word():
        return "".join(rng.choice(SYLLABLES) for _ in range(rng.randrange(2, 5)))

    docs = []
    for i in range(n):
        body = " ".join(word() for _ in range(5)) + (" common" if i % 3 == 0 else "")
        docs.append({"title": f"{word()} {word()}", "body": body, "tags": [f"tag{rng.randrange(50)}"],
                     "date": f"{rng.randrange(2010, 2025)}-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}"})
    return docs

phase, limit, prep_limit = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
out = {"phase": phase}

def done(**kw):
    out.update(kw)
    print(json.dumps(out))
    sys.exit(0)

docs = make_docs()
add_limit = limit if phase == "add" else prep_limit
t0 = time.perf_counter()
idx = Index()
for n, d in enumerate(docs):
    idx.add(**d)
    if n % 500 == 0 and time.perf_counter() - t0 > add_limit:
        done(ok=False, why=f"add too slow ({n} docs in {time.perf_counter() - t0:.1f}s)")
add_time = time.perf_counter() - t0
out["add_time"] = round(add_time, 3)

def timed(fn):
    t = time.perf_counter()
    result = fn(lambda: time.perf_counter() - t > limit)
    return time.perf_counter() - t, result

if phase == "add":
    done(ok=add_time <= limit, elapsed=add_time, check=[len(idx), idx.search("common").total])

if phase == "delete":
    def run(late):
        for k, doc_id in enumerate(range(1, 30001, 3)):
            idx.delete(doc_id)
            if k % 200 == 0 and late():
                return None
        return [len(idx), idx.search("common").total, idx.ids()[:3]]
    elapsed, check = timed(run)

elif phase == "update":
    def run(late):
        for k, doc_id in enumerate(range(2, 30001, 6)):
            idx.update(doc_id, body="changed common words here")
            if k % 100 == 0 and late():
                return None
        return [idx.search("common").total, idx.search("changed").total, len(idx)]
    elapsed, check = timed(run)

elif phase == "prefix":
    def run(late):
        totals = []
        for p in SYLLABLES[:10] * 2:
            totals.append(idx.search(p + "*").total)
            if late():
                return None
        return totals[:10]
    elapsed, check = timed(run)
    if check is not None:
        expected = []
        for p in SYLLABLES[:10]:
            expected.append(sum(1 for d in docs if any(w.startswith(p) for w in (d["title"] + " " + d["body"]).split())))
        out["expected"] = expected

elif phase == "not":
    def run(late):
        totals = []
        for _ in range(20):
            totals.append(idx.search("-common").total)
            if late():
                return None
        return sorted(set(totals))
    elapsed, check = timed(run)

elif phase == "suggest":
    def run(late):
        first = None
        for _ in range(5):
            for a in SYLLABLES:
                for b in SYLLABLES[:13]:
                    r = idx.suggest(a + b[0])
                    if first is None:
                        first = r
                if late():
                    return None
        return first
    elapsed, check = timed(run)
    if check is not None:
        counts = {}
        for n, d in enumerate(docs, 1):
            for w in set((d["title"] + " " + d["body"]).split()):
                if w.startswith("kak"):
                    counts[w] = counts.get(w, 0) + 1
        out["expected"] = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:10]

elif phase == "saveload":
    import os, tempfile
    path = os.path.join(tempfile.mkdtemp(), "big.json")
    def run(late):
        idx.save(path)
        j = Index.load(path)
        return [len(j), j.next_id, j.search("common").total]
    elapsed, check = timed(run)

else:
    raise SystemExit("unknown phase")

if check is None:
    done(ok=False, why="time limit exceeded", elapsed=limit)
done(ok=elapsed <= limit, elapsed=elapsed, check=check)
'''


def measure(tmp_path, phase, limit):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run([sys.executable, "-c", SCRIPT, phase, str(limit), str(PREP_LIMIT)], cwd=str(tmp_path),
                           capture_output=True, text=True, encoding="utf-8", env=env,
                           timeout=PREP_LIMIT + limit + 60)
    except subprocess.TimeoutExpired:
        pytest.fail(f"{phase}: 프로세스 시간 초과")
    lines = [line for line in r.stdout.splitlines() if line.startswith("{")]
    assert lines, f"{phase}: 결과 없음\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
    res = json.loads(lines[-1])
    assert res.get("ok"), f"{phase}: {res}"
    return res


def test_add_30000(tmp_path):
    res = measure(tmp_path, "add", ADD_LIMIT)
    assert res["check"] == [30000, 10000]


def test_delete_10000(tmp_path):
    res = measure(tmp_path, "delete", 1.5)
    assert res["check"] == [20000, 0, [2, 3, 5]]


def test_update_5000(tmp_path):
    res = measure(tmp_path, "update", 1.5)
    assert res["check"] == [15000, 5000, 30000]


def test_prefix_queries(tmp_path):
    res = measure(tmp_path, "prefix", 2.0)
    assert res["check"] == res["expected"]


def test_not_queries(tmp_path):
    res = measure(tmp_path, "not", 2.0)
    assert res["check"] == [20000]


def test_suggest_calls(tmp_path):
    res = measure(tmp_path, "suggest", 1.5)
    assert [list(x) for x in res["check"]] == [list(x) for x in res["expected"]]


def test_save_and_load(tmp_path):
    res = measure(tmp_path, "saveload", 8.0)
    assert res["check"] == [30000, 30001, 10000]


def test_bulk_changes_keep_exact_scores():
    """빠르게 고친 뒤에도 점수는 처음부터 만든 색인과 같아야 한다 (지우기·고치기 뒤의 통계)."""
    rng = random.Random(7)
    words = ["ka" + c + v for c in "lmnprst" for v in "aeiou"]
    docs = [(" ".join(rng.choice(words) for _ in range(2)), " ".join(rng.choice(words) for _ in range(rng.randrange(1, 9))))
            for _ in range(300)]
    deleted = set(range(5, 301, 7))
    updated = {n: " ".join(rng.choice(words) for _ in range(rng.randrange(1, 12))) for n in range(3, 301, 5)}
    live = Index()
    for title, body in docs:
        live.add(title, body=body)
    for n in sorted(updated):
        if n not in deleted:
            live.update(n, body=updated[n])
    for n in sorted(deleted):
        live.delete(n)
    fresh = Index()
    for n, (title, body) in enumerate(docs, 1):
        fresh.add(title, body=updated.get(n, body))
    for n in sorted(deleted):
        fresh.delete(n)
    for q in ["kala", "kame OR kasi", '"kala kame"', "kal*", "-kala", "title:kapu"]:
        a = {h.doc_id: h.score for h in live.search(q, per_page=100).hits}
        b = {h.doc_id: h.score for h in fresh.search(q, per_page=100).hits}
        assert a == pytest.approx(b, rel=1e-9), q
