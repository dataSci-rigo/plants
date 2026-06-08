#!/usr/bin/env python3
"""
Telegram pinger — randomly asks what you're doing and records your response.

Run:  python pinger.py
Stop: Ctrl-C  (safe — pending state is saved and resumed on next start)

Output: pings.json  (one entry per exchange)
"""
import json
import os
import random
import string
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")
BASE = f"https://api.telegram.org/bot{TOKEN}"

PINGS_FILE = Path(__file__).parent / "pings.json"
STATE_FILE = Path(__file__).parent / "pinger_state.json"

MIN_WAIT_MIN = 30   # shortest gap between pings
MAX_WAIT_MIN = 180  # longest gap between pings

QUESTION = "What are you doing?"


# ── helpers ──────────────────────────────────────────────────────────────────

def gen_code() -> str:
    """4-character alphanumeric code, e.g. A3X9."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=4))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2))


# ── Telegram API ─────────────────────────────────────────────────────────────

def tg(method: str, *, timeout: int = 10, **payload):
    resp = requests.post(f"{BASE}/{method}", json=payload or None, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_updates(offset: int) -> list:
    """Long-poll for new updates (blocks up to 30 s)."""
    data = requests.get(
        f"{BASE}/getUpdates",
        params={"timeout": 30, "offset": offset, "limit": 20},
        timeout=40,
    ).json()
    return data.get("result", [])


def drain_updates(offset: int) -> int:
    """Consume all pending updates and return the new offset."""
    while True:
        updates = get_updates(offset)
        if not updates:
            return offset
        offset = updates[-1]["update_id"] + 1


def send_ping(code: str) -> int:
    """Send the ping message; return Telegram's unix timestamp for the sent message."""
    result = tg("sendMessage", chat_id=int(OWNER_CHAT_ID), text=f"[{code}] {QUESTION}")
    return result["result"]["date"]


# ── core logic ────────────────────────────────────────────────────────────────

def poll_for_reply(
    code: str,
    sent_at_iso: str,
    sent_at_unix: int,
    offset: int,
) -> tuple[dict, int]:
    """
    Block until the owner sends a message containing the code.
    Returns (log entry, updated offset).
    """
    print(f"  Waiting for reply with code [{code}] …")

    while True:
        updates = get_updates(offset)

        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message")

            if not msg:
                continue
            if str(msg["chat"]["id"]) != str(OWNER_CHAT_ID):
                continue
            if msg["date"] <= sent_at_unix:
                continue                         # message predates our ping
            if code not in msg.get("text", "").upper():
                continue                         # code not present

            replied_at = datetime.fromtimestamp(msg["date"], tz=timezone.utc).isoformat()
            sent_dt = datetime.fromisoformat(sent_at_iso)
            reply_dt = datetime.fromisoformat(replied_at)
            elapsed = round((reply_dt - sent_dt).total_seconds())

            entry = {
                "code": code,
                "question": QUESTION,
                "sent_at": sent_at_iso,
                "replied_at": replied_at,
                "response_time_seconds": elapsed,
                "answer": msg["text"],
            }
            print(f"  Reply received in {elapsed}s: {msg['text']!r}")
            return entry, offset

        # Persist the latest offset so a restart doesn't reprocess old messages
        state = load_json(STATE_FILE, {})
        if state:
            state["update_offset"] = offset
            save_json(STATE_FILE, state)


def record(entry: dict) -> None:
    pings = load_json(PINGS_FILE, [])
    pings.append(entry)
    save_json(PINGS_FILE, pings)
    print(f"  Saved to {PINGS_FILE}  ({len(pings)} total entries)")


# ── main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    if not TOKEN:
        raise ValueError("TELEGRAM_TOKEN not set in .env")
    if not OWNER_CHAT_ID:
        raise ValueError("OWNER_CHAT_ID not set in .env")

    offset = 0
    state = load_json(STATE_FILE, {})

    # Resume a ping that was left pending from the last run
    if state.get("pending_code"):
        code        = state["pending_code"]
        sent_at_iso = state["sent_at_iso"]
        sent_at_unix = state["sent_at_unix"]
        offset      = state.get("update_offset", 0)
        print(f"Resuming pending ping [{code}] from {sent_at_iso}")
        entry, offset = poll_for_reply(code, sent_at_iso, sent_at_unix, offset)
        record(entry)
        STATE_FILE.unlink(missing_ok=True)

    while True:
        wait_min = random.uniform(MIN_WAIT_MIN, MAX_WAIT_MIN)
        print(f"\nNext ping in {wait_min:.1f} min …")
        time.sleep(wait_min * 60)

        # Drain any messages that arrived while we were sleeping
        offset = drain_updates(offset)

        code        = gen_code()
        sent_at_iso = now_iso()
        sent_at_unix = send_ping(code)
        print(f"Ping sent [{code}] at {sent_at_iso}")

        # Persist state before polling — survive a crash/restart
        save_json(STATE_FILE, {
            "pending_code": code,
            "sent_at_iso":  sent_at_iso,
            "sent_at_unix": sent_at_unix,
            "update_offset": offset,
        })

        entry, offset = poll_for_reply(code, sent_at_iso, sent_at_unix, offset)
        record(entry)
        STATE_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped. State saved — re-run to resume any pending ping.")
