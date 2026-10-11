import argparse
import csv
from datetime import datetime
from pathlib import Path

from . import alerts as stock_alerts
from . import db
from .analysis import client_ranking, daily_summary, low_stock, money, reconcile, sales_summary
from .parsers import load_inventory, load_sales, load_statement
from .render import render_html


def build_parser():
    parser = argparse.ArgumentParser(prog="shopreport", description="Daily report and history for a small shop.")
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("report", help="Build the daily report (and optionally save history + send stock alerts)")
    r.add_argument("--statement", required=True, help="M-Pesa statement CSV")
    r.add_argument("--sales", required=True, help="Sales log CSV")
    r.add_argument("--inventory", required=True, help="Stock list CSV")
    r.add_argument("--date", help="Report date YYYY-MM-DD (default: latest day in the statement)")
    r.add_argument("--shop-name", default="Demo Gadgets Shop", help="Name shown on the report")
    r.add_argument("--out", default="reports", help="Output folder")
    r.add_argument("--window", type=int, default=30, help="Minutes allowed between a payment and its sale")
    r.add_argument("--db", help="SQLite file to save history into (created if missing)")
    r.add_argument("--notify", choices=["none", "console", "telegram"], default="none", help="Send low-stock alerts (needs --db)")
    r.add_argument("--reminder-days", type=int, default=7, help="Days between reminders for items that stay low")

    h = sub.add_parser("history", help="Show or export every sale ever saved, with client details")
    h.add_argument("--db", required=True, help="SQLite file created by 'report --db'")
    h.add_argument("--client", help="Filter by client name (partial match)")
    h.add_argument("--item", help="Filter by item name (partial match)")
    h.add_argument("--since", help="Only sales from this date, YYYY-MM-DD")
    h.add_argument("--out", help="Also write the result to this CSV file")
    h.add_argument("--limit", type=int, default=15, help="Rows to print on screen")
    return parser


def run_report(args):
    payments = load_statement(args.statement)
    sales = load_sales(args.sales)
    inventory = load_inventory(args.inventory)
    if not payments:
        raise SystemExit("No completed transactions found in the statement.")
    if args.notify != "none" and not args.db:
        raise SystemExit("--notify needs --db so alerts are only sent once per low-stock event.")

    day = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else payments[-1].time.date()

    summary = daily_summary(payments, day)
    sales_info = sales_summary(sales, day)
    recon = reconcile(payments, sales, day, window_minutes=args.window)
    clients = client_ranking(payments, recon, day)
    low = low_stock(inventory)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"daily_report_{day:%Y-%m-%d}.html"
    html_path.write_text(render_html(args.shop_name, day, summary, sales_info, recon, low, clients), encoding="utf-8")

    attention_path = out_dir / f"needs_attention_{day:%Y-%m-%d}.csv"
    with open(attention_path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(["time", "reference", "who_or_item", "amount", "issue"])
        for p in recon.unmatched_payments:
            w.writerow([p.time.strftime("%H:%M"), p.receipt, p.payer, p.paid_in, "payment_without_sale"])
        for s in recon.unmatched_sales:
            w.writerow([s.time.strftime("%H:%M"), s.sale_id, s.item, s.amount, "sale_without_payment"])

    clients_path = out_dir / f"clients_{day:%Y-%m-%d}.csv"
    with open(clients_path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(["rank", "client", "payments", "total_paid", "last_paid", "items"])
        for i, c in enumerate(clients, 1):
            w.writerow([i, c["client"], c["count"], c["total"], c["last"].strftime("%H:%M"), "; ".join(c["items"])])

    print(f"Report for {day:%Y-%m-%d}")
    print(f"  Money in:        {money(summary['total_in'])} ({summary['count_in']} payments)")
    print(f"  Money out:       {money(summary['total_out'])}")
    print(f"  Sales logged:    {money(sales_info['total'])}")
    print(f"  Clients today:   {len(clients)}" + (f" (top: {clients[0]['client']}, {money(clients[0]['total'])})" if clients else ""))
    print(f"  Matched:         {len(recon.matched)}")
    print(f"  Payment no sale: {len(recon.unmatched_payments)}")
    print(f"  Sale no payment: {len(recon.unmatched_sales)}")
    print(f"  Low stock items: {len(low)}")
    print(f"Saved {html_path}, {attention_path} and {clients_path}")

    if args.db:
        conn = db.connect(args.db)
        new_pay, new_sales = db.save_payments(conn, payments), db.save_sales(conn, sales)
        db.save_matches(conn, payments, sales)
        totals = db.counts(conn)
        print(f"History saved to {args.db}: +{new_pay} payments, +{new_sales} sales "
              f"(total {totals['payments']} payments, {totals['sales']} sales, {totals['matches']} matched)")

        alerts, new_state = stock_alerts.evaluate(inventory, db.load_alert_state(conn), datetime.now(), args.reminder_days)
        db.save_alert_state(conn, new_state)
        message = stock_alerts.format_message(args.shop_name, alerts)
        print(f"Stock alerts to send now: {len(alerts)}")
        if message and args.notify != "none":
            notifier = stock_alerts.ConsoleNotifier() if args.notify == "console" else stock_alerts.TelegramNotifier.from_env()
            try:
                notifier.send(message)
            except Exception as exc:  # network problems must not break the report
                print(f"Warning: could not send alert ({exc})")
        conn.close()


def run_history(args):
    conn = db.connect(args.db)
    rows = db.sales_history(conn, client=args.client, item=args.item, since=args.since)
    conn.close()
    total = sum(r["amount"] for r in rows)
    print(f"{len(rows)} sale(s), total {money(total)}")
    for r in rows[: args.limit]:
        who = f"{r['client']} ({r['client_ref']})" if r["client"] else ("cash/unknown" if r["method"] == "cash" else "no matching payment")
        print(f"  {r['time']}  {r['item']:<22} x{r['qty']}  {money(r['amount']):>11}  {who}")
    if len(rows) > args.limit:
        print(f"  ... {len(rows) - args.limit} more (use --out to export all)")
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as handle:
            w = csv.DictWriter(handle, fieldnames=["time", "sale_id", "item", "qty", "amount", "method", "client", "client_ref", "receipt"])
            w.writeheader()
            w.writerows(rows)
        print(f"Saved {args.out}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "report":
        run_report(args)
    else:
        run_history(args)


if __name__ == "__main__":
    main()
