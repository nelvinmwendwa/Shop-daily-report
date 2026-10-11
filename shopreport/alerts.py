"""Low-stock alerts that fire once when stock crosses the line, not on every run.

Rules
- State per item: ok (above reorder level), low (at or below it), out (zero or less).
- Alert when an item newly becomes low or out.
- While it stays low, remind again only after `reminder_days` (default 7).
- When stock recovers to ok, the state resets silently.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import timedelta


def stock_state(item):
    if item.qty_on_hand <= 0:
        return "out"
    if item.qty_on_hand <= item.reorder_level:
        return "low"
    return "ok"


def evaluate(inventory, previous, now, reminder_days=7):
    """Return (alerts, new_state). alerts is a list of (item, kind): 'low', 'out' or 'reminder'."""
    alerts, new_state = [], {}
    for item in inventory:
        state = stock_state(item)
        old_state, alerted_at = previous.get(item.sku, ("ok", None))

        if state == "ok":
            new_state[item.sku] = ("ok", None)
            continue

        if state != old_state:  # newly low, newly out, or got worse
            alerts.append((item, state))
            new_state[item.sku] = (state, now)
        elif alerted_at is None or now - alerted_at >= timedelta(days=reminder_days):
            alerts.append((item, "reminder"))
            new_state[item.sku] = (state, now)
        else:
            new_state[item.sku] = (state, alerted_at)
    return alerts, new_state


def format_message(shop_name, alerts):
    if not alerts:
        return ""
    lines = [f"{shop_name}: restock needed"]
    labels = {"out": "OUT OF STOCK", "low": "Low", "reminder": "Still low"}
    for item, kind in sorted(alerts, key=lambda a: (a[1] != "out", a[0].qty_on_hand)):
        lines.append(f"- {item.item}: {item.qty_on_hand} left (reorder at {item.reorder_level}) [{labels[kind]}]")
    return "\n".join(lines)


class ConsoleNotifier:
    def send(self, text):
        print("\n--- ALERT MESSAGE ---\n" + text + "\n---------------------")


class TelegramNotifier:
    """Sends to a Telegram chat. Create a bot with @BotFather, then set
    TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your environment."""

    def __init__(self, token, chat_id):
        self.token, self.chat_id = token, chat_id

    @classmethod
    def from_env(cls):
        token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to use --notify telegram.")
        return cls(token, chat_id)

    def send(self, text):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as resp:
            body = json.loads(resp.read().decode())
        if not body.get("ok"):
            raise RuntimeError(f"Telegram rejected the message: {body}")
