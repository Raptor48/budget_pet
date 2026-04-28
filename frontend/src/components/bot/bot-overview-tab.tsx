"use client";

/**
 * Overview tab — link your Telegram chat, see core settings, tweak the
 * morning brief / quiet hours / mood threshold from one place.
 *
 * Layout note (V2.3 polish): the brief/quiet-hours fields live in a 2-col
 * grid where every cell shares the same height + icon treatment so the
 * column doesn't look ragged on narrow screens. Anniversary computes the
 * *next* occurrence client-side so a wedding date in the past still
 * surfaces "next anniversary in N days" — the bot fires on T-7 and T-0.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNowStrict } from "date-fns";
import {
  CalendarHeart,
  Check,
  Clock,
  Copy,
  DollarSign,
  Globe,
  Link as LinkIcon,
  Loader2,
  MoonStar,
  Shield,
  Sun,
  Trophy,
  Unlink,
  Users,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import {
  botApi,
  type CoupleSettings,
  type CoupleSettingsUpdate,
  type LinkedUser,
} from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";
import { notify, onMutationError } from "@/lib/notify";

import { formatCents, formatDate } from "./bot-helpers";

// Curated short list — covers ~99% of household setups. Anything else can
// be typed via the "Other (custom)" branch.
const TIMEZONE_PRESETS = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Toronto",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Amsterdam",
  "Europe/Madrid",
  "Europe/Warsaw",
  "Europe/Moscow",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Asia/Dubai",
  "Australia/Sydney",
  "UTC",
];

const TZ_CUSTOM_VALUE = "__custom__";

export function BotOverviewTab() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["bot", "telegram-status"],
    queryFn: botApi.telegramStatus,
  });
  const settings = useQuery({
    queryKey: ["bot", "settings"],
    queryFn: botApi.getSettings,
  });
  const me = useQuery({
    queryKey: ["auth", "me"],
    queryFn: getCurrentUser,
    staleTime: 60_000,
  });

  const generateCode = useMutation({
    mutationFn: () => botApi.generateLinkCode(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bot", "telegram-status"] }),
    onError: onMutationError("Couldn't generate a link code."),
  });
  const unlink = useMutation({
    mutationFn: () => botApi.unlinkTelegram(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "telegram-status"] });
      notify.success("Telegram unlinked.");
    },
    onError: onMutationError("Couldn't unlink Telegram."),
  });
  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-3 flex items-center gap-2 text-base font-semibold">
          <LinkIcon className="h-4 w-4 text-muted-foreground" />
          Telegram link
        </h2>
        {status.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-3 w-72" />
          </div>
        ) : status.data?.linked ? (
          <div className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/30 px-3 py-2.5">
            <Badge variant="secondary" className="gap-1.5">
              <Check className="h-3 w-3" />
              Linked
            </Badge>
            <span className="text-sm">
              Chat&nbsp;
              <code className="rounded bg-background px-1.5 py-0.5 text-xs">
                {status.data.chat_id}
              </code>
              {status.data.telegram_username
                ? ` (@${status.data.telegram_username})`
                : null}
            </span>
            <div className="ml-auto flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => unlink.mutate()}
                disabled={unlink.isPending}
              >
                {unlink.isPending ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Unlink className="mr-1 h-3.5 w-3.5" />
                )}
                Unlink
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Generate a one-time code, then send <code>/link CODE</code> to your
              Telegram bot to pair this account.
            </p>
            {status.data?.pending_code ? (
              <PendingCodeCard
                code={status.data.pending_code}
                expiresAt={status.data.pending_expires_at}
              />
            ) : null}
            <Button
              size="sm"
              onClick={() => generateCode.mutate()}
              disabled={generateCode.isPending}
            >
              {generateCode.isPending ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <LinkIcon className="mr-1 h-3.5 w-3.5" />
              )}
              Generate code
            </Button>
          </div>
        )}
      </section>

      {me.data?.is_owner ? <LinkedUsersSection /> : null}

      <Separator />

      <section>
        <h2 className="mb-1 flex items-center gap-2 text-base font-semibold">
          <Sun className="h-4 w-4 text-muted-foreground" />
          Morning brief & quiet hours
        </h2>
        <p className="mb-4 text-xs text-muted-foreground">
          The bot bundles overnight notifications and pushes them all in one
          message at your morning brief time. Quiet hours block every push
          except P0 (bank re-auth).
        </p>
        {settings.isLoading || !settings.data ? (
          <SettingsSkeleton />
        ) : (
          <SettingsForm initial={settings.data} />
        )}
      </section>
    </div>
  );
}

function SettingsSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="grid gap-1.5">
          <Skeleton className="h-3.5 w-28" />
          <Skeleton className="h-9 w-full" />
        </div>
      ))}
      <Skeleton className="h-14 w-full sm:col-span-2" />
      <Skeleton className="h-14 w-full sm:col-span-2" />
    </div>
  );
}

function LinkedUsersSection() {
  const linked = useQuery({
    queryKey: ["bot", "linked-users"],
    queryFn: botApi.listLinkedUsers,
    staleTime: 30_000,
  });

  return (
    <section>
      <h2 className="mb-1 flex items-center gap-2 text-base font-semibold">
        <Users className="h-4 w-4 text-muted-foreground" />
        Linked household members
      </h2>
      <p className="mb-3 text-xs text-muted-foreground">
        Everyone in the household with the bot wired up. Visible to owners
        only — useful when someone says &ldquo;did you get the alert?&rdquo;.
      </p>
      {linked.isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : !linked.data?.length ? (
        <div className="rounded-md border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">
          Nobody else has linked yet.
        </div>
      ) : (
        <ul className="divide-y rounded-md border">
          {linked.data.map((u) => (
            <LinkedUserRow key={u.user_id} user={u} />
          ))}
        </ul>
      )}
    </section>
  );
}

function LinkedUserRow({ user }: { user: LinkedUser }) {
  const lastSeen = user.last_activity_at
    ? formatDistanceToNowStrict(new Date(user.last_activity_at), {
        addSuffix: true,
      })
    : "no activity yet";
  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
        {user.is_owner ? (
          <Shield className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <Users className="h-3.5 w-3.5" aria-hidden />
        )}
      </span>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 font-medium">
          {user.username}
          {user.is_owner ? (
            <Badge variant="outline" className="text-[10px] uppercase">
              Owner
            </Badge>
          ) : null}
        </div>
        <div className="text-xs text-muted-foreground">
          Chat <code className="rounded bg-muted px-1 py-0.5">{user.telegram_chat_id}</code>
          {user.telegram_username ? ` · @${user.telegram_username}` : ""}
          {` · last activity ${lastSeen}`}
        </div>
      </div>
    </li>
  );
}

function PendingCodeCard({
  code,
  expiresAt,
}: {
  code: string;
  expiresAt?: string | null;
}) {
  // Re-render every 10s so the countdown stays current without thrashing.
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 10_000);
    return () => clearInterval(id);
  }, []);
  const [copied, setCopied] = useState(false);

  const expiresDate = expiresAt ? new Date(expiresAt) : null;
  const expiresMs = expiresDate ? expiresDate.getTime() - Date.now() : null;
  const expired = expiresMs != null && expiresMs <= 0;
  const countdown =
    expiresDate && !expired
      ? formatDistanceToNowStrict(expiresDate, { addSuffix: false })
      : null;
  const exactTime = expiresDate
    ? expiresDate.toLocaleString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  const onCopy = async () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(code);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      } catch {
        notify.error("Couldn't copy to clipboard.");
      }
    }
  };

  return (
    <div
      className={cn(
        "rounded-md border border-dashed bg-gradient-to-br p-3 text-sm transition-colors",
        expired
          ? "border-destructive/40 from-destructive/5 to-transparent"
          : "border-primary/30 from-primary/5 to-transparent",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground">Code</span>
        <code className="rounded bg-background px-2 py-1 font-mono text-base tracking-widest shadow-sm">
          {code}
        </code>
        <Button
          variant="ghost"
          size="sm"
          onClick={onCopy}
          className="transition-transform active:scale-95"
        >
          {copied ? (
            <>
              <Check className="mr-1 h-3.5 w-3.5" />
              Copied
            </>
          ) : (
            <>
              <Copy className="mr-1 h-3.5 w-3.5" />
              Copy
            </>
          )}
        </Button>
      </div>
      <div
        className={cn(
          "mt-1.5 text-xs",
          expired ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {expired
          ? "Code expired — generate a new one."
          : countdown
            ? `Expires in ${countdown} (at ${exactTime})`
            : null}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        Send <code>/link {code}</code> in your Telegram bot before it expires.
        Codes are intentionally short-lived so a leaked screen can&apos;t be
        used to hijack your account.
      </div>
    </div>
  );
}

/**
 * Project an anniversary date onto today's calendar. Mirrors
 * `_next_anniversary` in web/notifications/producers.py — kept in sync so
 * the UI hint and the actual notification agree on what "next" means.
 */
