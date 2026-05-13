"""
Cash-entry text parser — deterministic regex pass with an optional LLM
fallback for free-form input.

Two layers:

1. :func:`parse_deterministic` — handles the bot's classic shorthand:

   * ``5 coffee`` / ``120 grocery`` (number-first)
   * ``12,50 lunch`` / ``5.50 latte`` (decimal separators)
   * ``$5 coffee`` / ``5$ coffee`` / ``5 € lunch`` (currency tokens)
   * ``такси 400`` / ``coffee 5`` (number-last)
   * ``400р такси домой`` / ``5usd coffee`` (currency suffix without space)

   Returns ``(amount_cents, name)`` or ``None`` when nothing parses.

2. :func:`parse_with_llm` — optional fallback when the deterministic
   parser fails AND :env:`OPENAI_API_KEY` is set AND the per-user daily
   quota is not yet exhausted. Uses ``gpt-4o-mini`` (same model as OCR
   for billing parity) with a strict JSON contract:

       {"amount_cents": int|null, "currency": str, "name": str, "is_private": bool}

   Returns the same shape as the deterministic layer plus a ``meta`` dict
   so the caller can decide whether to surface a "categorise this?"
   correction button.

Privacy considerations:

* The LLM only sees the user's free-form text — no transactions, no
  category list, no household members. Prompt-injection from the input
  is bounded by ``response_format=json_object`` + temperature 0.
* The fallback is *opt-in via env*: without ``OPENAI_API_KEY`` this
  module silently no-ops the LLM path and the bot falls through to its
  existing "Try `5 coffee`" response. A failing API call also no-ops
  rather than surfacing an error to the user — the worst case is the
  same UX they had before this layer was introduced.

Daily quota:

* :func:`record_llm_call` upserts a counter into ``bot_llm_usage``.
* :func:`llm_quota_remaining` returns how many calls the user has left
  today. Default cap is 30/day, override via ``BOT_LLM_DAILY_QUOTA``.
* The quota is per-user and resets at UTC midnight.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

# Imported at module level so tests can ``patch("web.telegram.cash_parser.get_pool", …)``
# without first reaching into the function body. The symbol is only used by
# the quota-tracking helpers below.
from web.db import get_pool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic parser
# ---------------------------------------------------------------------------

# Match a positive number with optional one-or-two-digit fractional part.
# Both ``,`` and ``.`` are accepted as the separator. The number must be
# delimited by start-of-string, whitespace, or a currency token — so
# ``12abc`` doesn't extract ``12``.
_AMOUNT_RE = re.compile(
    r"(?:^|\s|[$€₽£¥])(\d+(?:[.,]\d{1,2})?)(?:\s|$|[$€₽£¥а-яА-Яa-zA-Z])"
)
# Currency tokens we strip from the leftover description so it doesn't
# read as ``р такси домой``. The list intentionally covers the inputs
# we've actually seen in user testing — Russian/English/Euro — rather
# than every ISO 4217 code.
_CURRENCY_TOKENS = {
    "$", "€", "₽", "£", "¥",
    "р", "р.", "руб", "руб.", "рубль", "рублей",
    "$.", "usd", "eur", "rub", "gbp", "jpy",
    "доллар", "долларов", "евро",
}


def parse_deterministic(text: str) -> Optional[Tuple[int, str]]:
    """Best-effort regex extraction. Returns ``None`` when the input
    has no number we can confidently treat as an amount.

    Picks the FIRST number match, not the largest — bot conventions are
    "amount first" or "amount last", and giving "I bought 2 apples for
    5" the value ``5`` is more natural than ``2``. When the only number
    is a tiny fraction like ``0.05``, we still return it; weeding out
    "implausibly small" amounts is the caller's job.
    """
    if not text or not text.strip():
        return None

    # Find every plausible number. Use ``finditer`` so we know where the
    # match was and can splice it out of the description.
    matches = list(_AMOUNT_RE.finditer(text))
    if not matches:
        # Maybe the entire text is just a number — covered by a simpler
        # fallback regex without surrounding-token requirements.
        bare = re.fullmatch(r"\s*(\d+(?:[.,]\d{1,2})?)\s*", text)
        if bare:
            try:
                amount = float(bare.group(1).replace(",", "."))
            except ValueError:
                return None
            if amount <= 0:
                return None
            return int(round(amount * 100)), "Cash spend"
        return None

    # First match wins; that's how the user's mental model works for
    # "5 coffee" and "такси 400" alike.
    first = matches[0]
    raw_num = first.group(1)
    try:
        amount = float(raw_num.replace(",", "."))
    except ValueError:
        return None
    if amount <= 0:
        return None
    # Splice the matched number out, leaving the surrounding tokens.
    # ``first.start(1)`` / ``first.end(1)`` point at the number itself,
    # not the regex's bracket characters.
    desc_left = text[: first.start(1)]
    desc_right = text[first.end(1):]
    desc = (desc_left + " " + desc_right).strip()
    desc = _strip_currency_tokens(desc)
    if not desc:
        desc = "Cash spend"
    return int(round(amount * 100)), desc


def _strip_currency_tokens(text: str) -> str:
    """Remove standalone currency-marker words ($, р, руб, USD, …) and
    collapse the resulting whitespace runs."""
    if not text:
        return text
    # Split on whitespace but preserve original casing for non-currency
    # tokens (so the user's "Coffee" stays "Coffee", not "coffee").
    out = []
    for raw in text.split():
        normalized = raw.lower().rstrip(".,!?")
        if normalized in _CURRENCY_TOKENS:
            continue
        # Strip trailing currency symbols glued to the token (e.g. "5р").
        stripped = raw
        for sym in ("$", "€", "₽", "£", "¥"):
            stripped = stripped.replace(sym, "")
        if not stripped:
            continue
        out.append(stripped)
    return " ".join(out).strip()


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------


_LLM_PROMPT = """You receive a single short message from a household budgeting chat.
Extract the cash spend the user is logging. Return STRICT JSON with keys:

  "amount_cents": int | null  // total spend in minor units; null if no amount is present
  "currency":     str         // ISO 4217 if obvious; otherwise "USD"
  "name":         str         // 1-4 word description of the spend (lowercase, no quotes)
  "is_private":   bool        // true ONLY if the user explicitly says "приват", "private", "secret", "hidden", "🤫"; otherwise false

