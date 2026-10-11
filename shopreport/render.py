"""Turn the analysis results into a single self-contained HTML report."""

from html import escape

from .analysis import money

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--mute:#667085;--line:#e4e7ec;--accent:#0b7a4b;--warn:#b54708;--warnbg:#fff4e5}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--card:#1a1f26;--ink:#e8ecf1;--mute:#98a2b3;--line:#2b323c;--accent:#3ccf91;--warn:#fdb022;--warnbg:#2a2113}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 48px}h1{font-size:22px;margin:0}h2{font-size:16px;margin:28px 0 10px}
.sub{color:var(--mute);margin:2px 0 18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.card b{display:block;font-size:20px}
.card span{color:var(--mute);font-size:13px}table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);font-size:14px}th{color:var(--mute);font-weight:600}tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right}.bar{height:8px;background:var(--accent);border-radius:4px}.alert{background:var(--warnbg);color:var(--warn);border-radius:10px;padding:10px 14px;margin:8px 0}
.ok{color:var(--accent)}.wrap{overflow-x:auto}.foot{color:var(--mute);font-size:12px;margin-top:32px}
"""


def _table(headers, rows, numeric=()):
    head = "".join(
        f'<th class="n">{escape(h)}</th>' if i in numeric else f"<th>{escape(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = ""
    for row in rows:
        cells = "".join(
            f'<td class="n">{escape(str(c))}</td>' if i in numeric else f"<td>{escape(str(c))}</td>"
            for i, c in enumerate(row)
        )
        body += f"<tr>{cells}</tr>"
    return f'<div class="wrap"><table><tr>{head}</tr>{body}</table></div>'


def render_html(shop_name, day, summary, sales, recon, stock_alerts, clients):
    cards = [
        ("Money in (M-Pesa)", money(summary["total_in"])),
        ("Payments received", str(summary["count_in"])),
        ("Average payment", money(summary["average_in"])),
        ("Money out", money(summary["total_out"])),
        ("Total sales logged", money(sales["total"])),
    ]
    cards_html = "".join(f'<div class="card"><b>{escape(v)}</b><span>{escape(k)}</span></div>' for k, v in cards)

    # Reconciliation
    alerts = ""
    if recon.unmatched_payments:
        total = sum(p.paid_in for p in recon.unmatched_payments)
        alerts += (
            f'<div class="alert">{len(recon.unmatched_payments)} payment(s) worth {money(total)} '
            f"have no matching sale in the sales log.</div>"
        )
    if recon.unmatched_sales:
        total = sum(s.amount for s in recon.unmatched_sales)
        alerts += (
            f'<div class="alert">{len(recon.unmatched_sales)} sale(s) marked M-Pesa worth {money(total)} '
            f"have no matching payment. Check before the customer leaves with the item.</div>"
        )
    if not alerts:
        alerts = '<p class="ok">All M-Pesa payments match the sales log.</p>'

    unmatched_rows = [
        (p.time.strftime("%H:%M"), p.receipt, p.payer or "-", money(p.paid_in), "Payment, no sale")
        for p in recon.unmatched_payments
    ] + [
        (s.time.strftime("%H:%M"), s.sale_id, s.item, money(s.amount), "Sale, no payment")
        for s in recon.unmatched_sales
    ]
    unmatched_html = (
        _table(["Time", "Reference", "Who / What", "Amount", "Issue"], unmatched_rows, numeric=(3,))
        if unmatched_rows
        else ""
    )

    # Hourly bars
    peak = max(summary["hourly"].values(), default=1)
    hour_rows = ""
    for hour, count in summary["hourly"].items():
        width = int(100 * count / peak)
        hour_rows += (
            f"<tr><td>{hour:02d}:00</td><td>{count}</td>"
            f'<td style="width:50%"><div class="bar" style="width:{width}%"></div></td></tr>'
        )
    hours_html = f'<div class="wrap"><table><tr><th>Hour</th><th>Payments</th><th></th></tr>{hour_rows}</table></div>'

    clients_html = (
        _table(
            ["#", "Client", "Payments", "Total paid", "Last paid", "Bought"],
            [
                (i, c["client"], c["count"], money(c["total"]), c["last"].strftime("%H:%M"), ", ".join(c["items"]) or "-")
                for i, c in enumerate(clients, 1)
            ],
            numeric=(0, 2, 3),
        )
        if clients
        else "<p>No M-Pesa payments today.</p>"
    )
    items_html = _table(
        ["Item", "Units sold"], [(name, qty) for name, qty in sales["top_items"]], numeric=(1,)
    )
    stock_html = (
        _table(
            ["Item", "On hand", "Reorder at"],
            [(i.item, i.qty_on_hand, i.reorder_level) for i in stock_alerts],
            numeric=(1, 2),
        )
        if stock_alerts
        else '<p class="ok">No items below reorder level.</p>'
    )

    busiest = f"{summary['busiest_hour']:02d}:00" if summary["busiest_hour"] is not None else "n/a"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(shop_name)} - daily report {day:%Y-%m-%d}</title><style>{CSS}</style></head>
<body><main>
<h1>{escape(shop_name)}</h1>
<p class="sub">Daily report for {day:%A, %d %B %Y} &middot; busiest hour {busiest}</p>
<div class="grid">{cards_html}</div>
<h2>Needs attention</h2>{alerts}{unmatched_html}
<h2>Today's clients, highest to lowest</h2>{clients_html}
<h2>Best sellers</h2>{items_html}
<h2>Payments by hour</h2>{hours_html}
<h2>Low stock</h2>{stock_html}
<p class="foot">Clients listed are M-Pesa payers only; cash customers are not identified. Generated by shop-daily-report. Sample output uses fake data.</p>
</main></body></html>"""
