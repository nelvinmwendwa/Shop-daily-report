"""Read the three CSV inputs. Customer phone numbers are masked on the way in."""

import csv
import re
from datetime import datetime
from pathlib import Path

from .models import Payment, Sale, StockItem

TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M")
PHONE_RE = re.compile(r"\b(?:254|0)([71]\d{8})\b")
PAYER_RE = re.compile(r"from\s+(\S+)\s*-\s*(.+)$", re.IGNORECASE)


def parse_amount(value):
    """'1,200.50' -> 1200.5 ; '' -> 0.0"""
    cleaned = (value or "").replace(",", "").strip()
    return float(cleaned) if cleaned else 0.0


def parse_time(value):
    value = (value or "").strip()
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date/time: {value!r}")


def mask_phone_numbers(text):
    """Replace full phone numbers with 2547****123 so reports never leak them."""
    return PHONE_RE.sub(lambda m: "254" + m.group(1)[0] + "****" + m.group(1)[-3:], text)


def _rows(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            yield {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def load_statement(path):
    """Load completed transactions from an M-Pesa style statement CSV."""
    payments = []
    for row in _rows(path):
        if row.get("Transaction Status", "Completed").lower() != "completed":
            continue
        details = mask_phone_numbers(row.get("Details", ""))
        match = PAYER_RE.search(details)
        payments.append(
            Payment(
                receipt=row["Receipt No"],
                time=parse_time(row["Completion Time"]),
                details=details,
                paid_in=parse_amount(row.get("Paid In")),
                withdrawn=parse_amount(row.get("Withdrawn")),
                balance=parse_amount(row.get("Balance")),
                payer=match.group(2).strip() if match else "",
                payer_ref=match.group(1).strip() if match else "",
            )
        )
    return sorted(payments, key=lambda p: p.time)


def load_sales(path):
    sales = [
        Sale(
            sale_id=row["sale_id"],
            time=parse_time(row["timestamp"]),
            sku=row["sku"],
            item=row["item"],
            qty=int(row["qty"]),
            amount=parse_amount(row["amount"]),
            method=row["payment_method"].lower(),
        )
        for row in _rows(path)
    ]
    return sorted(sales, key=lambda s: s.time)


def load_inventory(path):
    return [
        StockItem(
            sku=row["sku"],
            item=row["item"],
            price=parse_amount(row["price"]),
            qty_on_hand=int(row["qty_on_hand"]),
            reorder_level=int(row["reorder_level"]),
        )
        for row in _rows(Path(path))
    ]