Examples:
  IN  "400р такси домой"           → {"amount_cents": 40000, "currency": "RUB", "name": "такси домой", "is_private": false}
  IN  "$12 lunch private"          → {"amount_cents": 1200, "currency": "USD", "name": "lunch", "is_private": true}
  IN  "coffee with mark 5.50"      → {"amount_cents": 550, "currency": "USD", "name": "coffee with mark", "is_private": false}
  IN  "не помню сколько такси"     → {"amount_cents": null, "currency": "USD", "name": "такси", "is_private": false}

Do NOT include any prose around the JSON.
"""


def llm_enabled() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


def _llm_timeout() -> float:
    try:
        return float(os.getenv("BOT_LLM_TIMEOUT", "8"))
    except ValueError:
        return 8.0


def _llm_model() -> str:
    return (os.getenv("BOT_LLM_MODEL") or "gpt-4o-mini").strip()


async def parse_with_llm(text: str) -> Optional[Dict[str, Any]]:
    """Run the LLM fallback. Returns a dict shaped like::

        {
            "amount_cents": int,
            "currency": str,
            "name": str,
            "is_private": bool,
            "source": "llm",
        }

    or ``None`` when the model couldn't extract an amount, when the API
    is misconfigured, or when the call errored out. The caller treats
    ``None`` exactly like a deterministic-parser miss — show the
    "Try `5 coffee`" hint and move on.

    Errors are *deliberately* swallowed. We never want to surface
    "OpenAI 502" to a user typing ``5 coffee`` — they'd be confused. The
    OCR module surfaces backend errors because the user explicitly took
    a photo expecting parsing; this layer is invisible UX magic.
    """
    if not llm_enabled():
        return None
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > 200:
        # Defence-in-depth: free-text > 200 chars is almost certainly not
        # a cash entry. Skip the round trip.
        return None

    import asyncio

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_openai_text, text),
            timeout=_llm_timeout(),
        )
    except (asyncio.TimeoutError, Exception) as exc:
        logger.info("LLM cash-entry fallback failed (%s); ignoring", exc)
        return None


def _run_openai_text(text: str) -> Optional[Dict[str, Any]]:
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=_llm_model(),
        messages=[
            {"role": "system", "content": _LLM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        timeout=_llm_timeout(),
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.info("LLM cash-entry returned non-JSON: %r", raw[:120])
        return None
    if not isinstance(data, dict):
        return None
    return _normalize_llm_output(data)


def _normalize_llm_output(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw_amount = data.get("amount_cents")
    if raw_amount is None or isinstance(raw_amount, bool):
        return None
    try:
        amount = int(raw_amount)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    name = (data.get("name") or "").strip() or "Cash spend"
    # Hard-cap the description so an unbounded LLM response doesn't
    # become a 1000-char merchant_name. ``transactions.name`` is TEXT
    # but the UI expects something tweet-sized.
    if len(name) > 80:
        name = name[:80].rstrip()
    raw_curr = (data.get("currency") or "USD").strip().upper()
    currency = "".join(ch for ch in raw_curr if ch.isalpha())[:3] or "USD"
    is_private = bool(data.get("is_private"))
    return {
        "amount_cents": amount,
        "currency": currency,
        "name": name,
        "is_private": is_private,
        "source": "llm",
    }


# ---------------------------------------------------------------------------
# Per-user daily quota
# ---------------------------------------------------------------------------


def daily_quota() -> int:
    try:
        return max(0, int(os.getenv("BOT_LLM_DAILY_QUOTA", "30")))
    except ValueError:
        return 30


async def llm_quota_remaining(user_id: int, today: Optional[date] = None) -> int:
    """How many LLM calls the user has left today. Returns the quota
    cap when there's no recorded usage yet."""
    cap = daily_quota()
    if cap <= 0:
        return 0
    used = await _llm_calls_today(user_id, today or _today_utc())
    return max(0, cap - used)


async def record_llm_call(user_id: int, today: Optional[date] = None) -> None:
    """Bump the per-user counter. Idempotent at the row level via
    ON CONFLICT, so concurrent callers can't lose increments."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_llm_usage (user_id, day, calls)
            VALUES ($1, $2, 1)
            ON CONFLICT (user_id, day) DO UPDATE
                SET calls = bot_llm_usage.calls + 1
            """,
            user_id,
            today or _today_utc(),
        )


async def _llm_calls_today(user_id: int, today: date) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT calls FROM bot_llm_usage WHERE user_id = $1 AND day = $2",
            user_id,
            today,
        )
    return int(val or 0)


def _today_utc() -> date:
    """UTC day boundary for quota reset. Doesn't try to honour the
    user's TZ — quotas are about preventing cost runaway, not lining
    up with the user's morning."""
    return datetime.now(timezone.utc).date()
