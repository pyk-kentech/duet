import random
import time

import pytest

from ttlcache import TTLCache, memoize


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def test_basic_set_get_default():
    c = TTLCache(3, 10, clock=Clock())
    c.set("a", 1)
    assert c.get("a") == 1 and c.get("x") is None and c.get("x", 7) == 7
    c.set("a", 2)
    assert c.get("a") == 2 and len(c) == 1
    c.set("n", None)
    assert c.get("n", "default") is None and "n" in c


def test_lru_eviction_get_counts_as_use():
    c = TTLCache(2, 100, clock=Clock())
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)
    assert "b" not in c and c.get("a") == 1 and c.get("c") == 3


def test_contains_does_not_count_as_use():
    c = TTLCache(2, 100, clock=Clock())
    c.set("a", 1)
    c.set("b", 2)
    assert "a" in c
    c.set("c", 3)
    assert "a" not in c and "b" in c


def test_set_existing_key_refreshes_recency_without_eviction():
    c = TTLCache(2, 100, clock=Clock())
    c.set("a", 1)
    c.set("b", 2)
    c.set("a", 10)          # 기존 키: 아무것도 지우지 않는다
    assert len(c) == 2
    c.set("c", 3)           # 이제 b 가 가장 오래됨
    assert "b" not in c and c.get("a") == 10


def test_ttl_boundary():
    clock = Clock(0.0)
    c = TTLCache(10, 10, clock=clock)
    c.set("a", 1)
    clock.t = 9.999
    assert c.get("a") == 1 and "a" in c and len(c) == 1
    clock.t = 10.0
    assert c.get("a") is None and "a" not in c and len(c) == 0


def test_set_refreshes_ttl_get_does_not():
    clock = Clock(0.0)
    c = TTLCache(10, 10, clock=clock)
    c.set("a", 1)
    clock.t = 8
    assert c.get("a") == 1       # get 은 만료를 늘리지 않는다
    clock.t = 10
    assert c.get("a") is None
    c.set("b", 1)
    clock.t = 15
    c.set("b", 2)                # set 은 늘린다
    clock.t = 24.9
    assert c.get("b") == 2
    clock.t = 25
    assert c.get("b") is None


def test_full_cache_drops_expired_before_live_lru():
    clock = Clock(0.0)
    c = TTLCache(2, 10, clock=clock)
    c.set("a", 1)                # 만료 10
    clock.t = 1
    c.set("b", 2)                # 만료 11
    clock.t = 2
    assert c.get("a") == 1       # a 가 최근, b 가 가장 오래됨
    clock.t = 10.5               # a 만료, b 살아 있음
    c.set("c", 3)
    assert c.get("b") == 2 and c.get("c") == 3 and len(c) == 2


def test_len_counts_only_live():
    clock = Clock(0.0)
    c = TTLCache(10, 5, clock=clock)
    for i in range(5):
        clock.t = i
        c.set(i, i)
    clock.t = 6.5                # 0, 1 만료 (만료 5, 6)
    assert len(c) == 3


def test_delete_and_clear():
    clock = Clock(0.0)
    c = TTLCache(5, 10, clock=clock)
    c.set("a", 1)
    c.set("b", 2)
    assert c.delete("a") is True and c.delete("a") is False and c.delete("zz") is False
    clock.t = 20
    assert c.delete("b") is False
    c.set("x", 1)
    c.clear()
    assert len(c) == 0 and "x" not in c


@pytest.mark.parametrize("args", [(0, 1), (-1, 1), (1.5, 1), (1, 0), (1, -2)])
def test_invalid(args):
    with pytest.raises(ValueError):
        TTLCache(*args, clock=Clock())


def test_default_clock():
    c = TTLCache(2, 0.05)
    c.set("a", 1)
    assert c.get("a") == 1
    time.sleep(0.08)
    assert c.get("a") is None


# ====================================================================== 성능
BUDGET_SEC = 6.0


def _within_budget(start, i):
    """느린 구현이 채점 전체를 붙잡지 않게 중간중간 시간을 본다."""
    if i % 1000 == 0 and time.perf_counter() - start > BUDGET_SEC:
        pytest.fail(f"시간 제한 {BUDGET_SEC}초 초과 ({i}번째 연산)")


def test_performance_many_ops():
    clock = Clock(0.0)
    c = TTLCache(100_000, 1_000_000, clock=clock)
    rnd = random.Random(1)
    start = time.perf_counter()
    for i in range(150_000):
        c.set(i, i)
        _within_budget(start, i)
    hits = 0
    for j in range(150_000):
        k = rnd.randrange(150_000)
        if c.get(k) is not None:
            hits += 1
        _within_budget(start, j)
    assert len(c) == 100_000
    assert 90_000 < hits < 110_000
    assert time.perf_counter() - start < BUDGET_SEC


def test_performance_with_expiry_churn():
    clock = Clock(0.0)
    c = TTLCache(100_000, 50.0, clock=clock)
    start = time.perf_counter()
    for i in range(200_000):
        clock.t = i * 0.001           # 5만 개마다 앞의 것들이 만료
        c.set(i, i)
        if i % 10 == 0:
            assert len(c) <= 50_001
        _within_budget(start, i)
    assert time.perf_counter() - start < BUDGET_SEC


# ====================================================================== memoize
def test_memoize_caches_and_kwargs_order():
    calls = []

    @memoize(maxsize=10, ttl=100, clock=Clock())
    def f(a, b=0):
        """doc"""
        calls.append((a, b))
        return a + b

    assert f(1, b=2) == 3 and f(1, b=2) == 3
    assert len(calls) == 1
    assert f(a=1, b=2) == 3 and f(b=2, a=1) == 3
    assert len(calls) == 2
    assert f.__name__ == "f" and f.__doc__ == "doc"
    assert isinstance(f.cache, TTLCache)


def test_memoize_typed():
    calls = []

    @memoize(clock=Clock())
    def g(x):
        calls.append(x)
        return repr(x)

    assert [g(1), g(1.0), g(True), g(1)] == ["1", "1.0", "True", "1"]
    assert len(calls) == 3
    assert g(x=1) == "1" and g(x=True) == "True"
    assert len(calls) == 5


def test_memoize_unhashable_passes_through():
    calls = []

    @memoize(clock=Clock())
    def h(xs):
        calls.append(1)
        return sum(xs)

    assert h([1, 2]) == 3 and h([1, 2]) == 3
    assert len(calls) == 2


def test_memoize_exceptions_not_cached():
    n = {"calls": 0}

    @memoize(clock=Clock())
    def boom(x):
        n["calls"] += 1
        if n["calls"] == 1:
            raise RuntimeError("first")
        return x

    with pytest.raises(RuntimeError):
        boom(5)
    assert boom(5) == 5 and boom(5) == 5
    assert n["calls"] == 2


def test_memoize_ttl_and_maxsize():
    clock = Clock(0.0)
    calls = []

    @memoize(maxsize=2, ttl=10, clock=clock)
    def k(x):
        calls.append(x)
        return x

    k(1)
    k(2)
    k(3)                 # 1 이 밀려남
    k(1)
    assert calls == [1, 2, 3, 1]
    clock.t = 10
    k(1)
    assert calls == [1, 2, 3, 1, 1]
