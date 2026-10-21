"""shop: 작은 온라인 가게의 주문 관리 라이브러리와 CLI (표준 라이브러리만).

주요 진입점은 `Shop` 이다. 저장은 `shop.storage`, 보고서는 `shop.reports`, CSV 는 `shop.csvio`.
"""

from .cart import Cart, Quote, QuoteLine
from .catalog import Catalog, Product, Sellable, Variant
from .errors import CouponError, InsufficientStock, InvalidState, NotFound, ShopError, StorageError, ValidationError
from .inventory import Inventory
from .orders import CHANNELS, STATUSES, Order, OrderLine, Refund
from .pricing import COUPON_KINDS, Coupon
from .store import Settings, Shop
from .tax import TaxTable

__version__ = "0.9.2"

__all__ = [
    "CHANNELS", "COUPON_KINDS", "STATUSES", "Cart", "Catalog", "Coupon", "CouponError", "InsufficientStock", "InvalidState",
    "Inventory", "NotFound", "Order", "OrderLine", "Product", "Quote", "QuoteLine", "Refund", "Sellable", "Settings",
    "Shop", "ShopError", "StorageError", "TaxTable", "ValidationError", "Variant",
]
