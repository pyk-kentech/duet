"""참조 구현: 숨은 테스트 검증용."""

import collections
import threading
import time


class TokenBucket:
    def __init__(self, rate, capacity, clock=time.monotonic):
        if not rate > 0 or isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("rate > 0, capacity >= 1")
        self.rate, self.capacity, self.clock = rate, capacity, clock
        self._tokens = float(capacity)
        self._last = clock()
        self._lock = threading.Lock()

    def _refill(self):
        now = self.clock()
        if now > self._last:
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now

    def try_acquire(self, n=1):
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= self.capacity:
            raise ValueError("n 은 1..capacity")
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    def available(self):
        with self._lock:
            self._refill()
            return self._tokens


class SlidingWindow:
    def __init__(self, limit, window, clock=time.monotonic):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or not window > 0:
            raise ValueError("limit >= 1, window > 0")
        self.limit, self.window, self.clock = limit, window, clock
        self._events = collections.deque()
        self._lock = threading.Lock()

    def try_acquire(self):
        with self._lock:
            now = self.clock()
            while self._events and self._events[0] <= now - self.window:
                self._events.popleft()
            if len(self._events) < self.limit:
                self._events.append(now)
                return True
            return False


class KeyedLimiter:
    def __init__(self, factory, max_keys=1000):
        if isinstance(max_keys, bool) or not isinstance(max_keys, int) or max_keys < 1:
            raise ValueError("max_keys >= 1")
        self.factory, self.max_keys = factory, max_keys
        self._limiters = collections.OrderedDict()
        self._lock = threading.Lock()

    def _get(self, key):
        with self._lock:
            lim = self._limiters.get(key)
            if lim is None:
                lim = self.factory()
                while len(self._limiters) >= self.max_keys:
                    self._limiters.popitem(last=False)
                self._limiters[key] = lim
            else:
                self._limiters.move_to_end(key)
            return lim

    def try_acquire(self, key, *args):
        return self._get(key).try_acquire(*args)

    def __len__(self):
        with self._lock:
            return len(self._limiters)
