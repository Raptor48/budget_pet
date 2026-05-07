# Telegram bot

> Status: shipped in V2.3. Lives in-process inside the FastAPI app at
> `web/telegram/`. The legacy `bot.py` + `services/` worker has been
> removed — there is no separate Railway service to deploy.

The bot is a single channel into the same database the web app uses.
Every feature has a mirror screen under `/bot` in the frontend. Nothing
the bot writes is exclusive to Telegram, and nothing in the frontend
section is exclusive to the web — pick whichever is more convenient at
the moment.

## Surface

Top-level menu (English-only, accessed via `/menu` or `/start`):

```
💰 Cash       📊 Today      🔔 Alerts
👥 Family     🎯 Goals      ⚙️ Settings
```

Slash commands:

| Command | Effect |
| --- | --- |
| `/start`, `/menu` | Open the main menu. |
| `/link CODE` | Pair this chat with a web user. Code is generated on the `/bot` page → Overview tab. |
| `/balance`, `/networth`, `/upcoming` | Quick read-only snapshots. |
| `/anniversary` | Conversation flow to set/replace the anniversary date. |
| `/milestone` | Conversation flow to add a net-worth milestone. |
| `/cancel` | Abort any in-progress conversation. |

Free-form text starting with a number (`5 coffee`, `120 grocery`) is
parsed as a cash entry and logged against the user's primary cash wallet.
Photos are routed to the OCR pipeline (`web/telegram/ocr.py`); each is
converted to a cash transaction + a row in `receipts` with parsed
`receipt_lines`.

## Architecture

```
Telegram → POST /api/telegram/webhook
            (signature verified via X-Telegram-Bot-Api-Secret-Token)
            → web/telegram/router.py
                → web/telegram/runtime.py.get_bot_app().process_update()
                    → handlers in web/telegram/handlers.py
                        → repos under web/bot_api/repo.py + web/transactions/repo.py
```

Outbound:

```
APScheduler (every 60s)
    → web/notifications/dispatcher.py
        → reads notifications_queue (P0 immediate, P1 morning brief, P2 Sunday)
        → checks user_notification_prefs + couple_settings.quiet_hours
        → builds message via web/notifications/builders.py
        → app.bot.send_message(chat_id=…)
```

Producers populate the queue:

* `detect_budget_thresholds` — category over 100% of monthly budget (P1)
* `detect_recurring_tomorrow` — recurring stream's next date is tomorrow (P1)
* `detect_plaid_reauth` — `plaid_items.item_login_required = true` (P0)
* `detect_new_merchants` — first appearance of a merchant_name (P1)
* `detect_subscription_changes` — new sub or recurring price diff (P1)
* `detect_milestones` — net worth crosses a configured threshold (P1)
* `detect_mood_check` — un-tagged transaction over user's mood threshold (P1)
* `emit_weekly_leaderboard` — weekly per-category top spender (P2, Sunday)

Producers run hourly + immediately after every Plaid sync (the V2
scheduler hooks them in `web/plaid/scheduler._scheduled_sync`).

## Configuration

| Env var | Required | Notes |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes (to enable bot) | From @BotFather. Without it the runtime is skipped. |
| `TELEGRAM_WEBHOOK_SECRET` | yes | Same value passed to Telegram via `setWebhook?secret_token=…`. Compared against `X-Telegram-Bot-Api-Secret-Token` in constant time. |
| `TELEGRAM_WEBHOOK_URL` | docs only | Operator note for `setWebhook` calls; not read at runtime. |
| `TELEGRAM_BOT_USERNAME` | optional | Surfaced in the link-code dialog so users know which bot to message. |
| `OPENAI_API_KEY` | optional | Receipt OCR uses `gpt-4o-mini` vision. Without the key, photo handling shows a friendly "OCR isn't configured" message. |
| `OPENAI_OCR_MODEL` | optional | Override the OCR model (default `gpt-4o-mini`). |
| `PUBLIC_FRONTEND_URL` | recommended | Used in the Plaid re-auth deep link the bot sends back to the user. |

## Webhook setup

1. Generate a secret: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
   Save it as `TELEGRAM_WEBHOOK_SECRET` on Railway.
2. Restart the FastAPI service so the new env propagates.
3. Tell Telegram where to send updates:
   ```sh
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
        -d "url=https://<your-fastapi-host>/api/telegram/webhook" \
        -d "secret_token=$TELEGRAM_WEBHOOK_SECRET" \
        -d "allowed_updates=message,callback_query"
   ```
4. Verify: `GET /api/telegram/health` returns `{configured: true, running: true}`.

## Database tables (added in `web/migrations/bot_v1.py`)

* `users.telegram_chat_id`, `telegram_username`, `telegram_link_code*`
* `couple_settings` (one row per user — anniversary, mood threshold, brief time, quiet hours)
* `chores` + `chore_assignments` (with `(chore_id, week_start)` unique key)
* `audit_sessions` (Sunday ritual log — host, snack, tea, notes)
* `user_streaks`, `user_milestones`
* `transaction_mood`, `transaction_gifts`
* `merchant_seen`, `recurring_price_snapshots`
* `notifications_queue`, `user_notification_prefs`
* `receipts` + `receipt_lines`

All migrations are idempotent (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN
IF NOT EXISTS`) and run on every startup.

## Frontend

Sidebar entry sits below an `<hr>` divider after **Insights**. The
`/bot` page is a tabbed dashboard:

| Tab | Reads / writes |
| --- | --- |
| Overview | `/api/bot/telegram/*`, `/api/bot/settings` |
| Notifications | `/api/bot/notifications` |
| Audit | `/api/bot/audit/*` |
| Chores | `/api/bot/chores`, `/api/bot/chores/assignments`, `…/{id}/assignments/{week}` |
| Family | `/api/bot/leaderboard`, anniversary from settings |
| Goals | `/api/bot/milestones`, `/api/bot/streaks` |
| Receipts | `/api/bot/receipts`, `/api/bot/receipts/{id}/image` |

## What's not yet wired

These are flagged in `CLAUDE.md` under "Open follow-ups":

* Voice cash entry (Whisper STT)
* Receipt OCR with line-level split per partner
* `/find`, `/digest`, gift-mode UI
* Pinned KPI message that auto-edits with the latest balances
* Per-merchant trend chart on the receipts detail (we have the data)
