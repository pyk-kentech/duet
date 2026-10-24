"""자원(회의실·책상) 만들기와 검사.

- 종류: ``room``(회의실) 또는 ``desk``(책상). 책상은 1인용이라 정원이 늘 1이다.
- 정원(capacity): 1 이상의 정수. 회의실 예약의 참석 인원은 정원을 넘을 수 없다.
- 시간당 크레딧(credits_per_hour): 0 이상의 정수.
- 버퍼(buffer_minutes): 0 ~ 120, 15의 배수. 버퍼가 있는 자원에서는 **다른 회원의** 예약과
  버퍼 시간 이상 떨어져 있어야 한다(청소·환기 시간). 같은 회원이 이어서 쓰는 예약에는 버퍼가 필요 없다.
  버퍼는 예약끼리의 간격에만 적용되고, 영업 종료 시각까지 예약하는 것은 막지 않는다.
"""

from __future__ import annotations

from booking.errors import CapacityExceeded
from booking.hours import DEFAULT_HOURS, parse_hours
from booking.models import KINDS, Resource, check_id, check_name
from booking.timeutil import SLOT_MINUTES

MAX_BUFFER = 120


def _int(value, what: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{what} 는 {minimum} 이상의 정수여야 합니다: {value!r}")
    return value


def new_resource(id, name, kind="room", capacity=1, credits_per_hour=4, buffer_minutes=0,
                 hours=DEFAULT_HOURS) -> Resource:
    check_id(id, "자원")
    name = check_name(name, "자원")
    if kind not in KINDS:
        raise ValueError(f"자원 종류는 room 또는 desk: {kind!r}")
    _int(capacity, "정원", 1)
    if kind == "desk" and capacity != 1:
        raise ValueError("책상(desk)의 정원은 1 입니다")
    _int(credits_per_hour, "시간당 크레딧", 0)
    _int(buffer_minutes, "버퍼", 0)
    if buffer_minutes > MAX_BUFFER or buffer_minutes % SLOT_MINUTES:
        raise ValueError(f"버퍼는 0~{MAX_BUFFER}분, {SLOT_MINUTES}분 단위: {buffer_minutes!r}")
    if isinstance(hours, str):
        parsed = parse_hours(hours)
    elif isinstance(hours, dict):
        parsed = dict(hours)
    else:
        raise ValueError(f"영업시간 형식 오류: {hours!r}")
    return Resource(id=id, name=name, kind=kind, capacity=capacity, credits_per_hour=credits_per_hour,
                    buffer_minutes=buffer_minutes, hours=parsed)


def check_attendees(resource: Resource, attendees) -> int:
    """참석 인원 검사. 1 이상의 정수, 정원 이하. 책상은 늘 1명."""
    if isinstance(attendees, bool) or not isinstance(attendees, int) or attendees < 1:
        raise ValueError(f"참석 인원은 1 이상의 정수: {attendees!r}")
    if attendees > resource.capacity:
        raise CapacityExceeded(f"{resource.id}: 정원 {resource.capacity}명, 요청 {attendees}명")
    return attendees