function nextAnniversary(originalIso: string, today: Date): Date | null {
  const [yStr, mStr, dStr] = originalIso.split("-");
  const y = Number(yStr);
  const m = Number(mStr) - 1;
  const day = Number(dStr);
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(day)) {
    return null;
  }
  const tryDate = (year: number) => {
    const dt = new Date(year, m, day);
    // Handle Feb 29 in a non-leap year — JS rolls over to Mar 1, so detect
    // the rollover and clamp to Feb 28.
    if (dt.getMonth() !== m) return new Date(year, m, 28);
    return dt;
  };
  let candidate = tryDate(today.getFullYear());
  const startOfToday = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate(),
  );
  if (candidate < startOfToday) candidate = tryDate(today.getFullYear() + 1);
  return candidate;
}

function SettingsForm({ initial }: { initial: CoupleSettings }) {
  const qc = useQueryClient();

  const buildForm = (s: CoupleSettings) => ({
    morning_brief_local: s.morning_brief_local.slice(0, 5),
    morning_brief_tz: s.morning_brief_tz,
    quiet_hours_start: s.quiet_hours_start.slice(0, 5),
    quiet_hours_end: s.quiet_hours_end.slice(0, 5),
    mood_threshold_dollars: (s.mood_threshold_cents / 100).toFixed(0),
    sunday_brief_enabled: s.sunday_brief_enabled,
    leaderboard_enabled: s.leaderboard_enabled,
    anniversary_date: s.anniversary_date ?? "",
  });

  const [form, setForm] = useState(buildForm(initial));

  // Reset whenever the source row changes externally.
  useEffect(() => {
    setForm(buildForm(initial));
  }, [initial]);

  // Track whether the timezone is one of the curated presets so we can
  // show the "Other (custom)" branch when the user has typed something
  // unusual (e.g. America/Indiana/Indianapolis).
  const tzIsPreset = TIMEZONE_PRESETS.includes(form.morning_brief_tz);
  const [tzMode, setTzMode] = useState<"preset" | "custom">(
    tzIsPreset || !form.morning_brief_tz ? "preset" : "custom",
  );
  useEffect(() => {
    setTzMode(tzIsPreset || !form.morning_brief_tz ? "preset" : "custom");
  }, [tzIsPreset, form.morning_brief_tz]);

  const save = useMutation({
    mutationFn: (patch: CoupleSettingsUpdate) => botApi.updateSettings(patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "settings"] });
      notify.success("Settings saved.");
    },
    onError: onMutationError("Couldn't save those settings."),
  });

  const dirty = useMemo(() => {
    const baseline = buildForm(initial);
    return JSON.stringify(form) !== JSON.stringify(baseline);
  }, [form, initial]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    save.mutate({
      morning_brief_local: `${form.morning_brief_local}:00`,
      morning_brief_tz: form.morning_brief_tz,
      quiet_hours_start: `${form.quiet_hours_start}:00`,
      quiet_hours_end: `${form.quiet_hours_end}:00`,
      mood_threshold_cents: Math.max(
        0,
        Math.round(Number(form.mood_threshold_dollars || 0) * 100),
      ),
      sunday_brief_enabled: form.sunday_brief_enabled,
      leaderboard_enabled: form.leaderboard_enabled,
      anniversary_date: form.anniversary_date || null,
    });
  };

  // Anniversary hint — show next computed anniversary so a wedding date in
  // the past still feels meaningful. Computed client-side; the producer
  // does the same projection on the server when it fires.
  const anniversaryHint = useMemo(() => {
    if (!form.anniversary_date) {
      return "Bot pings 7 days before and on the day. Past dates are projected to this year.";
    }
    const next = nextAnniversary(form.anniversary_date, new Date());
    if (!next) return null;
    const diffDays = Math.round(
      (next.getTime() - Date.now()) / (1000 * 60 * 60 * 24),
    );
    const original = new Date(form.anniversary_date);
    const years = Number.isFinite(original.getFullYear())
      ? next.getFullYear() - original.getFullYear()
      : null;
    const yearStr = years && years > 0 ? ` · ${years} years together` : "";
    return `Next: ${formatDate(next.toISOString())} — in ${diffDays} day${diffDays === 1 ? "" : "s"}${yearStr}. Bot pings T-7 and on the day.`;
  }, [form.anniversary_date]);

  return (
    <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
      <Field
        icon={Sun}
        id="brief"
        label="Morning brief"
        hint="Bundles overnight P1 alerts into one push."
      >
        <TimePicker
          id="brief"
          value={form.morning_brief_local}
          onChange={(v) =>
            setForm((f) => ({ ...f, morning_brief_local: v }))
          }
        />
      </Field>

      <Field icon={Globe} id="tz" label="Timezone" hint="Used for brief + quiet hours.">
        <Select
          value={tzMode === "preset" ? form.morning_brief_tz : TZ_CUSTOM_VALUE}
          onValueChange={(v) => {
            if (v === TZ_CUSTOM_VALUE) {
              setTzMode("custom");
            } else {
              setTzMode("preset");
              setForm((f) => ({ ...f, morning_brief_tz: v }));
            }
          }}
        >
          <SelectTrigger id="tz" className="h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TIMEZONE_PRESETS.map((tz) => (
              <SelectItem key={tz} value={tz}>
                {tz}
              </SelectItem>
            ))}
            <SelectItem value={TZ_CUSTOM_VALUE}>Other (custom)…</SelectItem>
          </SelectContent>
        </Select>
        {tzMode === "custom" ? (
          <Input
            className="mt-1"
            placeholder="e.g. America/Indiana/Indianapolis"
            value={form.morning_brief_tz}
            onChange={(e) =>
              setForm((f) => ({ ...f, morning_brief_tz: e.target.value }))
            }
          />
        ) : null}
      </Field>

      <Field
        icon={MoonStar}
        id="quiet-start"
        label="Quiet hours start"
        hint="Pushes pause until quiet end."
      >
        <TimePicker
          id="quiet-start"
          value={form.quiet_hours_start}
          onChange={(v) =>
            setForm((f) => ({ ...f, quiet_hours_start: v }))
          }
        />
      </Field>

      <Field
        icon={Clock}
        id="quiet-end"
        label="Quiet hours end"
        hint="Bundled brief lands at this time."
      >
        <TimePicker
          id="quiet-end"
          value={form.quiet_hours_end}
          onChange={(v) =>
            setForm((f) => ({ ...f, quiet_hours_end: v }))
          }
        />
      </Field>

      <Field
        icon={DollarSign}
        id="mood"
        label="Mood-check threshold ($)"
        hint={`Default ${formatCents(initial.mood_threshold_cents)}.`}
      >
        <Input
          id="mood"
          type="number"
          min={0}
          className="h-9"
          value={form.mood_threshold_dollars}
          onChange={(e) =>
            setForm((f) => ({ ...f, mood_threshold_dollars: e.target.value }))
          }
        />
      </Field>

      <Field icon={CalendarHeart} id="anniversary" label="Anniversary" hint={anniversaryHint ?? undefined}>
        <DatePicker
          id="anniversary"
          value={form.anniversary_date}
          onChange={(v) =>
            setForm((f) => ({ ...f, anniversary_date: v }))
          }
        />
      </Field>

      <ToggleRow
        icon={Sun}
        title="Sunday brief"
        description="Audit-day digest right after Plaid sync."
        checked={form.sunday_brief_enabled}
        onChange={(v) => setForm((f) => ({ ...f, sunday_brief_enabled: v }))}
      />

      <ToggleRow
        icon={Trophy}
        title="Couple leaderboard"
        description="Weekly per-category top spender, included in the Sunday brief."
        checked={form.leaderboard_enabled}
        onChange={(v) => setForm((f) => ({ ...f, leaderboard_enabled: v }))}
      />

      <div className="flex items-center justify-end gap-3 sm:col-span-2">
        {!dirty && !save.isPending ? (
          <span className="text-xs text-muted-foreground">All changes saved.</span>
        ) : null}
        <Button
          type="submit"
          disabled={!dirty || save.isPending}
          className="transition-transform active:scale-95"
        >
          {save.isPending ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Check className="mr-1 h-4 w-4" />
          )}
          Save
        </Button>
      </div>
    </form>
  );
}

