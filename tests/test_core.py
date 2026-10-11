from datetime import date, datetime

from shopreport.analysis import daily_summary, low_stock, reconcile
from shopreport.models import Payment, Sale, StockItem
from shopreport.parsers import load_statement, mask_phone_numbers, parse_amount, parse_time

DAY = date(2026, 10, 7)


def pay(receipt, hour, minute, amount, payer="A B"):
    return Payment(receipt, datetime(2026, 10, 7, hour, minute), f"Funds received from 2547****111 - {payer}", amount, 0, 0, payer)


def sale(sid, hour, minute, amount, method="mpesa"):
    return Sale(sid, datetime(2026, 10, 7, hour, minute), "SKU", "Item", 1, amount, method)


def test_parse_amount_handles_commas_and_blanks():
    assert parse_amount("1,200.50") == 1200.5
    assert parse_amount("") == 0.0


def test_parse_time_accepts_known_formats():
    assert parse_time("2026-10-07 09:30:00") == datetime(2026, 10, 7, 9, 30)
    assert parse_time("07-10-2026 09:30:00") == datetime(2026, 10, 7, 9, 30)


def test_phone_numbers_are_masked():
    assert mask_phone_numbers("from 0712345678 - JANE") == "from 2547****678 - JANE"
    assert "****" in mask_phone_numbers("254712345678")


def test_statement_skips_failed_rows_and_extracts_payer(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text(
        "Receipt No,Completion Time,Details,Transaction Status,Paid In,Withdrawn,Balance\n"
        "AAA,2026-10-07 10:00:00,Funds received from 0712345678 - JANE DOE,Completed,\"1,500.00\",,5000\n"
        "BBB,2026-10-07 11:00:00,Funds received from 0700000000 - X Y,Failed,300,,5300\n"
    )
    rows = load_statement(f)
    assert len(rows) == 1
    assert rows[0].paid_in == 1500
    assert rows[0].payer == "JANE DOE"
    assert "0712345678" not in rows[0].details


def test_daily_summary_totals():
    payments = [pay("1", 9, 0, 800), pay("2", 9, 30, 1200, "C D")]
    s = daily_summary(payments, DAY)
    assert s["total_in"] == 2000 and s["count_in"] == 2
    assert s["busiest_hour"] == 9


def test_reconcile_matches_and_flags_both_directions():
    payments = [pay("1", 10, 2, 800), pay("2", 12, 0, 5000)]
    sales = [sale("S1", 10, 0, 800), sale("S2", 14, 0, 3500), sale("S3", 11, 0, 400, method="cash")]
    r = reconcile(payments, sales, DAY)
    assert len(r.matched) == 1
    assert [p.receipt for p in r.unmatched_payments] == ["2"]
    assert [s.sale_id for s in r.unmatched_sales] == ["S2"]  # cash sale is ignored


def test_each_sale_is_only_matched_once():
    payments = [pay("1", 10, 1, 800), pay("2", 10, 2, 800)]
    sales = [sale("S1", 10, 0, 800)]
    r = reconcile(payments, sales, DAY)
    assert len(r.matched) == 1 and len(r.unmatched_payments) == 1


def test_payment_outside_time_window_does_not_match():
    r = reconcile([pay("1", 16, 0, 800)], [sale("S1", 10, 0, 800)], DAY, window_minutes=30)
    assert not r.matched


def test_low_stock_orders_most_urgent_first():
    items = [StockItem("a", "A", 1, 5, 5), StockItem("b", "B", 1, 0, 4), StockItem("c", "C", 1, 50, 5)]
    assert [i.sku for i in low_stock(items)] == ["b", "a"]
