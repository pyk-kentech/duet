"""iCalendar 비슷한 내보내기.

``export_ics(space, resource_id=None, member_id=None)`` 는 취소되지 않은 예약을 시작 시각, id 순으로
VEVENT 하나씩 내보낸다. 줄 끝은 CRLF, 마지막 줄 뒤에도 CRLF.

    BEGIN:VCALENDAR
    VERSION:2.0
    PRODID:-//booking//coworking//KO
    BEGIN:VEVENT
    UID:booking-12@booking.local
    DTSTART:20261021T090000
    DTEND:20261021T103000
    SUMMARY:Room A (alice)
    DESCRIPTION:메모           (메모가 있을 때만)
    CATEGORIES:series-3        (반복 예약의 발생일 때만)
    END:VEVENT
    END:VCALENDAR

글자 값(SUMMARY, DESCRIPTION)은 ``\\`` → ``\\\\``, ``;`` → ``\\;``, ``,`` → ``\\,``, 줄바꿈 → ``\\n`` 으로 바꾼다.
"""

from __future__ import annotations

PRODID = "-//booking//coworking//KO"


def escape_text(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def export_ics(space, resource_id: str | None = None, member_id: str | None = None) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}"]
    for b in space.bookings(resource_id=resource_id, member_id=member_id):
        res = space.resource(b.resource_id)
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:booking-{b.id}@booking.local")
        lines.append(f"DTSTART:{b.start:%Y%m%dT%H%M%S}")
        lines.append(f"DTEND:{b.end:%Y%m%dT%H%M%S}")
        lines.append(f"SUMMARY:{escape_text(res.name)} ({b.member_id})")
        if b.note:
            lines.append(f"DESCRIPTION:{escape_text(b.note)}")
        if b.series_id is not None:
            lines.append(f"CATEGORIES:series-{b.series_id}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
