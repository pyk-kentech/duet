"""참조 구현: 숨은 테스트 검증용. POSIX TZ 규칙, 지역 시각 <-> UTC, 반복 일정."""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import NamedTuple

from ._spec import fmt_abbr, fmt_hms, nth_weekday, parse

__all__ = ["TZ", "Transition"]

_GAPS = ("shift", "skip")
_AMBIG = ("first", "last", "both")


class Transition(NamedTuple):
    when: datetime        # UTC (naive)
    before: timedelta
    after: timedelta


def _check_local(local) -> None:
    if not isinstance(local, datetime):
        raise TypeError("지역 시각은 datetime 이어야 한다")
    if local.tzinfo is not None:
        raise ValueError("지역 시각에 tzinfo 가 있으면 안 된다")


def _check_fold(fold) -> None:
    if fold not in (0, 1):
        raise ValueError("fold 는 0 또는 1")


def _utc_input(utc) -> datetime:
    if not isinstance(utc, datetime):
        raise TypeError("UTC 시각은 datetime 이어야 한다")
    if utc.tzinfo is not None:
        utc = utc.astimezone(timezone.utc).replace(tzinfo=None)
    return utc.replace(fold=0)


class TZ:
    def __init__(self, spec: str):
        p = parse(spec)
        self.spec = spec
        self.std_abbr = p.std_abbr
        self.std_offset = timedelta(seconds=p.std)
        self.dst_abbr = p.dst_abbr
        self.dst_offset = None if p.dst is None else timedelta(seconds=p.dst)
        self._start, self._end = p.start, p.end
        self._tzinfo = _TzInfo(self)
        self._iv_cache: dict[int, tuple] = {}

    def __repr__(self) -> str:
        return f"TZ({self.spec!r})"

    def __str__(self) -> str:
        s = fmt_abbr(self.std_abbr) + fmt_hms(-int(self.std_offset.total_seconds()))
        if self.dst_offset is None:
            return s
        s += fmt_abbr(self.dst_abbr)
        if self.dst_offset != self.std_offset + timedelta(hours=1):
            s += fmt_hms(-int(self.dst_offset.total_seconds()))
        return f"{s},{self._start},{self._end}"

    def __eq__(self, other):
        if not isinstance(other, TZ):
            return NotImplemented
        return str(self) == str(other)

    def __hash__(self) -> int:
        return hash(str(self))

    # ------------------------------------------------------------------ 시각선
    def _start_utc(self, year: int) -> datetime:
        return self._start.local(year) - self.std_offset

    def _end_utc(self, year: int) -> datetime:
        return self._end.local(year) - self.dst_offset

    def _period(self, year: int):
        """P(Y): S(Y) < E(Y) 이면 [S(Y), E(Y)), 아니면 [S(Y), E(Y+1))."""
        if year in self._iv_cache:
            return self._iv_cache[year]
        try:
            s = self._start_utc(year)
            e = self._end_utc(year)
            if not s < e:
                try:
                    e = self._end_utc(year + 1)
                except (ValueError, OverflowError):
                    e = datetime.max
            iv = (s, e)
        except (ValueError, OverflowError):
            iv = None
        self._iv_cache[year] = iv
        return iv

    def _merged(self, ylo: int, yhi: int) -> list[list[datetime]]:
        ivs = sorted(iv for y in range(ylo, yhi + 1) if (iv := self._period(y)) is not None)
        out: list[list[datetime]] = []
        for a, b in ivs:
            if out and a <= out[-1][1]:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return out

    def _offset_at(self, t: datetime) -> timedelta:
        if self.dst_offset is None:
            return self.std_offset
        for a, b in self._merged(t.year - 2, t.year + 2):
            if a <= t < b:
                return self.dst_offset
        return self.std_offset

    def _transitions_years(self, ya: int, yb: int) -> list[Transition]:
        if self.dst_offset is None:
            return []
        lo = datetime(ya, 1, 1)
        hi = datetime(yb + 1, 1, 1) if yb < 9999 else datetime.max
        out = []
        for a, b in self._merged(ya - 2, yb + 2):
            if lo <= a < hi:
                out.append(Transition(a, self.std_offset, self.dst_offset))
            if lo <= b < hi and b != datetime.max:
                out.append(Transition(b, self.dst_offset, self.std_offset))
        out.sort()
        return out

    # ------------------------------------------------------------------ 공개 API
    def transitions(self, year: int) -> list[Transition]:
        if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
            raise ValueError("year 는 1~9999")
        return self._transitions_years(year, year)

    def next_transition(self, utc: datetime) -> Transition | None:
        u = _utc_input(utc)
        if self.dst_offset is None:
            return None
        for y in range(u.year, min(u.year + 3, 9999) + 1):
            for tr in self._transitions_years(y, y):
                if tr.when > u:
                    return tr
        return None

    def _offsets(self) -> list[timedelta]:
        return [self.std_offset] if self.dst_offset is None else [self.std_offset, self.dst_offset]

    def _candidates(self, local: datetime) -> list[timedelta]:
        local = local.replace(fold=0)
        return [o for o in self._offsets() if self._offset_at(local - o) == o]

    def utcoffset(self, local: datetime, fold: int = 0) -> timedelta:
        _check_local(local)
        _check_fold(fold)
        c = self._candidates(local)
        if len(c) == 2:                    # 겹침: fold=0 은 앞(큰 오프셋), fold=1 은 뒤
            return max(c) if fold == 0 else min(c)
        if len(c) == 1:
            return c[0]
        offs = self._offsets()             # 틈: fold=0 은 전이 전(작은 오프셋), fold=1 은 후
        return min(offs) if fold == 0 else max(offs)

    def to_utc(self, local: datetime, fold: int = 0) -> datetime:
        off = self.utcoffset(local, fold)
        return local.replace(fold=0) - off

    def tzname(self, local: datetime, fold: int = 0) -> str:
        off = self.utcoffset(local, fold)
        return self.std_abbr if off == self.std_offset else self.dst_abbr

    def dst(self, local: datetime, fold: int = 0) -> timedelta:
        return self.utcoffset(local, fold) - self.std_offset

    def from_utc(self, utc: datetime) -> tuple[datetime, int]:
        u = _utc_input(utc)
        off = self._offset_at(u)
        local = u + off
        fold = 0
        if self.dst_offset is not None:
            other = self.dst_offset if off == self.std_offset else self.std_offset
            if other > off and self._offset_at(local - other) == other:
                fold = 1
        return local, fold

    def is_gap(self, local: datetime) -> bool:
        _check_local(local)
        return not self._candidates(local)

    def is_ambiguous(self, local: datetime) -> bool:
        _check_local(local)
        return len(self._candidates(local)) == 2

    def tzinfo(self) -> tzinfo:
        return self._tzinfo

    # ------------------------------------------------------------------ 반복 일정
    def _instants(self, local: datetime, gap: str, ambiguous: str) -> list[datetime]:
        c = self._candidates(local)
        if not c:
            return [] if gap == "skip" else [local - min(self._offsets())]
        if len(c) == 2:
            first, last = local - max(c), local - min(c)
            return {"first": [first], "last": [last], "both": [first, last]}[ambiguous]
        return [local - c[0]]

    @staticmethod
    def _check_schedule(at, start, n, gap, ambiguous) -> None:
        if not isinstance(at, time) or at.tzinfo is not None:
            raise ValueError("at 은 tzinfo 없는 time")
        if isinstance(start, datetime) or not isinstance(start, date):
            raise ValueError("start 는 date (datetime 은 안 된다)")
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError("개수는 0 이상 정수")
        if gap not in _GAPS:
            raise ValueError(f"gap 은 {_GAPS} 중 하나")
        if ambiguous not in _AMBIG:
            raise ValueError(f"ambiguous 는 {_AMBIG} 중 하나")

    def daily(self, at: time, start: date, days: int, *, gap: str = "shift",
              ambiguous: str = "first") -> list[datetime]:
        self._check_schedule(at, start, days, gap, ambiguous)
        at = at.replace(fold=0)
        out: list[datetime] = []
        for i in range(days):
            out.extend(self._instants(datetime.combine(start + timedelta(days=i), at), gap, ambiguous))
        return out

    def monthly(self, at: time, start: date, count: int, *, day: int | None = None,
                week: int | None = None, weekday: int | None = None, gap: str = "shift",
                ambiguous: str = "first") -> list[datetime]:
        self._check_schedule(at, start, count, gap, ambiguous)
        if day is not None:
            if week is not None or weekday is not None:
                raise ValueError("day 와 week·weekday 는 함께 쓸 수 없다")
            if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
                raise ValueError("day 는 1~31")
        else:
            if week is None or weekday is None:
                raise ValueError("day 또는 week·weekday 둘 다가 필요하다")
            for v, lo, hi in ((week, 1, 5), (weekday, 0, 6)):
                if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                    raise ValueError("week 는 1~5, weekday 는 0~6")
        at = at.replace(fold=0)
        out: list[datetime] = []
        found = 0
        y, m = start.year, start.month
        while found < count:
            if day is not None:
                d = date(y, m, day) if day <= calendar.monthrange(y, m)[1] else None
            else:
                d = nth_weekday(y, m, week, weekday)
            if d is not None and d >= start:
                got = self._instants(datetime.combine(d, at), gap, ambiguous)
                if got:
                    out.extend(got)
                    found += 1
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out


class _TzInfo(tzinfo):
    def __init__(self, tz: TZ):
        self._tz = tz

    def __repr__(self) -> str:
        return f"<tzinfo {self._tz.spec!r}>"

    def utcoffset(self, dt):
        if dt is None:
            return None
        return self._tz.utcoffset(dt.replace(tzinfo=None), dt.fold)

    def dst(self, dt):
        if dt is None:
            return None
        return self._tz.dst(dt.replace(tzinfo=None), dt.fold)

    def tzname(self, dt):
        if dt is None:
            return None
        return self._tz.tzname(dt.replace(tzinfo=None), dt.fold)

    def fromutc(self, dt):
        if not isinstance(dt, datetime):
            raise TypeError("fromutc 에는 datetime")
        if dt.tzinfo is not self:
            raise ValueError("fromutc: dt.tzinfo 가 이 tzinfo 가 아니다")
        local, fold = self._tz.from_utc(dt.replace(tzinfo=None))
        return local.replace(tzinfo=self, fold=fold)
