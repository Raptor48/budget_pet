"""
RecurringRepository — DB operations for recurring_streams.
Handles upsert from Plaid /transactions/recurring/get response,
price change detection (threshold 10%), and user label updates.
"""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from web.accounts.repo import AccountsRepository
from web.categories.pfc_display import format_plaid_category_for_display
from web.db import get_pool
from web.transactions.display import normalize_transaction_title

logger = logging.getLogger(__name__)

PRICE_CHANGE_THRESHOLD = 0.10  # 10%

# Grace window stacked onto the next expected charge date before the
# verifier is allowed to confirm an unsubscribe. Covers Plaid lag
# (typically 1-2 days), bank settlement (T+1…T+3), and weekend posting.
UNSUBSCRIBE_VERIFY_GRACE_DAYS = 7

# Cadences for which the verifier auto-flips to ``cancelled`` when no
# charge is detected after the grace period. ``ANNUALLY`` is deliberately
# out — waiting 13 months to confirm is silly UX. ``UNKNOWN`` is out
# because Plaid uses it for irregular bills (utilities by meter read)
# where "no charge this cycle" is normal, not a signal of cancellation.
_AUTO_VERIFIABLE_CADENCES = frozenset(
    {"WEEKLY", "BIWEEKLY", "SEMI_MONTHLY", "MONTHLY"}
)


