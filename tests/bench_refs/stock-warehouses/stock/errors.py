class StockError(Exception):
    """재고 관련 오류의 공통 부모."""


class UnknownItem(StockError):
    pass


class DuplicateItem(StockError):
    pass


class InsufficientStock(StockError):
    pass


class StorageError(StockError):
    pass


class UnknownWarehouse(StockError):
    pass


class DuplicateWarehouse(StockError):
    pass


class WarehouseNotEmpty(StockError):
    pass
