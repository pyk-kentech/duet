"""영업시간.

자원마다 요일(0=월 … 6=일)별로 영업 구간을 하나씩 가진다. 구간이 없는 요일은 쉬는 날이다.
내부 표현은 ``{요일: (여는 시각, 닫는 시각)}`` 사전이고, 사람이 쓰는 문자열 형식은 이렇다::

    mon-fri 08:00-20:00; sat 10:00-14:00
    mon,wed,fri 09:00-18:00
    fri 18:00-02:00                       (자정을 넘는 구간)

- 요일 이름: mon tue wed thu fri sat sun. ``mon-fri`` 처럼 범위(주 순서대로), 쉼표로 여러 개.
- 시각은 ``HH:MM``, 15분 단위. 여는 시각과 닫는 시각이 같으면 오류.
- 닫는 시각이 여는 시각보다 앞이면 다음 날 그 시각까지 영업한다(``00:00`` 은 자정까지).
  구간은 여는 날의 것이다: ``fri 18:00-02:00`` = 금 18:00 ~ 토 02:00.
  자정을 넘는 구간이 다음 날의 구간과 겹치면 오류(맞닿는 것은 된다).
- 한 요일이 두 번 나오면 오류. 빈 문자열은 '늘 닫힘'.
- 예약은 영업 구간 **하나** 안에 있어야 한다. 끝 시각이 닫는 시각과 같아도 된다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from booking.timeutil import fmt_hm, minutes_between, parse_hm

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_HOURS = "mon-fri 08:00-20:00"

Hours = dict[int, tuple[time, time]]


def _parse_days(text: str) -> list[int]:
    out: list[int] = []
    for item in text.split(","):
        item = item.strip().lower()
        if not item:
            raise ValueError(f"요일이 비어 있습니다: {text!r}")
        if "-" in item:
            a, b = (x.strip() for x in item.split("-", 1))
            if a not in DAY_NAMES or b not in DAY_NAMES:
                raise ValueError(f"요일 이름 오류: {item!r}")
            ia, ib = DAY_NAMES.index(a), DAY_NAMES.index(b)
            if ib < ia:
                raise ValueError(f"요일 범위는 주 순서대로 써야 합니다: {item!r}")
            out.extend(range(ia, ib + 1))
        else:
            if item not in DAY_NAMES:
                raise ValueError(f"요일 이름 오류: {item!r}")
            out.append(DAY_NAMES.index(item))
    return out


def overnight(rng: tuple[time, time]) -> bool:
    """닫는 시각이 여는 시각보다 앞이면(자정을 넘으면) True."""
    return rng[1] < rng[0]


def parse_range(text: str) -> tuple[time, time]:
    if "-" not in text:
        raise ValueError(f"시간 범위 형식 오류: {text!r} (예: 08:00-20:00)")
    a, b = text.split("-", 1)
    opens, closes = parse_hm(a), parse_hm(b)
    if closes == opens:
        raise ValueError(f"여는 시각과 닫는 시각이 같습니다: {text!r}")
    return opens, closes


def check_hours(hours: Hours) -> Hours:
    """자정을 넘는 구간이 다음 날의 구간과 겹치지 않는지."""
    for d, rng in hours.items():
        if not overnight(rng):
            continue
        nxt = hours.get((d + 1) % 7)
        if nxt is not None and nxt[0] < rng[1]:
            raise ValueError(f"{DAY_NAMES[d]} 의 영업 구간이 다음 날({DAY_NAMES[(d + 1) % 7]}) 구간과 겹칩니다")
    return hours


def parse_hours(spec: str) -> Hours:
    """영업시간 문자열을 사전으로. 형식이 틀리면 ValueError."""
    if not isinstance(spec, str):
        raise ValueError(f"영업시간은 문자열이어야 합니다: {spec!r}")
    hours: Hours = {}
    for part in spec.split(";"):
        part = part.strip()
        if not part:
            continue
        pieces = part.split()
        if len(pieces) != 2:
            raise ValueError(f"영업시간 형식 오류: {part!r} (예: mon-fri 08:00-20:00)")
        day_list = _parse_days(pieces[0])
        rng = parse_range(pieces[1])
        for d in day_list:
            if d in hours:
                raise ValueError(f"같은 요일이 두 번 나옵니다: {DAY_NAMES[d]}")
            hours[d] = rng
    return check_hours(hours)


def format_hours(hours: Hours) -> str:
    """표준 문자열. 이어진 요일의 같은 구간은 묶는다(mon-fri)."""
    parts: list[str] = []
    d = 0
    while d < 7:
        if d not in hours:
            d += 1
            continue
        rng = hours[d]
        e = d
        while e + 1 < 7 and hours.get(e + 1) == rng:
            e += 1
        days = DAY_NAMES[d] if d == e else f"{DAY_NAMES[d]}-{DAY_NAMES[e]}"
        parts.append(f"{days} {fmt_hm(rng[0])}-{fmt_hm(rng[1])}")
        d = e + 1
    return "; ".join(parts)


def open_interval(hours: Hours, day: date) -> tuple[datetime, datetime] | None:
    """그 날 여는 영업 구간 (시작, 끝) 또는 None. 자정을 넘으면 끝은 다음 날."""
    rng = hours.get(day.weekday())
    if not rng:
        return None
    end_day = day + timedelta(days=1) if overnight(rng) else day
    return datetime.combine(day, rng[0]), datetime.combine(end_day, rng[1])


def within(hours: Hours, start: datetime, end: datetime) -> bool:
    """[start, end) 가 영업 구간 하나 안에 들어가는지 (그 날 여는 구간 또는 전날 자정을 넘는 구간)."""
    d = start.date()
    for day in (d, d - timedelta(days=1)):
        iv = open_interval(hours, day)
        if iv is not None and iv[0] <= start and end <= iv[1]:
            return True
    return False


def open_minutes(hours: Hours, day: date) -> int:
    iv = open_interval(hours, day)
    return minutes_between(*iv) if iv else 0
