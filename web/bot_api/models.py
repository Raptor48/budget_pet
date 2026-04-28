"""
Pydantic models for /api/bot/* endpoints.

Naming convention mirrors the rest of the V2 API: ``*Out`` for read DTOs,
``*Create`` / ``*Update`` for write payloads.
"""
from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Telegram link
# ---------------------------------------------------------------------------

class TelegramLinkStatus(BaseModel):
    linked: bool
    chat_id: Optional[int] = None
    telegram_username: Optional[str] = None
    pending_code: Optional[str] = None
    pending_expires_at: Optional[datetime] = None


class LinkedUser(BaseModel):
    """One row per user with a Telegram chat attached.

    Returned by the owner-only ``GET /api/bot/telegram/linked-users``
    endpoint so the admin/owner can see who in the household has the bot
    wired up without juggling per-user logins.
    """

    user_id: int
    username: str
    is_owner: bool
    telegram_chat_id: int
    telegram_username: Optional[str] = None
    last_activity_at: Optional[datetime] = None


class HouseholdMember(BaseModel):
    """A user the bot considers a real household member.

    Excludes the env-var bootstrap admin (used as an emergency-only
    technical account) so chore rotation, audit hosts, etc. only show
    real people.
    """

    id: int
    username: str


class TelegramLinkCodeOut(BaseModel):
    code: str
    expires_at: datetime
    bot_username: Optional[str] = None


# ---------------------------------------------------------------------------
# Couple / bot settings
# ---------------------------------------------------------------------------

class CoupleSettingsOut(BaseModel):
    user_id: int
    anniversary_date: Optional[date] = None
    partner_user_id: Optional[int] = None
    partner_username: Optional[str] = None
    mood_threshold_cents: int
    leaderboard_enabled: bool
    morning_brief_local: time
    morning_brief_tz: str
    quiet_hours_start: time
    quiet_hours_end: time
    sunday_brief_enabled: bool


class CoupleSettingsUpdate(BaseModel):
    anniversary_date: Optional[date] = None
    partner_user_id: Optional[int] = None
    mood_threshold_cents: Optional[int] = Field(None, ge=0)
    leaderboard_enabled: Optional[bool] = None
    morning_brief_local: Optional[time] = None
    morning_brief_tz: Optional[str] = None
    quiet_hours_start: Optional[time] = None
    quiet_hours_end: Optional[time] = None
    sunday_brief_enabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# Notification preferences (toggle each alert type)
# ---------------------------------------------------------------------------

class NotificationPrefOut(BaseModel):
    alert_type: str
    enabled: bool
    label: str
    description: Optional[str] = None


class NotificationPrefUpdate(BaseModel):
    enabled: bool


# ---------------------------------------------------------------------------
# Chores
# ---------------------------------------------------------------------------

class ChoreOut(BaseModel):
    id: int
    name: str
    icon: Optional[str] = None
    rotation: str
    fixed_user_id: Optional[int] = None
    sort_order: int
    is_active: bool


class ChoreCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    icon: Optional[str] = Field(None, max_length=8)
    rotation: str = Field("weekly", pattern=r"^(weekly|biweekly|fixed)$")
    fixed_user_id: Optional[int] = None
    sort_order: int = 0


class ChoreUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    icon: Optional[str] = Field(None, max_length=8)
    rotation: Optional[str] = Field(None, pattern=r"^(weekly|biweekly|fixed)$")
    fixed_user_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class ChoreAssignmentOut(BaseModel):
    chore_id: int
    chore_name: str
    chore_icon: Optional[str] = None
    week_start: date
    user_id: int
    username: str
    completed_at: Optional[datetime] = None


class ChoreCompletionUpdate(BaseModel):
    completed: bool


# ---------------------------------------------------------------------------
# Audit sessions
# ---------------------------------------------------------------------------

class AuditSessionOut(BaseModel):
    id: int
    week_start: date
    host_user_id: Optional[int] = None
    host_username: Optional[str] = None
    snack: Optional[str] = None
    tea_choice: Optional[str] = None
    notes: Optional[str] = None
    completed_at: Optional[datetime] = None


