"""참조 구현: 숨은 테스트 검증용."""

import functools
import time
from collections import OrderedDict

_MISSING = object()


class TTLCache:
    def __init__(self, maxsize, ttl, clock=time.monotonic):
        if isinstance(maxsize, bool) or not isinstance(maxsize, int) or maxsize < 1 or not ttl > 0:
            raise ValueError("maxsize >= 1, ttl > 0")
        self.maxsize, self.ttl, self.clock = maxsize, ttl, clock
        self._lru: OrderedDict = OrderedDict()     # key -> value, 최근 사용 순
        self._exp: OrderedDict = OrderedDict()     # key -> 만료 시각, 만료 순 (ttl 이 같아 set 순서)

    def _purge(self, now):
        while self._exp:
            key, exp = next(iter(self._exp.items()))
            if exp > now:
                break
            del self._exp[key]
            del self._lru[key]

    def set(self, key, value):
        now = self.clock()
        self._purge(now)
        if key not in self._lru and len(self._lru) >= self.maxsize:
            old, _ = self._lru.popitem(last=False)
            del self._exp[old]
        self._lru[key] = value
        self._lru.move_to_end(key)
        self._exp[key] = now + self.ttl
        self._exp.move_to_end(key)

    def get(self, key, default=None):
        self._purge(self.clock())
        value = self._lru.get(key, _MISSING)
        if value is _MISSING:
            return default
        self._lru.move_to_end(key)
        return value

    def __contains__(self, key):
        self._purge(self.clock())
        return key in self._lru

    def __len__(self):
        self._purge(self.clock())
        return len(self._lru)

    def delete(self, key):
        self._purge(self.clock())
        if key in self._lru:
            del self._lru[key]
            del self._exp[key]
            return True
        return False

    def clear(self):
        self._lru.clear()
        self._exp.clear()


def _key(args, kwargs):
    items = tuple(sorted(kwargs.items()))
    return (args, items, tuple(type(a) for a in args), tuple(type(v) for _, v in items))


def memoize(maxsize=128, ttl=60.0, clock=time.monotonic):
    def deco(fn):
        cache = TTLCache(maxsize, ttl, clock)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = _key(args, kwargs)
            try:
                hash(key)
            except TypeError:
                return fn(*args, **kwargs)
            value = cache.get(key, _MISSING)
            if value is _MISSING:
                value = fn(*args, **kwargs)
                cache.set(key, value)
            return value

        wrapper.cache = cache
        return wrapper
    return deco
