"""Generate FAKE data for a small electronics shop so the report can be demoed safely.

Nothing here is real: names, phone numbers, receipts and amounts are all made up.
Run:  python generate_sample_data.py --days 7 --end 2026-10-07
"""

import argparse
import csv
import random
import string
from datetime import date, datetime, timedelta
from pathlib import Path

PRODUCTS = [  # sku, item, price (KES), start qty, reorder level
    ("SKU-001", "Phone charger 20W", 800, 14, 6),
    ("SKU-002", "USB-C cable", 450, 30, 10),
    ("SKU-003", "Wireless earbuds", 1800, 9, 4),
    ("SKU-004", "Phone case", 500, 40, 12),
    ("SKU-005", "Screen protector", 350, 50, 15),
    ("SKU-006", "Power bank 10000mAh", 2500, 8, 4),
    ("SKU-007", "Bluetooth speaker", 3200, 6, 3),
    ("SKU-008", "Laptop bag", 2200, 7, 3),
    ("SKU-009", "HDMI cable", 700, 12, 5),
    ("SKU-010", "Flash drive 32GB", 900, 20, 8),
    ("SKU-011", "Smart watch", 3500, 5, 3),
    ("SKU-012", "Wireless mouse", 1100, 10, 4),
]
FIRST = ["Amina", "Brian", "Cynthia", "Dennis", "Esther", "Felix", "Grace", "Hassan", "Irene", "James",
         "Kevin", "Lucy", "Mercy", "Noah", "Olive", "Peter", "Faith", "Samuel", "Tabitha", "Victor"]
LAST = ["Mwangi", "Otieno", "Kamau", "Wanjiru", "Njoroge", "Achieng", "Kiptoo", "Mutua", "Naliaka", "Omondi"]


def receipt(rng, used):
    while True:
        code = "".join(rng.choices(string.ascii_uppercase + string.digits, k=10))
        if code not in used:
            used.add(code)
            return code


def fake_payer(rng):
    phone = f"2547****{rng.randint(100, 999)}"
    return f"{phone} - {rng.choice(FIRST).upper()} {rng.choice(LAST).upper()}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--end", default="2026-10-07", help="last day, YYYY-MM-DD")
    ap.add_argument("--out", default="sample_data")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    end = date.fromisoformat(args.end)
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    sales, statement, used = [], [], set()
    sale_no = 1000

    for offset in range(args.days - 1, -1, -1):
        day = end - timedelta(days=offset)
        is_last = offset == 0
        for _ in range(rng.randint(18, 32)):
            sku, item, price, _qty, _lvl = rng.choice(PRODUCTS)
            qty = rng.choice([1, 1, 1, 2])
            when = datetime(day.year, day.month, day.day, rng.choices(range(8, 20), weights=[2,3,4,5,6,5,4,4,5,6,4,2])[0], rng.randint(0, 59))
            method = "mpesa" if rng.random() < 0.7 else "cash"
            sale_no += 1
            sales.append({"sale_id": f"S{sale_no}", "timestamp": when, "sku": sku, "item": item,
                          "qty": qty, "amount": price * qty, "payment_method": method})
            if method == "mpesa":
                statement.append({"time": when + timedelta(minutes=rng.randint(0, 4)),
                                  "details": f"Funds received from {fake_payer(rng)}",
                                  "in": price * qty, "out": 0})

        # Supplier payment each day
        statement.append({"time": datetime(day.year, day.month, day.day, 17, rng.randint(0, 40)),
                          "details": "Pay Bill to 400200 - SAMPLE WHOLESALERS LTD",
                          "in": 0, "out": rng.choice([20000, 35000, 48000])})

        if is_last:  # plant a few problems so the demo has something to catch
            # 1) a customer pays but nobody logged the sale
            statement.append({"time": datetime(day.year, day.month, day.day, 13, 12),
                              "details": f"Funds received from {fake_payer(rng)}", "in": 5000, "out": 0})
            # 2) a sale was logged as M-Pesa but no payment arrived
            sale_no += 1
            sales.append({"sale_id": f"S{sale_no}", "timestamp": datetime(day.year, day.month, day.day, 15, 40),
                          "sku": "SKU-011", "item": "Smart watch", "qty": 1, "amount": 3500, "payment_method": "mpesa"})
            # 3) overpayment that doesn't match any sale amount
            statement.append({"time": datetime(day.year, day.month, day.day, 16, 5),
                              "details": f"Funds received from {fake_payer(rng)}", "in": 1550, "out": 0})

    statement.sort(key=lambda r: r["time"])
    balance = 120000.0
    with open(out / "mpesa_statement.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Receipt No", "Completion Time", "Details", "Transaction Status", "Paid In", "Withdrawn", "Balance"])
        for r in statement:
            balance += r["in"] - r["out"]
            w.writerow([receipt(rng, used), r["time"].strftime("%Y-%m-%d %H:%M:%S"), r["details"], "Completed",
                        f"{r['in']:,.2f}" if r["in"] else "", f"{r['out']:,.2f}" if r["out"] else "", f"{balance:,.2f}"])

    sales.sort(key=lambda r: r["timestamp"])
    with open(out / "sales_log.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sale_id", "timestamp", "sku", "item", "qty", "amount", "payment_method"])
        for r in sales:
            w.writerow([r["sale_id"], r["timestamp"].strftime("%Y-%m-%d %H:%M:%S"), r["sku"], r["item"],
                        r["qty"], r["amount"], r["payment_method"]])

    sold = {}
    for r in sales:
        sold[r["sku"]] = sold.get(r["sku"], 0) + r["qty"]
    with open(out / "inventory.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku", "item", "price", "qty_on_hand", "reorder_level"])
        for sku, item, price, qty, level in PRODUCTS:
            w.writerow([sku, item, price, max(qty - sold.get(sku, 0) // 4, 0) if sku not in ("SKU-003", "SKU-006") else 3, level])

    print(f"Wrote {len(statement)} statement rows, {len(sales)} sales to {out}/")


if __name__ == "__main__":
    main()
