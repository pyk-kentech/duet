"""참조 구현: POSIX TZ 문자열 파서와 규칙 날짜 계산."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

ASCII_DIGITS = frozenset("0123456789")
ASCII_LETTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
QUOTED_CHARS = ASCII_LETTERS | ASCII_DIGITS | {"+", "-"}


def nth_weekday(year: int, month: int, week: int, weekday: int) -> date:
    """POSIX Mm.w.d 날짜: weekday 0 = 일요일, week 5 = 그 달의 마지막."""
    first = date(year, month, 1)
    first_wd = (first.weekday() + 1) % 7
    day = 1 + (weekday - first_wd) % 7 + 7 * (week - 1)
    last = calendar.monthrange(year, month)[1]
    while day > last:
        day -= 7
    return date(year, month, day)


@dataclass(frozen=True)
class Rule:
    kind: str            # "J" | "n" | "M"
    n: int = 0
    month: int = 0
    week: int = 0
    weekday: int = 0
    seconds: int = 7200  # 기본 02:00

    def day(self, year: int) -> date:
        if self.kind == "J":
            d = date(year, 1, 1) + timedelta(days=self.n - 1)
            if calendar.isleap(year) and self.n >= 60:
                d += timedelta(days=1)          # 2월 29일은 세지 않는다
            return d
        if self.kind == "n":
            return date(year, 1, 1) + timedelta(days=self.n)   # 평년 365 → 다음 해 1월 1일
        return nth_weekday(year, self.month, self.week, self.weekday)

    def local(self, year: int) -> datetime:
        return datetime.combine(self.day(year), time()) + timedelta(seconds=self.seconds)

    def __str__(self) -> str:
        if self.kind == "J":
            s = f"J{self.n}"
        elif self.kind == "n":
            s = str(self.n)
        else:
            s = f"M{self.month}.{self.week}.{self.weekday}"
        return s if self.seconds == 7200 else f"{s}/{fmt_hms(self.seconds)}"


def fmt_hms(seconds: int) -> str:
    """POSIX 형식: 음수만 '-', 시는 앞자리 0 없이, 필요한 만큼만 :mm, :ss."""
    sign = "-" if seconds < 0 else ""
    h, rem = divmod(abs(seconds), 3600)
    m, s = divmod(rem, 60)
    out = f"{sign}{h}"
    if m or s:
        out += f":{m:02d}"
    if s:
        out += f":{s:02d}"
    return out


def fmt_abbr(name: str) -> str:
    return name if all(c in ASCII_LETTERS for c in name) else f"<{name}>"


DEFAULT_START = Rule("M", month=3, week=2, weekday=0)
DEFAULT_END = Rule("M", month=11, week=1, weekday=0)


@dataclass(frozen=True)
class Parsed:
    std_abbr: str
    std: int                  # 동쪽이 +, 초
    dst_abbr: str | None = None
    dst: int | None = None
    start: Rule | None = None
    end: Rule | None = None


class _Parser:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def fail(self, why: str) -> ValueError:
        return ValueError(f"잘못된 TZ 문자열 {self.s!r} (위치 {self.i}): {why}")

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def take(self, ch: str) -> bool:
        if self.peek() == ch:
            self.i += 1
            return True
        return False

    def expect(self, ch: str) -> None:
        if not self.take(ch):
            raise self.fail(f"{ch!r} 가 와야 한다")

    def digits(self, min_len: int, max_len: int) -> int:
        j = self.i
        while j < len(self.s) and self.s[j] in ASCII_DIGITS:
            j += 1
        if not min_len <= j - self.i <= max_len:
            raise self.fail("숫자 자릿수가 맞지 않는다")
        v = int(self.s[self.i:j])
        self.i = j
        return v

    def abbr(self) -> str:
        if self.take("<"):
            j = self.s.find(">", self.i)
            if j < 0:
                raise self.fail("'>' 가 없다")
            name = self.s[self.i:j]
            if len(name) < 3 or any(c not in QUOTED_CHARS for c in name):
                raise self.fail("따옴표 이름은 영문자·숫자·+·- 3자 이상")
            self.i = j + 1
            return name
        j = self.i
        while j < len(self.s) and self.s[j] in ASCII_LETTERS:
            j += 1
        name = self.s[self.i:j]
        if len(name) < 3:
            raise self.fail("이름은 영문자 3자 이상")
        self.i = j
        return name

    def hms(self, max_hours: int, hour_digits: int) -> int:
        sign = 1
        if self.peek() in ("+", "-"):
            sign = -1 if self.peek() == "-" else 1
            self.i += 1
        h = self.digits(1, hour_digits)
        if h > max_hours:
            raise self.fail("시가 범위를 벗어난다")
        m = s = 0
        if self.take(":"):
            m = self.digits(2, 2)
            if m > 59:
                raise self.fail("분은 00~59")
            if self.take(":"):
                s = self.digits(2, 2)
                if s > 59:
                    raise self.fail("초는 00~59")
        return sign * (h * 3600 + m * 60 + s)

    def rule(self) -> Rule:
        c = self.peek()
        if c == "J":
            self.i += 1
            n = self.digits(1, 3)
            if not 1 <= n <= 365:
                raise self.fail("Jn 은 1~365")
            r = Rule("J", n=n)
        elif c in ASCII_DIGITS and c:
            n = self.digits(1, 3)
            if n > 365:
                raise self.fail("n 은 0~365")
            r = Rule("n", n=n)
        elif c == "M":
            self.i += 1
            m = self.digits(1, 2)
            self.expect(".")
            w = self.digits(1, 1)
            self.expect(".")
            d = self.digits(1, 1)
            if not (1 <= m <= 12 and 1 <= w <= 5 and 0 <= d <= 6):
                raise self.fail("Mm.w.d 범위")
            r = Rule("M", month=m, week=w, weekday=d)
        else:
            raise self.fail("규칙 날짜가 와야 한다")
        if self.take("/"):
            r = Rule(r.kind, r.n, r.month, r.week, r.weekday, self.hms(167, 3))
        return r


def parse(spec: str) -> Parsed:
    if not isinstance(spec, str):
        raise TypeError("TZ 문자열은 str 이어야 한다")
    p = _Parser(spec)
    std_abbr = p.abbr()
    std = -p.hms(23, 2)
    if p.i == len(spec):
        return Parsed(std_abbr, std)
    if p.peek() == ",":
        raise p.fail("DST 이름 없이 규칙이 왔다")
    dst_abbr = p.abbr()
    if p.peek() not in ("", ","):
        dst = -p.hms(23, 2)
    else:
        dst = std + 3600
    if abs(dst) >= 86400:
        raise p.fail("DST 오프셋은 24시간 미만")
    if dst == std:
        raise p.fail("DST 오프셋이 표준 오프셋과 같다")
    if p.take(","):
        start = p.rule()
        p.expect(",")
        end = p.rule()
    else:
        start, end = DEFAULT_START, DEFAULT_END
    if p.i != len(spec):
        raise p.fail("뒤에 남은 글자가 있다")
    return Parsed(std_abbr, std, dst_abbr, dst, start, end)
