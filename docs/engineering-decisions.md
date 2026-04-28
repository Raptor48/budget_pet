# Engineering decisions

A short, honest log of design calls I made while building Budget Pet.
Each entry has the context, the choice, and the trade-off — what I'd
do the same way again, and what I'd revisit. AI assistance was used
for code generation throughout; every architecture and trade-off
decision below is mine.

---

## Family-wide vs per-user data scoping

**Context.** Some entities (transactions, accounts) belong to one user.
Others (savings milestones, receipts, recurring streams) describe
shared household state. The first cut had everything per-user, which
meant my partner and I each had to re-add the same milestones.

**Choice.** Make `milestones` and `receipts` family-wide, but keep a
`created_by_user_id` foreign key on each row so the UI can tag who
added what. WHERE clauses on `user_id` were dropped in the repo
methods; the tests that called them with `user_id=` keep the kwarg
for backward compat (it's a no-op).

**Trade-off.** Slightly more complex audit story — "who deleted this
milestone?" now requires the audit log, not the row itself. Worth it:
the household abstraction is the actual user-facing model, and the
duplication friction was real.

**See:** `web/bot_api/repo.py` (`list_milestones`, `list_receipts`),
`MilestoneOut`, `ReceiptOut`.

---

## Producer-side denoise vs builder-side render

**Context.** Plaid's recurring detector flags monthly bank-internal
descriptors (interest charges, ACH self-transfers, monthly fees) as
"new subscriptions". A morning brief had 15 lines of `INTEREST CHARGE`
under "Subscriptions detected" — pure noise.

**Choice.** Filter at the **producer** level, not the renderer. A small
denylist of substring matches (`INTEREST CHARGE`, `DDA TO DDA`,
`MONTHLY SERVICE FEE`, …) is checked before the row is enqueued.
Bonus: the `notifications_queue` rows themselves stay clean, so audit
logs and dedup keys are meaningful.

**Trade-off.** New artefact strings will leak through until the
denylist is updated. Acceptable — the alternative (filter at render)
fragmented the dedup key space and made replay hard to reason about.

**See:** `web/notifications/producers.py` (`_BANK_ARTEFACT_SUBSTRINGS`,
`_looks_like_bank_artefact`).

---

## Brand-aware merchant cleanup over generic ACH cleanup

**Context.** Even after the generic ACH descriptor cleaner, names like
`APPLE.COM/BILL CA 03/27` and `ARCHDIGEST - DIGITAL CONDENAST.COM NY`
made the brief unreadable. The generic cleaner couldn't know that
"Apple" was the canonical form of a dozen weird Apple descriptor
variants.

**Choice.** Layer a small `_BRAND_OVERRIDES` regex table on top of the
generic normalizer for ~15 common subscription brands. Match wins →
return canonical name; otherwise fall through to the existing pipeline
plus a duplicate-word collapse pass for cases like `SPECTRUM SPECTRUM`.

**Trade-off.** A maintenance list, but it's tiny (~15 entries) and
catches >80% of real subscriptions seen in my Plaid feed. I prefer a
short list of explicit brands to clever-but-fragile heuristics that
mis-clean unknown merchants.

**See:** `web/notifications/producers.py` (`_BRAND_OVERRIDES`,
`_pretty_subscription_name`).

---

## `next_future_occurrence` vs `next_occurrence`

**Context.** The Reports → Recurring tab showed entries like "Next
payment Mar 9" when today was Apr 27. The existing helper
`next_occurrence(last, freq)` returned **one cadence step** past
`last_date`, which is correct for "what's the immediately following
billing date" but useless for "what's the next billing date from
today's perspective".

**Choice.** Add a second helper, `next_future_occurrence(last, freq,
*, today)`, that walks cadence forward until it crosses `today`. The
original helper stays — its semantic is still useful internally and
the existing tests assert on it. Only the user-facing sort and the
`detect_recurring_tomorrow` producer were switched over.

**Trade-off.** Two helpers with subtly different semantics. The names
make the difference clear; comments at the call sites say which is
appropriate. I'd rather have two well-named functions than one with a
"horizon" boolean.

**See:** `web/reports/calculations.py`, `web/recurring/repo.py`
(`_sort_streams_by_next_payment`).

---

## Reply keyboard over inline keyboard for the bot main menu

**Context.** Inline-keyboard buttons on Telegram are bubble-width-bound
on iOS — even after padding labels with NBSP and ideographic spaces,
each row sat at ~75% of chat width. Reviewers saw a list of narrow
strips and called it cramped (rightly).

**Choice.** Move the main menu to a persistent `ReplyKeyboardMarkup`
(`is_persistent=True`, `resize_keyboard=True`). Buttons render in the
device's bottom keyboard area at full width — roughly 2-3× the visible
size of inline buttons. A `MessageHandler` matches the six button
labels and routes them to the existing menu sections, so taps still
land in the same handler tree.

**Trade-off.** Reply-keyboard taps arrive as plain text messages, not
as `callback_query`. The conversion is straightforward but brittle if
labels are renamed without updating the lookup. Suppressed while a
cash-entry conversation is mid-flight so typed amounts still parse.

**See:** `web/telegram/handlers.py` (`_main_reply_kb`,
`_REPLY_BUTTON_TO_SECTION`, `_open_main_section`).

---

## Foreign-key violation in the brief send loop

**Context.** Production logs flagged
`asyncpg.exceptions.ForeignKeyViolationError` on every brief send:
`bundled_into_id=0` was not present in `notifications_queue`. The brief
itself was being delivered, but the children were never marked sent
because the FK update failed.

**Choice.** The original code held a TODO ("Treat the brief itself as
a fresh queue row so we can dedup on it") that was never finished —
no parent row was inserted, but a placeholder `parent_id=0` was being
written anyway. Replaced with a plain `mark_sent` on children: the
brief is a one-shot Telegram message, not a queue row, so there's no
parent id to point at. `list_pending_for_user` already filters on
`sent_at IS NULL`, so stamping `sent_at` is sufficient to exclude the
children from the next tick.

**Trade-off.** We lose a hypothetical "deduplicate the brief itself"
mechanism, which was never implemented anyway. If we want it back
later, we'd insert a real parent row first and link children to it.

**See:** `web/notifications/dispatcher.py` (`_drain_user`),
commit `89aa033`.

---

## Idempotent migrations over ordered migrations

**Context.** Multiple deploys, occasional schema additions, and the
need to be able to re-run any migration safely (Railway redeploys can
trigger startup before previous migrations finish on a fresh DB).

**Choice.** All migration steps use `ALTER TABLE … ADD COLUMN IF NOT
EXISTS`, `CREATE INDEX IF NOT EXISTS`, and similar idempotent forms.
There is no migration version table and no down-migrations. Schema
state is determined by what the latest run produced, not by which
files have been recorded.

**Trade-off.** No ability to roll back a migration. In practice, this
hasn't been a problem — every change has been additive. If a
destructive migration is ever needed, I'd add a versions table at
that point rather than ahead of time.

**See:** `web/migrations/v2_init.py`, `web/migrations/bot_v1.py`.

---

## Two-layer suppression for the bot in demo deployments

**Context.** The same codebase serves the production deployment (full
bot) and the public demo (no bot). I didn't want a separate "demo"
branch that drifts from production.

**Choice.** Two independent feature flags:
- `NEXT_PUBLIC_HIDE_BOT_TAB=true` removes the Bot nav row from the
  sidebar and silently redirects `/bot` → `/`.
- The backend skips `app.include_router(bot_router)` and the Telegram
  webhook router when `TELEGRAM_BOT_TOKEN` is unset. `/api/bot/*`
  returns 404, so there's nothing for a curious URL-paster to find.

**Trade-off.** Two flags instead of one — but they protect different
layers (FE chrome vs BE API surface) and are independently useful.

**See:** `frontend/src/components/layout/sidebar.tsx`,
`frontend/src/app/bot/page.tsx`, `web/main.py`.
