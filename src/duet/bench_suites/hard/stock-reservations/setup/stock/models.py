from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class Item:
    sku: str
    name: str
    on_hand: int = 0
    unit_cost: Decimal = Decimal("0")


@dataclass
class Movement:
    ts: datetime
    sku: str
    kind: str        # "receive" | "ship" | "adjust"
    qty: int         # 부호 있는 변화량 (출고는 음수)
    note: str = ""
