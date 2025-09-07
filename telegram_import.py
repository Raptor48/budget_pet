import argparse
import json
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests


API_BASE_URL = os.getenv("API_BASE_URL", "https://fastapi-production-eadf.up.railway.app")


def load_messages(json_path: str) -> Iterable[Dict[str, Any]]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("messages", [])


def extract_text(msg_text_field: Any) -> str:
    if isinstance(msg_text_field, str):
        return msg_text_field
    if isinstance(msg_text_field, list):
        parts: List[str] = []
        for item in msg_text_field:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text_val = item.get("text")
                if isinstance(text_val, str):
                    parts.append(text_val)
        return "".join(parts)
    return ""


def parse_amount_and_category(text: str) -> Optional[Tuple[str, float]]:
    import re

    candidate = text.strip()
    if not candidate:
        return None

    # Skip bot commands and system messages
    skip_patterns = [
        r"^/",  # Bot commands like /start, /help, /setlimit
        r"^OK:",  # Bot confirmations like "OK: Food +25.00"
        r"^Отчёт",  # Reports
        r"^Report",  # Reports
        r"^Привет",  # Greetings
        r"^Hello",  # Greetings
        r"^Твой user_id",  # User ID messages
        r"^Your user_id",  # User ID messages
        r"^Формат:",  # Format instructions
        r"^Format:",  # Format instructions
        r"^Команды:",  # Commands list
        r"^Commands:",  # Commands list
        r"^setlimit",  # Set limit commands
        r"^limits",  # Limits commands
        r"^month",  # Month commands
        r"^report",  # Report commands
    ]
    
    for pattern in skip_patterns:
        if re.match(pattern, candidate, re.IGNORECASE):
            return None

    # Pattern A: "User added Category $amount" (bot confirmation messages)
    m = re.match(r"^[A-Za-zА-Яа-яёЁ\s]+\s+added\s+([A-Za-zА-Яа-яёЁ ,&/]+?)\s*\$?\s*([0-9]+(?:[.,][0-9]+)?)$", candidate)
    if m:
        category = m.group(1).strip()
        amount_str = m.group(2).replace(",", ".")
        try:
            amount = float(amount_str)
            if category and amount > 0:  # Only positive amounts
                return category, amount
        except ValueError:
            pass

    # Pattern B: Category first, then amount (optional $) - only for simple user messages
    m = re.match(r"^([A-Za-zА-Яа-яёЁ ,&/]+?)\s*\$?\s*([0-9]+(?:[.,][0-9]+)?)$", candidate)
    if m:
        category = m.group(1).strip()
        amount_str = m.group(2).replace(",", ".")
        try:
            amount = float(amount_str)
            # Additional validation: category should not contain command keywords
            if (category and amount > 0 and 
                not any(cmd in category.lower() for cmd in ['setlimit', 'limits', 'month', 'report', 'help', 'start'])):
                return category, amount
        except ValueError:
            pass

    # Pattern C: Amount first, then category - only for simple user messages
    m = re.match(r"^\$?\s*([0-9]+(?:[.,][0-9]+)?)\s+([A-Za-zА-Яа-яёЁ ,&/]+)$", candidate)
    if m:
        amount_str = m.group(1).replace(",", ".")
        category = m.group(2).strip()
        try:
            amount = float(amount_str)
            # Additional validation: category should not contain command keywords
            if (category and amount > 0 and 
                not any(cmd in category.lower() for cmd in ['setlimit', 'limits', 'month', 'report', 'help', 'start'])):
                return category, amount
        except ValueError:
            pass

    return None


def date_to_ymd(date_iso: str) -> str:
    # Telegram export like: 2025-09-06T14:55:47
    try:
        dt = datetime.fromisoformat(date_iso)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        # Fallback: first 10 chars
        return date_iso[:10]


def month_of(date_ymd: str) -> str:
    return date_ymd[:7]