def _compute_unsubscribe_verify_after(
    last_date: Optional[date],
    frequency: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    """Earliest UTC moment the verifier is allowed to act on an unsubscribe.

    Returns ``None`` for cadences we won't auto-verify (``ANNUALLY``,
    ``UNKNOWN``, missing data) — those streams stay in the ``unsubscribed``
    state indefinitely until the user finalises manually or Plaid itself
    tombstones the stream.

    For verifiable cadences: ``next_future_occurrence(last_date, freq) +
    UNSUBSCRIBE_VERIFY_GRACE_DAYS``. The grace covers banking + Plaid lag.
    """
    if not last_date or not frequency:
        return None
    freq = frequency.upper()
    if freq not in _AUTO_VERIFIABLE_CADENCES:
        return None
    # Local import to break the import cycle: reports.calculations does not
    # depend on recurring; recurring depends on reports.calculations only
    # at runtime.
    from web.reports.calculations import next_future_occurrence

    today_local = (now or datetime.now(timezone.utc)).date()
    nxt = next_future_occurrence(last_date, freq, today=today_local)
    if nxt is None:
        return None
    return datetime.combine(
        nxt + timedelta(days=UNSUBSCRIBE_VERIFY_GRACE_DAYS),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )


def _coerce_last_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def _sort_streams_by_next_payment(rows: List[Dict[str, Any]]) -> None:
    """In-place: soonest *future* payment first (uses
    ``next_future_occurrence`` so streams whose last_date is several
    cadences behind don't sort by a date in the past); unknown last."""
    # Local import avoids import cycle: reports.routes imports this repo.
    from web.reports.calculations import next_future_occurrence

    def sort_key(row: Dict[str, Any]) -> tuple:
        last_d = _coerce_last_date(row.get("last_date"))
        freq = (row.get("frequency") or "").strip()
        if not last_d or not freq:
            return (1, date.max, row.get("id") or 0)
        nxt = next_future_occurrence(last_d, freq)
        if nxt is None:
            return (1, date.max, row.get("id") or 0)
        return (0, nxt, row.get("id") or 0)

    rows.sort(key=sort_key)


class RecurringRepository:
    async def _pool(self):
        return await get_pool()

    async def list_streams(
        self,
        direction: Optional[str] = None,
        active_only: bool = True,
        viewer_user_id: Optional[int] = None,
        include_user_statuses: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """List recurring streams, enriched with account + owner + primary
        category metadata so the UI can render "Charged to <card · @owner>"
        and a collapsed "Category" column without N+1 follow-up fetches.

        The returned dict follows `RecurringStreamOut`'s enrichment contract:
        `account_name`, `account_mask`, `owner_username`,
        `primary_category_{id,name,color}`, and `display_title`.

        When ``viewer_user_id`` is set (e.g. Insights), streams whose underlying
        account is owned by a *different* user are filtered out. Shared accounts
        (``accounts.user_id IS NULL``) remain visible. ``GET /api/recurring``
        passes ``viewer_user_id=None`` for a single household-wide list.

        ``include_user_statuses`` filters by the user-managed lifecycle column
        (``user_status``). Default = ``['active', 'paused']`` so cancelled
        streams stay archived but still queryable on demand. Pass
        ``['active', 'paused', 'cancelled']`` (or ``None`` + an unrelated
        callsite) to opt out of the filter.

        Results are sorted by computed next payment date (``next_occurrence``),
        soonest first; rows without a computable next date sort last.
        """
        pool = await self._pool()
        conditions: List[str] = []
        params: List[Any] = []
        idx = 1
        if direction:
            conditions.append(f"rs.direction = ${idx}")
            params.append(direction)
            idx += 1
        if active_only:
            conditions.append("rs.is_active = TRUE")
        if include_user_statuses is None:
            # ``unsubscribed`` is a pending-verification state — we keep
            # it visible alongside active/paused so the user can see the
            # "we'll verify this in N days" pill, and cancel the
            # cancellation if they change their mind.
            include_user_statuses = ["active", "paused", "unsubscribed"]
        if include_user_statuses:
            conditions.append(f"rs.user_status = ANY(${idx}::text[])")
            params.append(list(include_user_statuses))
            idx += 1
        if viewer_user_id is not None:
            conditions.append(f"(a.user_id = ${idx} OR a.user_id IS NULL)")
            params.append(viewer_user_id)
            idx += 1
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        # Plaid's recurring endpoint does not return ``merchant_entity_id``,
        # only ``merchant_name`` — so we match aliases by the ``name:`` key
        # path. ``upsert_alias`` writes both ``eid:`` and ``name:`` rows for
        # any merchant where both are available, so an alias created from a
        # transaction also resolves here.
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    rs.*,
                    a.name                 AS account_name,
                    a.mask                 AS account_mask,
                    u.username             AS owner_username,
                    c.parent_id            AS category_parent_id,
                    COALESCE(pc.id, c.id)     AS primary_category_id,
                    COALESCE(pc.name, c.name) AS primary_category_name,
                    COALESCE(pc.color, c.color) AS primary_category_color,
                    ma.display_name           AS merchant_alias,
                    merchant_logos.logo_url   AS logo_url
                FROM recurring_streams rs
                LEFT JOIN accounts a   ON a.id = rs.account_id
                LEFT JOIN users u      ON u.id = a.user_id
                LEFT JOIN categories c ON c.id = rs.category_id
                LEFT JOIN categories pc ON pc.id = c.parent_id
                LEFT JOIN merchant_aliases ma ON ma.merchant_key =
                    'name:' || lower(NULLIF(TRIM(rs.merchant_name), ''))
                -- Plaid's recurring endpoint doesn't return logos, but
                -- transactions.logo_url has them for the same merchant.
                -- Picking the most recent non-null logo per merchant_name
                -- once, then hash-joining onto rs, avoids a per-stream
                -- LATERAL seq-scan. No `lower()` because Plaid returns
                -- merchant_name consistently cased within a merchant.
                LEFT JOIN (
                    SELECT DISTINCT ON (merchant_name)
                           merchant_name, logo_url
                    FROM transactions
                    WHERE merchant_name IS NOT NULL
                      AND logo_url      IS NOT NULL
                    ORDER BY merchant_name, date DESC NULLS LAST
                ) merchant_logos
                  ON merchant_logos.merchant_name = rs.merchant_name
                {where}
                """,
                *params,
            )
        enriched: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            d.pop("category_parent_id", None)
            d["display_title"] = normalize_transaction_title(
                {
                    # Layer the alias onto merchant_name so the
                    # title-normalizer treats it as the canonical merchant
                    # label — keeps the same precedence chain (user_label
                    # > merchant_name > description).
                    "merchant_name": d.get("merchant_alias") or d.get("merchant_name"),
                    "name": d.get("description"),
                    "description": d.get("description"),
                    "user_label": d.get("user_label"),
                }
            )
            if not (d.get("primary_category_name") or "").strip():
                fb = format_plaid_category_for_display(
                    d.get("pfc_detailed"),
                    d.get("pfc_primary"),
                )
                if fb:
                    d["primary_category_name"] = fb
            enriched.append(d)
        _sort_streams_by_next_payment(enriched)
        return enriched

    async def get_stream(self, stream_id: int) -> Optional[Dict[str, Any]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM recurring_streams WHERE id = $1", stream_id)
        return dict(row) if row else None

    async def get_price_changes(
        self, viewer_user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Return streams where |last / avg - 1| > PRICE_CHANGE_THRESHOLD.

        `price_change_pct` is stored as a *signed* percentage where a positive
        value means the latest charge exceeds the long-term average. Callers
        (insights, UI) interpret the sign against `direction` to decide whether
        a change is favourable (e.g. price drop on an outflow subscription).
        Filtering still uses the absolute magnitude so drops and increases both
        surface as notable.

        Skips:
          * cancelled streams (``user_status = 'cancelled'``);
          * snoozed alerts (``price_change_snoozed_until >= today``).

        When ``viewer_user_id`` is set, streams whose underlying account is
        owned by another user are hidden (see ``list_streams``).
        """
        pool = await self._pool()
        params: List[Any] = [PRICE_CHANGE_THRESHOLD]
        viewer_clause = ""
        if viewer_user_id is not None:
            viewer_clause = " AND (a.user_id = $2 OR a.user_id IS NULL)"
            params.append(viewer_user_id)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT rs.*
                FROM recurring_streams rs
                LEFT JOIN accounts a ON a.id = rs.account_id
                WHERE rs.is_active = TRUE
                  AND rs.user_status <> 'cancelled'
                  AND (rs.price_change_snoozed_until IS NULL
                       OR rs.price_change_snoozed_until < CURRENT_DATE)
                  AND rs.last_amount_cents IS NOT NULL
                  AND rs.average_amount_cents IS NOT NULL
                  AND rs.average_amount_cents != 0
                  AND ABS(rs.last_amount_cents - rs.average_amount_cents)::float / ABS(rs.average_amount_cents) > $1
                  {viewer_clause}
                """,
                *params,
            )
        out = [dict(r) for r in rows]
        _sort_streams_by_next_payment(out)
        return out

    async def create_manual_stream(self, user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a user-defined recurring stream (same table as Plaid; never overwritten by sync)."""
        acct = await AccountsRepository().get_account(int(data["account_id"]))
        if not acct or acct.get("user_id") != user_id:
            raise ValueError("account_not_found_or_forbidden")
        last_cents = data.get("last_amount_cents")
        if last_cents is None:
            last_cents = int(data["average_amount_cents"])
        plaid_stream_id = f"manual:{uuid.uuid4()}"
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO recurring_streams (
                    plaid_stream_id, account_id, direction, description,
                    merchant_name, frequency, average_amount_cents, last_amount_cents,
                    currency, first_date, last_date, is_active, status,
                    category_id, stream_source, last_synced_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,TRUE,'MANUAL',$12,'manual',NOW()
                )
                RETURNING *
                """,
                plaid_stream_id,
                int(data["account_id"]),
                data["direction"],
                data["description"],
                data.get("merchant_name"),
                data.get("frequency"),
                int(data["average_amount_cents"]),
                int(last_cents),
                (data.get("currency") or "USD").strip() or "USD",
                data.get("first_date"),
                data.get("last_date"),
                data.get("category_id"),
            )
        return dict(row)

    async def update_stream(
        self, stream_id: int, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        allowed = {
            "user_label",
            "category_id",
            "user_status",
            "paused_until",
            "price_change_snoozed_until",
        }
        fields = {k: v for k, v in data.items() if k in allowed}
        if not fields:
            return await self.get_stream(stream_id)

        # Side-effects on user_status transition: stamp / clear cancelled_at,
        # clear paused_until when leaving 'paused', stamp unsubscribed_at +
        # verify_after when entering 'unsubscribed'. Done as extra SET pairs
        # so a single PATCH can flip multiple fields atomically.
        if "user_status" in fields:
            new_status = fields["user_status"]
            if new_status == "cancelled":
                fields["cancelled_at"] = datetime.now()
                # Leaving 'unsubscribed' as the verified terminal state —
                # clear the verifier metadata so an immediate Plaid resync
                # can't accidentally reopen a charge alert against a
                # row the user has explicitly closed.
                fields["unsubscribed_at"] = None
                fields["unsubscribe_verify_after"] = None
            elif new_status == "active":
                fields["cancelled_at"] = None
                fields["unsubscribed_at"] = None
                fields["unsubscribe_verify_after"] = None
                fields["unsubscribed_charge_alerted_at"] = None
                # Don't drop paused_until here unless the caller didn't pass it
                # — they may be re-pausing later from a different code path.
                fields.setdefault("paused_until", None)
            elif new_status == "paused":
                fields["cancelled_at"] = None
                fields["unsubscribed_at"] = None
                fields["unsubscribe_verify_after"] = None
            elif new_status == "unsubscribed":
                fields["cancelled_at"] = None
                fields["paused_until"] = None
                fields["unsubscribed_at"] = datetime.now(timezone.utc)
                fields["unsubscribed_charge_alerted_at"] = None
                # Compute verify_after from the row's own cadence. Needs a
                # round-trip but keeps the API call atomic from the caller's
                # POV (no extra fetch + patch).
                row = await self.get_stream(stream_id)
                if row:
                    fields["unsubscribe_verify_after"] = (
                        _compute_unsubscribe_verify_after(
                            _coerce_last_date(row.get("last_date")),
                            row.get("frequency"),
                        )
                    )
                else:
                    fields["unsubscribe_verify_after"] = None

        set_clause = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(fields.keys()))
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE recurring_streams SET {set_clause} WHERE id = $1 RETURNING *",
                stream_id,
                *fields.values(),
            )
        return dict(row) if row else None

    async def bulk_apply(
        self,
        ids: List[int],
        action: str,
        paused_until: Optional[date] = None,
        snooze_days: Optional[int] = None,
    ) -> int:
        """Apply one user-state action to many streams in a single SQL round-trip.

        See ``RecurringBulkAction`` in ``models.py`` for the action contract.
        Returns the number of rows updated.
        """
        if action not in {
            "cancel",
            "pause",
            "reactivate",
            "unsubscribe",
            "snooze_price_change",
        }:
            raise ValueError(f"Unknown bulk action: {action}")
        if not ids:
            return 0
        pool = await self._pool()
        async with pool.acquire() as conn:
            if action == "cancel":
                rows = await conn.fetch(
                    """
                    UPDATE recurring_streams
                       SET user_status                  = 'cancelled',
                           cancelled_at                 = NOW(),
                           unsubscribed_at              = NULL,
                           unsubscribe_verify_after     = NULL
                     WHERE id = ANY($1::int[])
                    RETURNING id
                    """,
                    ids,
                )
            elif action == "pause":
                rows = await conn.fetch(
                    """
                    UPDATE recurring_streams
                       SET user_status              = 'paused',
                           paused_until             = $2,
                           cancelled_at             = NULL,
                           unsubscribed_at          = NULL,
                           unsubscribe_verify_after = NULL
                     WHERE id = ANY($1::int[])
                    RETURNING id
                    """,
                    ids,
                    paused_until,
                )
            elif action == "reactivate":
                rows = await conn.fetch(
                    """
                    UPDATE recurring_streams
                       SET user_status                    = 'active',
                           paused_until                   = NULL,
                           cancelled_at                   = NULL,
                           unsubscribed_at                = NULL,
                           unsubscribe_verify_after       = NULL,
                           unsubscribed_charge_alerted_at = NULL
                     WHERE id = ANY($1::int[])
                    RETURNING id
                    """,
                    ids,
                )
            elif action == "unsubscribe":
                # Bulk path: ONE atomic UPDATE, not N per-row UPDATEs.
                #
                # Originally we did `for m in meta: await conn.fetchrow(...)`
                # which works for tiny inputs but is a latency landmine
                # under contention: Plaid sync's ``upsert_streams`` holds
                # row-level locks on the same rows for the duration of
                # its ON CONFLICT DO UPDATE. Each per-row UPDATE waits in
                # its own queue, multiplying the worst case by N. We hit
                # the 30s ``command_timeout`` on the pool and the user
                # got a 500.
                #
                # Now: pre-compute verify_after in Python (cadence policy
                # already lives there), then a single UPDATE that joins
                # against UNNEST($ids, $verify_afters). One round-trip,
                # one lock acquisition, no path-dependency on per-row
                # contention.
                meta = await conn.fetch(
                    "SELECT id, last_date, frequency FROM recurring_streams "
                    "WHERE id = ANY($1::int[])",
                    ids,
                )
                now_utc = datetime.now(timezone.utc)
                ids_arr: List[int] = []
                verify_after_arr: List[Optional[datetime]] = []
                for m in meta:
                    ids_arr.append(int(m["id"]))
                    verify_after_arr.append(
                        _compute_unsubscribe_verify_after(
                            _coerce_last_date(m["last_date"]),
                            m["frequency"],
                            now=now_utc,
                        )
                    )
                if not ids_arr:
                    return 0
                rows = await conn.fetch(
                    """
                    UPDATE recurring_streams AS rs
                       SET user_status                    = 'unsubscribed',
                           unsubscribed_at                = $2,
                           unsubscribe_verify_after       = v.verify_after,
                           unsubscribed_charge_alerted_at = NULL,
                           cancelled_at                   = NULL,
                           paused_until                   = NULL
                      FROM UNNEST($1::int[], $3::timestamptz[])
                           AS v(id, verify_after)
                     WHERE rs.id = v.id
                    RETURNING rs.id
                    """,
                    ids_arr,
                    now_utc,
                    verify_after_arr,
                )
            else:  # action == "snooze_price_change" — validated above.
                snooze_until = date.today() + timedelta(days=snooze_days or 30)
                rows = await conn.fetch(
                    """
                    UPDATE recurring_streams
                       SET price_change_snoozed_until = $2
                     WHERE id = ANY($1::int[])
                    RETURNING id
                    """,
                    ids,
                    snooze_until,
                )
        return len(rows)

    async def upsert_streams(
        self,
        plaid_streams: List[Dict[str, Any]],
        direction: str,
        account_id_map: Dict[str, int],
    ) -> int:
        """
        Upsert recurring streams from Plaid API response.
        account_id_map: {plaid_account_id: internal accounts.id}
        Returns count of upserted rows.
        """
        upserted = 0
        pool = await self._pool()
        async with pool.acquire() as conn:
            for stream in plaid_streams:
                plaid_stream_id = stream.get("stream_id", "")
                if not plaid_stream_id:
                    continue

                plaid_account_id = stream.get("account_id", "")
                account_id = account_id_map.get(plaid_account_id)

                avg_amount = stream.get("average_amount") or {}
                last_amount = stream.get("last_amount") or {}
                avg_cents = (
                    int(round(avg_amount["amount"] * 100))
                    if avg_amount.get("amount") is not None
                    else None
                )
                last_cents = (
                    int(round(last_amount["amount"] * 100))
                    if last_amount.get("amount") is not None
                    else None
                )

                # Calculate SIGNED price change pct. Positive = last charge
                # exceeds the long-term average; negative = latest is lower.
                # Using `abs(avg_cents)` as the denominator keeps the sign from
                # flipping for inflow streams where amounts are already
                # negative in Plaid's contract.
                price_change_pct = None
                if avg_cents and last_cents and avg_cents != 0:
                    pct = (last_cents - avg_cents) / abs(avg_cents)
                    price_change_pct = round(pct * 100, 2)

                pfc = stream.get("personal_finance_category") or {}
                pfc_primary = pfc.get("primary")
                pfc_detailed = pfc.get("detailed")

                currency = (
                    avg_amount.get("iso_currency_code")
                    or last_amount.get("iso_currency_code")
                    or "USD"
                )

                await conn.execute(
                    """
                    INSERT INTO recurring_streams (
                        plaid_stream_id, account_id, direction, description,
                        merchant_name, frequency, average_amount_cents, last_amount_cents,
                        currency, pfc_primary, pfc_detailed,
                        first_date, last_date, is_active, status,
                        price_change_pct, last_synced_at, stream_source
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,NOW(),'plaid')
                    ON CONFLICT (plaid_stream_id) DO UPDATE SET
                        account_id           = EXCLUDED.account_id,
                        direction            = EXCLUDED.direction,
                        description          = EXCLUDED.description,
                        merchant_name        = EXCLUDED.merchant_name,
                        frequency            = EXCLUDED.frequency,
                        average_amount_cents = EXCLUDED.average_amount_cents,
                        last_amount_cents    = EXCLUDED.last_amount_cents,
                        currency             = EXCLUDED.currency,
                        pfc_primary          = EXCLUDED.pfc_primary,
                        pfc_detailed         = EXCLUDED.pfc_detailed,
                        first_date           = EXCLUDED.first_date,
                        last_date            = EXCLUDED.last_date,
                        is_active            = EXCLUDED.is_active,
                        status               = EXCLUDED.status,
                        price_change_pct     = EXCLUDED.price_change_pct,
                        last_synced_at       = NOW()
                    WHERE recurring_streams.stream_source IS DISTINCT FROM 'manual'
                    """,
                    plaid_stream_id,
                    account_id,
                    direction,
                    stream.get("description", ""),
                    stream.get("merchant_name"),
                    stream.get("frequency"),
                    avg_cents,
                    last_cents,
                    currency,
                    pfc_primary,
                    pfc_detailed,
                    stream.get("first_date"),
                    stream.get("last_date"),
                    stream.get("is_active", True),
                    stream.get("status"),
                    price_change_pct,
                )
                upserted += 1
        return upserted
