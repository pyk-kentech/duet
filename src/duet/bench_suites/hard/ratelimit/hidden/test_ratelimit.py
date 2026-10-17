import sys
import threading
import time

import pytest

from ratelimit import KeyedLimiter, SlidingWindow, TokenBucket


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def busy_switching():
    """스레드 전환을 아주 자주 일으켜 경쟁 조건을 드러낸다."""
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(old)


def hammer(fn, threads=16, calls=250):
    barrier = threading.Barrier(threads)
    results = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        mine = [fn() for _ in range(calls)]
        with lock:
            results.extend(mine)

    ts = [threading.Thread(target=worker) for _ in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    return sum(1 for r in results if r)


# ====================================================================== TokenBucket
def test_bucket_starts_full_and_refills():
    c = Clock()
    b = TokenBucket(rate=1, capacity=5, clock=c)
    assert [b.try_acquire() for _ in range(6)] == [True] * 5 + [False]
    c.t += 1
    assert b.try_acquire() and not b.try_acquire()
    c.t += 100
    assert b.available() == pytest.approx(5)
    assert sum(b.try_acquire() for _ in range(10)) == 5


def test_bucket_fractional_refill_and_n():
    c = Clock()
    b = TokenBucket(rate=2, capacity=4, clock=c)
    assert b.try_acquire(4)
    c.t += 0.25
    assert b.available() == pytest.approx(0.5)
    assert not b.try_acquire()
    c.t += 0.25
    assert b.try_acquire()
    c.t += 1.0
    assert not b.try_acquire(3) and b.available() == pytest.approx(2)
    assert b.try_acquire(2)


def test_bucket_failed_acquire_changes_nothing():
    c = Clock()
    b = TokenBucket(rate=1, capacity=3, clock=c)
    assert b.try_acquire(2)
    assert not b.try_acquire(2)
    assert b.available() == pytest.approx(1)


@pytest.mark.parametrize("kwargs", [dict(rate=0, capacity=1), dict(rate=-1, capacity=1),
                                    dict(rate=1, capacity=0), dict(rate=1, capacity=1.5)])
def test_bucket_invalid_args(kwargs):
    with pytest.raises(ValueError):
        TokenBucket(clock=Clock(), **kwargs)


@pytest.mark.parametrize("n", [0, -1, 6, 1.0, True])
def test_bucket_invalid_n(n):
    with pytest.raises(ValueError):
        TokenBucket(1, 5, clock=Clock()).try_acquire(n)


def test_bucket_clock_going_backwards():
    c = Clock(100.0)
    b = TokenBucket(rate=1, capacity=10, clock=c)
    for _ in range(10):
        assert b.try_acquire()
    c.t = 90.0                       # 거꾸로
    assert b.available() == pytest.approx(0)
    assert not b.try_acquire()
    c.t = 95.0                       # 여전히 기준(100) 전
    assert b.available() == pytest.approx(0)
    c.t = 102.0                      # 기준을 2초 넘음
    assert b.available() == pytest.approx(2)


def test_bucket_concurrent_exact(busy_switching):
    b = TokenBucket(rate=1, capacity=1000, clock=Clock())
    assert hammer(b.try_acquire) == 1000


def test_bucket_concurrent_exact_n3(busy_switching):
    b = TokenBucket(rate=1, capacity=1000, clock=Clock())
    assert hammer(lambda: b.try_acquire(3)) == 333


def test_bucket_default_clock_is_monotonic():
    b = TokenBucket(rate=1000, capacity=1)
    assert b.try_acquire()
    time.sleep(0.05)   # Windows 의 monotonic 은 약 15.6ms 단위로 바뀐다
    assert b.try_acquire()


# ====================================================================== SlidingWindow
def test_window_boundary():
    c = Clock(0.0)
    w = SlidingWindow(limit=3, window=10, clock=c)
    for t in (0.0, 1.0, 2.0):
        c.t = t
        assert w.try_acquire()
    c.t = 3.0
    assert not w.try_acquire()
    c.t = 9.999
    assert not w.try_acquire()
    c.t = 10.0                       # 0 에 성공한 호출은 이제 세지 않는다
    assert w.try_acquire()
    assert not w.try_acquire()       # 1, 2, 10
    c.t = 11.0
    assert w.try_acquire()           # 2, 10, 11
    assert not w.try_acquire()
    c.t = 12.0
    assert w.try_acquire()           # 10, 11, 12


def test_window_failures_not_recorded():
    c = Clock(0.0)
    w = SlidingWindow(limit=1, window=5, clock=c)
    assert w.try_acquire()
    for t in (1, 2, 3, 4):
        c.t = t
        assert not w.try_acquire()
    c.t = 5
    assert w.try_acquire()


@pytest.mark.parametrize("kwargs", [dict(limit=0, window=1), dict(limit=1, window=0), dict(limit=1.5, window=1)])
def test_window_invalid(kwargs):
    with pytest.raises(ValueError):
        SlidingWindow(clock=Clock(), **kwargs)


def test_window_concurrent_exact(busy_switching):
    w = SlidingWindow(limit=500, window=60, clock=Clock())
    assert hammer(w.try_acquire) == 500


# ====================================================================== KeyedLimiter
def test_keyed_independent_keys():
    c = Clock()
    k = KeyedLimiter(lambda: TokenBucket(1, 2, clock=c))
    assert [k.try_acquire("a") for _ in range(3)] == [True, True, False]
    assert k.try_acquire("b") and len(k) == 2
    assert k.try_acquire("a", 1) is False


def test_keyed_factory_called_once_under_contention(busy_switching):
    made = []
    lock = threading.Lock()

    def factory():
        time.sleep(0.02)              # 경쟁 구간을 넓힌다
        with lock:
            made.append(1)
        return TokenBucket(1, 100, clock=Clock())

    k = KeyedLimiter(factory)
    assert hammer(lambda: k.try_acquire("same"), threads=12, calls=20) == 100
    assert len(made) == 1


def test_keyed_lru_eviction():
    made = []

    def factory():
        made.append(1)
        return TokenBucket(1, 1, clock=Clock())

    k = KeyedLimiter(factory, max_keys=2)
    assert k.try_acquire("a") and k.try_acquire("b")
    assert not k.try_acquire("a")        # a 를 최근에 씀 → b 가 가장 오래됨
    assert k.try_acquire("c")            # b 를 지움
    assert len(k) == 2 and len(made) == 3
    assert k.try_acquire("b")            # 새 리미터(가득 참) — 이번엔 a 를 지움
    assert len(made) == 4 and len(k) == 2
    assert not k.try_acquire("c")        # c 는 남아 있다(토큰 다 씀)
    assert len(made) == 4


def test_keyed_invalid():
    with pytest.raises(ValueError):
        KeyedLimiter(lambda: None, max_keys=0)