def fetch_existing_for_month(session: requests.Session, month: str) -> Set[Tuple[str, float, str]]:
    url = f"{API_BASE_URL}/expenses"
    r = session.get(url, params={"month": month}, timeout=30)
    r.raise_for_status()
    existing = set()
    for exp in r.json():
        category = str(exp.get("category", "")).strip().lower()
        amount = float(exp.get("amount", 0.0))
        date = str(exp.get("date", ""))
        existing.add((category, round(amount, 2), date))
    return existing


def post_expense(session: requests.Session, category: str, amount: float, date_ymd: str) -> None:
    url = f"{API_BASE_URL}/expenses"
    payload = {"category": category, "amount": amount, "date": date_ymd}
    r = session.post(url, json=payload, timeout=30)
    r.raise_for_status()


def collect_from_telegram(
    messages: Iterable[Dict[str, Any]],
    since: Optional[str],
    until: Optional[str],
    user_only: bool,
    bot_from_id: str,
) -> List[Tuple[str, float, str]]:
    results: List[Tuple[str, float, str]] = []
    for msg in messages:
        if msg.get("type") != "message":
            continue

        # Skip bot messages when user_only enabled
        if user_only and str(msg.get("from_id", "")) == bot_from_id:
            continue

        text = extract_text(msg.get("text"))
        parsed = parse_amount_and_category(text)
        if not parsed:
            continue

        cat, amt = parsed
        date_ymd = date_to_ymd(str(msg.get("date", "")))

        if since and date_ymd < since:
            continue
        if until and date_ymd > until:
            continue

        results.append((cat, amt, date_ymd))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Import expenses from Telegram export JSON via FastAPI")
    parser.add_argument("--file", default="frontend/result.json", help="Path to Telegram export JSON")
    parser.add_argument("--since", default=None, help="Include messages from this date (YYYY-MM-DD)")
    parser.add_argument("--until", default=None, help="Include messages up to this date (YYYY-MM-DD)")
    parser.add_argument("--apply", action="store_true", help="Apply changes (otherwise dry-run)")
    parser.add_argument(
        "--include-bot",
        action="store_true",
        help="Also parse bot messages (by default only user messages are parsed)",
    )
    parser.add_argument(
        "--bot-from-id",
        default="user8134194690",
        help="From ID that identifies bot messages in export (default: user8134194690)",
    )

    args = parser.parse_args()

    messages = list(load_messages(args.file))

    parsed = collect_from_telegram(
        messages=messages,
        since=args.since,
        until=args.until,
        user_only=not args.include_bot,
        bot_from_id=args.bot_from_id,
    )

    if not parsed:
        print("No candidate expenses found in Telegram export.")
        return

    # Group by month for efficient de-duplication against API
    months: Set[str] = {month_of(d) for _, _, d in parsed}

    session = requests.Session()

    existing_map: Dict[str, Set[Tuple[str, float, str]]] = {}
    for m in sorted(months):
        existing_map[m] = fetch_existing_for_month(session, m)

    # Compute new items (skip duplicates by (category, amount, date))
    to_add: List[Tuple[str, float, str]] = []
    for cat, amt, date_ymd in parsed:
        key = (cat.strip().lower(), round(amt, 2), date_ymd)
        if key not in existing_map.get(month_of(date_ymd), set()):
            to_add.append((cat, amt, date_ymd))

    # Dry-run report
    print(f"Found {len(parsed)} candidate messages; {len(to_add)} to add after de-dup.")

    # Brief preview (first 20)
    for i, (cat, amt, date_ymd) in enumerate(to_add[:20], start=1):
        print(f"[{i:02d}] {date_ymd}  {cat}  {amt:.2f}")
    if len(to_add) > 20:
        print(f"... and {len(to_add) - 20} more")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to import.")
        return

    # Apply
    added = 0
    for cat, amt, date_ymd in to_add:
        post_expense(session, cat, amt, date_ymd)
        added += 1
    print(f"Imported {added} expenses into API {API_BASE_URL}.")


if __name__ == "__main__":
    main()


