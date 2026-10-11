import urllib.request
from datetime import date, datetime, timedelta

import pytest

from shopreport import alerts, db
from shopreport.analysis import client_ranking, reconcile
from shopreport.models import Payment, Sale, StockItem
from shopreport.parsers import load_statement

DAY = date(2026, 10, 7)
NOW = datetime(2026, 10, 8, 9, 0)


def pay(receipt, hour, minute, amount, payer="A B", ref="2547****111"):
    return Payment(receipt, datetime(2026, 10, 7, hour, minute), f"Funds received from {ref} - {payer}", amount, 0, 0, payer, ref)


def sale(sid, hour, minute, amount, item="Item", method="mpesa"):
    return Sale(sid, datetime(2026, 10, 7, hour, minute), "SKU", item, 1, amount, method)


def item(sku, qty, level=5):
    return StockItem(sku, sku.upper(), 100, qty, level)


# ---- client ranking
def test_clients_ranked_highest_to_lowest_with_items():
    payments = [pay("1", 9, 0, 800, "SMALL", "2547****001"), pay("2", 10, 0, 3000, "BIG", "2547****002"),
                pay("3", 11, 0, 500, "SMALL", "2547****001")]
    sales = [sale("S1", 9, 0, 800, "Charger"), sale("S2", 10, 0, 3000, "Speaker")]
    ranking = client_ranking(payments, reconcile(payments, sales, DAY), DAY)
    assert [c["client"] for c in ranking] == ["BIG (2547****002)", "SMALL (2547****001)"]
    assert ranking[0]["items"] == ["Speaker"]
    assert ranking[1]["total"] == 1300 and ranking[1]["count"] == 2


def test_same_name_different_phone_are_different_clients():
    payments = [pay("1", 9, 0, 500, "JOHN", "2547****111"), pay("2", 9, 5, 500, "JOHN", "2547****222")]
    assert len(client_ranking(payments, reconcile(payments, [], DAY), DAY)) == 2


def test_statement_parser_keeps_masked_phone_reference(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("Receipt No,Completion Time,Details,Transaction Status,Paid In,Withdrawn,Balance\n"
                 "AAA,2026-10-07 10:00:00,Funds received from 0712345678 - JANE DOE,Completed,500,,500\n")
    p = load_statement(f)[0]
    assert p.payer == "JANE DOE" and p.payer_ref == "2547****678"


# ---- database
def test_import_is_idempotent_and_history_joins_client_to_item(tmp_path):
    payments = [pay("R1", 10, 1, 800, "JANE", "2547****555")]
    sales = [sale("S1", 10, 0, 800, "Charger"), sale("S2", 11, 0, 450, "Cable", method="cash")]
    conn = db.connect(tmp_path / "t.db")
    assert db.save_payments(conn, payments) == 1 and db.save_sales(conn, sales) == 2
    db.save_matches(conn, payments, sales)
    assert db.save_payments(conn, payments) == 0 and db.save_sales(conn, sales) == 0  # no duplicates
    rows = db.sales_history(conn)
    assert len(rows) == 2
    charger = [r for r in rows if r["item"] == "Charger"][0]
    assert charger["client"] == "JANE" and charger["receipt"] == "R1"
    assert [r["item"] for r in db.sales_history(conn, client="jan")] == ["Charger"]
    assert [r["item"] for r in db.sales_history(conn, item="cab")] == ["Cable"]
    conn.close()


# ---- stock alerts
def test_alert_fires_once_when_crossing_reorder_level():
    first, state = alerts.evaluate([item("a", 4)], {}, NOW)
    assert [(i.sku, k) for i, k in first] == [("a", "low")]
    again, state = alerts.evaluate([item("a", 4)], state, NOW + timedelta(days=1))
    assert again == []


def test_going_from_6_to_4_still_alerts_even_though_never_exactly_5():
    ok, state = alerts.evaluate([item("a", 6)], {}, NOW)
    assert ok == []
    low, _ = alerts.evaluate([item("a", 4)], state, NOW + timedelta(days=1))
    assert [k for _, k in low] == ["low"]


def test_out_of_stock_escalates_and_reminder_after_a_week():
    _, state = alerts.evaluate([item("a", 3)], {}, NOW)
    out, state = alerts.evaluate([item("a", 0)], state, NOW + timedelta(days=1))
    assert [k for _, k in out] == ["out"]
    quiet, state = alerts.evaluate([item("a", 0)], state, NOW + timedelta(days=3))
    assert quiet == []
    remind, _ = alerts.evaluate([item("a", 0)], state, NOW + timedelta(days=9))
    assert [k for _, k in remind] == ["reminder"]


def test_restock_resets_so_next_drop_alerts_again():
    _, state = alerts.evaluate([item("a", 3)], {}, NOW)
    _, state = alerts.evaluate([item("a", 20)], state, NOW + timedelta(days=1))
    again, _ = alerts.evaluate([item("a", 2)], state, NOW + timedelta(days=2))
    assert [k for _, k in again] == ["low"]


def test_message_lists_out_of_stock_first():
    flagged, _ = alerts.evaluate([item("low", 2), item("gone", 0)], {}, NOW)
    lines = alerts.format_message("Shop", flagged).splitlines()
    assert "OUT OF STOCK" in lines[1]


def test_telegram_notifier_posts_to_bot_api(monkeypatch):
    seen = {}

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def fake_urlopen(request, timeout=0):
        seen["url"], seen["data"] = request.full_url, request.data.decode()
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    alerts.TelegramNotifier("TOKEN", "42").send("hello")
    assert seen["url"] == "https://api.telegram.org/botTOKEN/sendMessage"
    assert "chat_id=42" in seen["data"] and "text=hello" in seen["data"]


def test_telegram_needs_environment_variables(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(SystemExit):
        alerts.TelegramNotifier.from_env()
