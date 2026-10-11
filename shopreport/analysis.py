"""The actual logic: daily totals, payment-vs-sale reconciliation, low stock."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta


def money(value):
    return f"KES {value:,.0f}"


def on_day(items, day):
    return [i for i in items if i.time.date() == day]


def daily_summary(payments, day):
    """Totals for money in / money out on one day."""
    todays = on_day(payments, day)
    incoming = [p for p in todays if p.paid_in > 0]
    outgoing = [p for p in todays if p.withdrawn > 0]

    by_payer = defaultdict(float)
    by_hour = defaultdict(int)
    for p in incoming:
        by_payer[p.payer or "Unknown"] += p.paid_in
        by_hour[p.time.hour] += 1

    total_in = sum(p.paid_in for p in incoming)
    top_payers = sorted(by_payer.items(), key=lambda kv: kv[1], reverse=True)[:5]
    busiest = max(by_hour, key=by_hour.get) if by_hour else None

    return {
        "day": day,
        "total_in": total_in,
        "count_in": len(incoming),
        "average_in": total_in / len(incoming) if incoming else 0.0,
        "total_out": sum(p.withdrawn for p in outgoing),
        "count_out": len(outgoing),
        "top_payers": top_payers,
        "hourly": dict(sorted(by_hour.items())),
        "busiest_hour": busiest,
    }


@dataclass
class Reconciliation:
    matched: list = field(default_factory=list)  # (payment, sale)
    unmatched_payments: list = field(default_factory=list)  # money in, no sale logged
    unmatched_sales: list = field(default_factory=list)  # M-Pesa sale, no money seen


def reconcile(payments, sales, day, window_minutes=30):
    """Pair each M-Pesa payment with a logged M-Pesa sale of the same amount.

    A payment and a sale match when the amounts are equal and the times are within
    `window_minutes`. Each sale is used once; the closest in time wins.
    """
    window = timedelta(minutes=window_minutes)
    incoming = [p for p in on_day(payments, day) if p.paid_in > 0]
    open_sales = [s for s in on_day(sales, day) if s.method == "mpesa"]

    result = Reconciliation()
    for payment in incoming:
        candidates = [
            s
            for s in open_sales
            if abs(s.amount - payment.paid_in) < 0.01 and abs(s.time - payment.time) <= window
        ]
        if candidates:
            best = min(candidates, key=lambda s: abs(s.time - payment.time))
            open_sales.remove(best)
            result.matched.append((payment, best))
        else:
            result.unmatched_payments.append(payment)

    result.unmatched_sales = open_sales
    return result


def sales_summary(sales, day):
    todays = on_day(sales, day)
    by_method = defaultdict(float)
    by_item = defaultdict(int)
    for s in todays:
        by_method[s.method] += s.amount
        by_item[s.item] += s.qty
    return {
        "total": sum(s.amount for s in todays),
        "count": len(todays),
        "by_method": dict(by_method),
        "top_items": sorted(by_item.items(), key=lambda kv: kv[1], reverse=True)[:5],
    }


def low_stock(inventory):
    """Items at or below their reorder level, most urgent first."""
    flagged = [i for i in inventory if i.qty_on_hand <= i.reorder_level]
    return sorted(flagged, key=lambda i: i.qty_on_hand / max(i.reorder_level, 1))


def client_ranking(payments, recon, day):
    """Everyone who paid on `day`, highest total first, with the items they bought.

    Items come from reconciliation: when a payment matches a logged sale we know
    what that client bought. Only M-Pesa payers appear; cash customers are not
    identified in an M-Pesa statement.
    """
    sale_for_receipt = {p.receipt: s for p, s in recon.matched}
    groups = {}
    for p in on_day(payments, day):
        if p.paid_in <= 0:
            continue
        name = p.payer or "Unknown"
        key = f"{name} ({p.payer_ref})" if p.payer_ref else name
        g = groups.setdefault(key, {"client": key, "total": 0.0, "count": 0, "last": p.time, "items": []})
        g["total"] += p.paid_in
        g["count"] += 1
        g["last"] = max(g["last"], p.time)
        sale = sale_for_receipt.get(p.receipt)
        if sale:
            g["items"].append(sale.item)
    return sorted(groups.values(), key=lambda g: (-g["total"], g["client"]))
