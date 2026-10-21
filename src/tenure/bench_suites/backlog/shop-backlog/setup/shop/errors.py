"""shop 의 오류.

모든 오류는 ShopError 의 하위 클래스다. CLI 는 ShopError 를 잡아 메시지를 `오류: ...` 로 보여 주고
종료 코드 1 로 끝난다(데이터 파일은 바꾸지 않는다).
"""


class ShopError(Exception):
    """이 패키지가 일부러 내는 모든 오류의 부모."""


class ValidationError(ShopError, ValueError):
    """입력 값이 규칙에 맞지 않음."""


class NotFound(ShopError, LookupError):
    """없는 상품·쿠폰·주문."""


class InsufficientStock(ShopError):
    """재고 부족. 주문 전체가 거절되고 아무것도 예약되지 않는다."""


class InvalidState(ShopError):
    """지금 주문 상태에서 할 수 없는 동작 (예: 출고된 주문 취소)."""


class CouponError(ShopError):
    """쿠폰을 쓸 수 없음 (만료, 사용 한도, 최소 금액, 함께 쓰기 규칙)."""


class StorageError(ShopError):
    """데이터 파일을 읽거나 쓸 수 없음 (깨진 JSON, 모르는 형식 버전 등)."""