/**
 * Inline time picker built from two `Select` dropdowns.
 *
 * Native <input type="time"> looks ugly across browsers and the picker
 * icon is invisible on dark backgrounds. Two compact selects (HH and MM)
 * sit beside each other with a colon separator and use the same styling
 * as every other dropdown in the app, so the form reads consistently.
 *
 * Granularity: 5 minutes for minute selection (12 options) — enough for
 * a morning brief / quiet hours toggle. If the saved value isn't on a
 * 5-minute boundary (e.g. legacy data), it's added to the list so the
 * user doesn't see a blank trigger.
 */
function TimePicker({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const [rawHh, rawMm] = (value || "00:00").split(":");
  const hh = (rawHh || "00").padStart(2, "0");
  const mm = (rawMm || "00").padStart(2, "0");

  const hourOptions = useMemo(
    () => Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0")),
    [],
  );
  const minuteOptions = useMemo(() => {
    const base = Array.from({ length: 12 }, (_, i) =>
      String(i * 5).padStart(2, "0"),
    );
    if (!base.includes(mm)) {
      return Array.from(new Set([...base, mm])).sort();
    }
    return base;
  }, [mm]);

  return (
    <div className="flex items-center gap-1">
      <Select value={hh} onValueChange={(v) => onChange(`${v}:${mm}`)}>
        <SelectTrigger id={id} className="h-9 w-[78px] tabular-nums">
          <SelectValue />
        </SelectTrigger>
        <SelectContent className="max-h-[260px]">
          {hourOptions.map((h) => (
            <SelectItem key={h} value={h} className="tabular-nums">
              {h}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <span className="select-none px-0.5 text-base text-muted-foreground">:</span>
      <Select value={mm} onValueChange={(v) => onChange(`${hh}:${v}`)}>
        <SelectTrigger className="h-9 w-[78px] tabular-nums">
          <SelectValue />
        </SelectTrigger>
        <SelectContent className="max-h-[260px]">
          {minuteOptions.map((m) => (
            <SelectItem key={m} value={m} className="tabular-nums">
              {m}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

const MONTH_NAMES = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/**
 * Inline date picker — three `Select`s for month/day/year.
 *
 * Beats native <input type="date"> on three counts: consistent styling
 * across browsers (Safari and Firefox render the native picker very
 * differently from Chrome), works in dark mode without the invisible
 * calendar-icon problem, and the day list stays bounded to the actual
 * days of the chosen month so 30 February isn't selectable.
 *
 * Empty value → placeholder text shown by SelectValue (passing
 * `value={undefined}` to Radix Select keeps the trigger empty so the
 * placeholder shows). Year range covers 60 years back through 20
 * years forward to handle wedding dates and milestone projections
 * without growing the list to absurd lengths.
 */
function DatePicker({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const today = new Date();
  const fallbackYear = today.getFullYear();

  const parts = value ? value.split("-") : ["", "", ""];
  const yyStr = parts[0] || "";
  const mmStr = parts[1] || "";
  const ddStr = parts[2] || "";

  const yearOptions = useMemo(() => {
    const start = fallbackYear - 60;
    const length = 81; // 60 back + this year + 20 forward
    return Array.from({ length }, (_, i) => String(start + i));
  }, [fallbackYear]);

  // Days available for the currently-selected month. When year/month are
  // unset we default to a 31-day month so the user can pick day first.
  const yearForCalc = Number(yyStr || fallbackYear);
  const monthForCalc = Number(mmStr || 1);
  const daysInMonth = new Date(yearForCalc, monthForCalc, 0).getDate();
  const dayOptions = useMemo(
    () =>
      Array.from({ length: daysInMonth }, (_, i) =>
        String(i + 1).padStart(2, "0"),
      ),
    [daysInMonth],
  );

  // Compose YYYY-MM-DD when all parts are present, clamping the day to
  // the last valid day of the chosen month so flipping Mar 31 → Feb
  // doesn't crash on Feb 31. Returns null while any part is still
  // unset — caller leaves the form value empty until the user picks
  // the missing pieces.
  const compose = (newY: string, newM: string, newD: string) => {
    if (!newY || !newM || !newD) return null;
    const ymd = new Date(Number(newY), Number(newM) - 1, Number(newD));
    if (Number.isNaN(ymd.getTime())) return null;
    const lastDay = new Date(Number(newY), Number(newM), 0).getDate();
    const safeDay = Math.min(Number(newD), lastDay);
    return `${newY}-${newM.padStart(2, "0")}-${String(safeDay).padStart(2, "0")}`;
  };

  const currentMonthStr = String(today.getMonth() + 1).padStart(2, "0");
  const setMonth = (v: string) => {
    const next = compose(yyStr || String(fallbackYear), v, ddStr || "01");
    if (next) onChange(next);
  };
  const setDay = (v: string) => {
    const next = compose(
      yyStr || String(fallbackYear),
      mmStr || currentMonthStr,
      v,
    );
    if (next) onChange(next);
  };
  const setYear = (v: string) => {
    const next = compose(v, mmStr || currentMonthStr, ddStr || "01");
    if (next) onChange(next);
  };

  return (
    <div className="flex items-center gap-1">
      <Select value={mmStr || undefined} onValueChange={setMonth}>
        <SelectTrigger id={id} className="h-9 w-[88px]">
          <SelectValue placeholder="Month" />
        </SelectTrigger>
        <SelectContent className="max-h-[260px]">
          {MONTH_NAMES.map((label, i) => (
            <SelectItem key={label} value={String(i + 1).padStart(2, "0")}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={ddStr || undefined} onValueChange={setDay}>
        <SelectTrigger className="h-9 w-[68px] tabular-nums">
          <SelectValue placeholder="Day" />
        </SelectTrigger>
        <SelectContent className="max-h-[260px]">
          {dayOptions.map((d) => (
            <SelectItem key={d} value={d} className="tabular-nums">
              {d}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={yyStr || undefined} onValueChange={setYear}>
        <SelectTrigger className="h-9 w-[86px] tabular-nums">
          <SelectValue placeholder="Year" />
        </SelectTrigger>
        <SelectContent className="max-h-[260px]">
          {yearOptions.map((y) => (
            <SelectItem key={y} value={y} className="tabular-nums">
              {y}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function Field({
  icon: Icon,
  id,
  label,
  hint,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id} className="flex items-center gap-1.5 text-xs font-medium">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        {label}
      </Label>
      {children}
      {hint ? (
        <span className="min-h-[1.25rem] text-[11px] leading-snug text-muted-foreground">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

function ToggleRow({
  icon: Icon,
  title,
  description,
  checked,
  onChange,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-md border p-3 transition-colors sm:col-span-2",
        "hover:bg-muted/30",
      )}
    >
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "grid h-8 w-8 place-items-center rounded-md transition-colors",
            checked ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <div>
          <div className="text-sm font-medium">{title}</div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </div>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}
