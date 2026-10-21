"""오류 계층.

예약 규칙 위반은 모두 ``BookingError`` 의 하위 클래스로 알린다. 입력 형식이 틀린 경우
(빈 이름, 잘못된 시각 문자열, 음수 정원 등)는 ``ValueError`` 를 쓴다. CLI 는 둘 다
``오류: ...`` 로 보여 주고 종료 코드 1 로 끝난다.
"""


class BookingError(Exception):
    """booking 패키지 오류의 공통 부모."""


class NotFound(BookingError):
    """찾는 대상이 없다."""


class UnknownResource(NotFound):
    pass


class UnknownMember(NotFound):
    pass


class UnknownBooking(NotFound):
    pass


class UnknownSeries(NotFound):
    pass


class UnknownEntry(NotFound):
    """없는 대기열 항목."""


class AlreadyExists(BookingError):
    """같은 id 가 이미 있다."""


class Conflict(BookingError):
    """다른 예약과 겹친다(버퍼 포함)."""


class OutsideHours(BookingError):
    """영업시간 밖."""


class CapacityExceeded(BookingError):
    """참석 인원이 정원을 넘는다."""


class InsufficientCredits(BookingError):
    """크레딧이 모자란다(초과 사용이 허용되지 않는 플랜)."""


class StorageError(BookingError):
    """데이터 파일을 읽거나 쓸 수 없다."""