class AuditSessionUpdate(BaseModel):
    snack: Optional[str] = Field(None, max_length=120)
    tea_choice: Optional[str] = Field(None, max_length=60)
    notes: Optional[str] = Field(None, max_length=2000)
    host_user_id: Optional[int] = None
    completed: Optional[bool] = None


# ---------------------------------------------------------------------------
# Net worth milestones
# ---------------------------------------------------------------------------

class MilestoneOut(BaseModel):
    id: int
    threshold_cents: int
    label: Optional[str] = None
    reached_at: Optional[datetime] = None


class MilestoneCreate(BaseModel):
    threshold_cents: int = Field(..., gt=0)
    label: Optional[str] = Field(None, max_length=80)


# ---------------------------------------------------------------------------
# Streaks (read-only listing)
# ---------------------------------------------------------------------------

class StreakOut(BaseModel):
    streak_type: str
    label: str
    current_count: int
    longest_count: int
    last_event_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Mood log
# ---------------------------------------------------------------------------

class MoodEntryOut(BaseModel):
    transaction_id: int
    mood: str
    note: Optional[str] = None
    created_at: datetime
    transaction_amount_cents: int
    transaction_name: str
    transaction_date: date


class MoodEntryUpsert(BaseModel):
    mood: str = Field(..., pattern=r"^(happy|meh|regret)$")
    note: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

class ReceiptLineOut(BaseModel):
    id: int
    line_number: int
    description: str
    quantity: Optional[float] = None
    unit_price_cents: Optional[int] = None
    total_cents: int


class ReceiptOut(BaseModel):
    id: int
    transaction_id: Optional[int] = None
    merchant_name: Optional[str] = None
    receipt_date: Optional[date] = None
    total_cents: Optional[int] = None
    tax_cents: Optional[int] = None
    currency: str
    parse_status: str
    created_at: datetime
    image_mime: Optional[str] = None
    has_image: bool = True
    # True iff the receipt is attached to a manual-source transaction on a
    # non-Plaid account (i.e. one we created via "Log as cash"). The FE
    # uses this to gate the "also delete the linked cash transaction"
    # checkbox on delete/detach so we never offer to delete a Plaid row.
    linked_is_manual_cash: bool = False
    lines: List[ReceiptLineOut] = []


class ReceiptUpdate(BaseModel):
    """Editable header fields on a receipt.

    All fields optional — Pydantic skips ``None`` so the SQL UPDATE only
    touches what the client actually sent. ``currency`` is constrained to
    3 alpha chars to mirror the OCR sanitiser.
    """

    merchant_name: Optional[str] = Field(None, max_length=200)
    receipt_date: Optional[date] = None
    total_cents: Optional[int] = Field(None, ge=0)
    tax_cents: Optional[int] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=1, max_length=3)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = "".join(ch for ch in v if ch.isalpha()).upper()[:3]
        return cleaned or None


class ReceiptLineUpdate(BaseModel):
    """One row in a receipt's line-items list, used by ``replace_receipt_lines``.

    ``id`` is intentionally omitted — replace_receipt_lines wipes existing
    rows and re-inserts in order. The FE rebuilds line_number from array
    position so reordering also works without a separate endpoint.
    """

    description: str = Field(..., min_length=1, max_length=200)
    quantity: Optional[float] = Field(None, ge=0)
    unit_price_cents: Optional[int] = None
    total_cents: int


class ReceiptLinesReplace(BaseModel):
    lines: List[ReceiptLineUpdate]


# ---------------------------------------------------------------------------
# Couple leaderboard (read-only)
# ---------------------------------------------------------------------------

class LeaderboardEntry(BaseModel):
    user_id: int
    username: str
    category_id: int
    category_name: str
    amount_cents: int


class LeaderboardOut(BaseModel):
    week_start: date
    entries: List[LeaderboardEntry]


# ---------------------------------------------------------------------------
# Bot activity log
# ---------------------------------------------------------------------------

class BotActivityEntry(BaseModel):
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    chat_id: Optional[int] = None
    kind: str
    severity: str
    summary: str
    payload: dict = {}
    error: Optional[str] = None
    created_at: datetime
