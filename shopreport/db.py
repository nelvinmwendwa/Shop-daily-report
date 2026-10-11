"""SQLite storage so history builds up day after day (standard library only).

Imports are idempotent: running the same statement twice never creates duplicates,
because M-Pesa receipt numbers and sale ids are primary keys.
"""

import sqlite3
from datetime import datetime

from .analysis import reconcile

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments(
    receipt TEXT PRIMARY KEY, time TEXT NOT NULL, details TEXT, payer TEXT, payer_ref TEXT,
    paid_in REAL, withdrawn REAL, balance REAL);
CREATE TABLE IF NOT EXISTS sales(
    sale_id TEXT PRIMARY KEY, time TEXT NOT NULL, sku TEXT, item TEXT, qty INTEGER,
    amount REAL, method TEXT);
CREATE TABLE IF NOT EXISTS matches(
    receipt TEXT PRIMARY KEY, sale_id TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS stock_alerts(
    sku TEXT PRIMARY KEY, state TEXT NOT NULL, alerted_at TEXT);
"""


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def connect(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_payments(conn, payments):
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO payments VALUES (?,?,?,?,?,?,?,?)",
        [(p.receipt, _ts(p.time), p.details, p.payer, p.payer_ref, p.paid_in, p.withdrawn, p.balance) for p in payments],
    )
    conn.commit()
    return conn.total_changes - before


def save_sales(conn, sales):
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO sales VALUES (?,?,?,?,?,?,?)",
        [(s.sale_id, _ts(s.time), s.sku, s.item, s.qty, s.amount, s.method) for s in sales],
    )
    conn.commit()
    return conn.total_changes - before


def save_matches(conn, payments, sales):
    """Run reconciliation for every day in the data and remember which payment paid for which sale."""
    days = sorted({p.time.date() for p in payments} | {s.time.date() for s in sales})
    for day in days:
        result = reconcile(payments, sales, day)
        conn.executemany(
            "INSERT OR IGNORE INTO matches VALUES (?,?)",
            [(p.receipt, s.sale_id) for p, s in result.matched],
        )
    conn.commit()


def load_alert_state(conn):
    state = {}
    for row in conn.execute("SELECT sku, state, alerted_at FROM stock_alerts"):
        alerted = datetime.strptime(row["alerted_at"], "%Y-%m-%d %H:%M:%S") if row["alerted_at"] else None
        state[row["sku"]] = (row["state"], alerted)
    return state


def save_alert_state(conn, state):
    conn.executemany(
        "INSERT OR REPLACE INTO stock_alerts VALUES (?,?,?)",
        [(sku, st, _ts(at) if at else None) for sku, (st, at) in state.items()],
    )
    conn.commit()


def sales_history(conn, client=None, item=None, since=None):
    """Every sale ever recorded, with the matched M-Pesa client where known (newest first)."""
    sql = (
        "SELECT s.time, s.sale_id, s.item, s.qty, s.amount, s.method,"
        " COALESCE(p.payer,'') AS client, COALESCE(p.payer_ref,'') AS client_ref,"
        " COALESCE(p.receipt,'') AS receipt"
        " FROM sales s LEFT JOIN matches m ON m.sale_id = s.sale_id"
        " LEFT JOIN payments p ON p.receipt = m.receipt WHERE 1=1"
    )
    params = []
    if client:
        sql += " AND p.payer LIKE ?"
        params.append(f"%{client}%")
    if item:
        sql += " AND s.item LIKE ?"
        params.append(f"%{item}%")
    if since:
        sql += " AND s.time >= ?"
        params.append(since + " 00:00:00")
    sql += " ORDER BY s.time DESC"
    return [dict(row) for row in conn.execute(sql, params)]


def counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("payments", "sales", "matches")}
