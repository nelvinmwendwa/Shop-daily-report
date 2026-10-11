from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Payment:
    """One row of an M-Pesa statement."""

    receipt: str
    time: datetime
    details: str
    paid_in: float
    withdrawn: float
    balance: float
    payer: str = ""  # name shown in the statement details, if any
    payer_ref: str = ""  # masked phone shown in the details, e.g. 2547****123


@dataclass(frozen=True)
class Sale:
    """One line of the shop's own sales log."""

    sale_id: str
    time: datetime
    sku: str
    item: str
    qty: int
    amount: float
    method: str  # "mpesa" or "cash"


@dataclass(frozen=True)
class StockItem:
    sku: str
    item: str
    price: float
    qty_on_hand: int
    reorder_level: int
