"use client";

/**
 * Settings tab — single home for everything that configures the bot:
 * the Telegram link, when/how the brief lands, household-level rituals
 * (Sunday brief, leaderboard), every alert toggle, plus the owner-only
 * roster of linked users.
 *
 * Layout (V2.4): full-width Telegram-link card on top, then a 2-column
 * grid where the LEFT column holds the timing/ritual form (one Save
 * button) and the RIGHT column holds the alert toggles (each saves on
 * flip — no commit step, you can fan-toggle without losing place).
 * Below: linked household members for owners.
 *
 * Anniversary computes the *next* occurrence client-side so a wedding
 * date in the past still surfaces "next anniversary in N days" — the
 * bot fires on T-7 and T-0.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNowStrict } from "date-fns";
import {
  AlertTriangle,
  ArrowDownToDot,
  Bell,
  CalendarClock,
  CalendarHeart,
  Check,
  Clock,
  Copy,
  Globe,
  Link as LinkIcon,
  Loader2,
  MoonStar,
  Plug,
  Settings as SettingsIcon,
  Shield,
  Sparkles,
  Sun,
  Trophy,
  TrendingUp,
  Unlink,
  Users,
  type LucideIcon,
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
  type NotificationPref,
} from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";
import { notify, onMutationError } from "@/lib/notify";

import { formatDate } from "./bot-helpers";

// Curated short list — covers ~99% of household setups. Anything else
// can be typed via the "Other (custom)" branch.
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

// Per-alert icon used in the right-column toggle list. Falls back to a
// neutral warning glyph for any alert_type not enumerated here.
const ALERT_ICONS: Record<string, LucideIcon> = {
  budget_threshold: TrendingUp,
  recurring_tomorrow: CalendarClock,
  plaid_reauth: Plug,
  new_merchant: Sparkles,
  subscription_creep: ArrowDownToDot,
  milestone: Trophy,
  anniversary: CalendarHeart,
};

// P0 / P1 / P2 labels live next to each toggle so the user can decide
// at a glance whether flipping something off is "I miss it tomorrow
// morning" (P1) or "the bank stays broken until I notice" (P0).
function priorityFor(alertType: string): { tier: "P0" | "P1" | "P2"; tone: string } {
  if (alertType === "plaid_reauth") return { tier: "P0", tone: "text-destructive" };
  return { tier: "P1", tone: "text-muted-foreground" };
}

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
    <div className="space-y-6">
      <TelegramLinkCard
        status={status.data}
        loading={status.isLoading}
        onGenerate={() => generateCode.mutate()}
        onUnlink={() => unlink.mutate()}
        generating={generateCode.isPending}
        unlinking={unlink.isPending}
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <Panel
          icon={SettingsIcon}
          title="Schedule & rituals"
          description="When the bot reaches you, in whose timezone, and which household-wide rituals are on."
        >
          {settings.isLoading || !settings.data ? (
            <SettingsFormSkeleton />
          ) : (
            <SettingsForm initial={settings.data} />
          )}
        </Panel>

        <Panel
          icon={Bell}
          title="Alerts"
          description={
            <>
              Each toggle controls whether the bot enqueues that alert.{" "}
              <Badge variant="outline" className="border-destructive/40 text-destructive align-middle">
                P0
              </Badge>{" "}
              push immediately ·{" "}
              <Badge variant="outline" className="align-middle">
                P1
              </Badge>{" "}
              wait for the morning brief.
            </>
          }
        >
          <AlertsPanel />
        </Panel>
      </div>

      {me.data?.is_owner ? <LinkedUsersSection /> : null}
    </div>
  );
}

// ---------------------------------------------------------------------
// Telegram link card — full-width, clearly separated from the rest of
// the form so the link state is the first thing the eye lands on.
// ---------------------------------------------------------------------

function TelegramLinkCard({
  status,
  loading,
  onGenerate,
  onUnlink,
  generating,
  unlinking,
}: {
  status?: {
    linked: boolean;
    chat_id?: number | null;
    telegram_username?: string | null;
    pending_code?: string | null;
    pending_expires_at?: string | null;
  };
  loading: boolean;
  onGenerate: () => void;
  onUnlink: () => void;
  generating: boolean;
  unlinking: boolean;
}) {
  return (
    <Panel icon={LinkIcon} title="Telegram link">
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3 w-72" />
        </div>
      ) : status?.linked ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/30 px-3 py-2.5">
          <Badge variant="secondary" className="gap-1.5">
            <Check className="h-3 w-3" />
            Linked
          </Badge>
          <span className="text-sm">
            Chat&nbsp;
            <code className="rounded bg-background px-1.5 py-0.5 text-xs">
              {status.chat_id}
            </code>
            {status.telegram_username ? ` (@${status.telegram_username})` : null}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={onUnlink}
            disabled={unlinking}
            className="ml-auto"
          >
            {unlinking ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Unlink className="mr-1 h-3.5 w-3.5" />
            )}
            Unlink
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Generate a one-time code, then send <code>/link CODE</code> to
            your Telegram bot to pair this account.
          </p>
          {status?.pending_code ? (
            <PendingCodeCard
              code={status.pending_code}
              expiresAt={status.pending_expires_at}
            />
          ) : null}
          <Button size="sm" onClick={onGenerate} disabled={generating}>
            {generating ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <LinkIcon className="mr-1 h-3.5 w-3.5" />
            )}
            Generate code
          </Button>
        </div>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------
// Generic card shell — title + optional description in the header,
// border + bg-muted/20 so panels read as visually distinct from the
// surrounding tab. Used by every section on this page.
// ---------------------------------------------------------------------

function Panel({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: LucideIcon;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-muted/10 p-4">
      <div className="mb-3 flex items-start gap-2.5">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold leading-tight">{title}</h2>
          {description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function SettingsFormSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="grid gap-1.5">
          <Skeleton className="h-3.5 w-28" />
          <Skeleton className="h-9 w-full" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------
// Linked household roster (admin-only)
// ---------------------------------------------------------------------

function LinkedUsersSection() {
  const linked = useQuery({
    queryKey: ["bot", "linked-users"],
    queryFn: botApi.listLinkedUsers,
    staleTime: 30_000,
  });

  return (
    <Panel
      icon={Users}
      title="Linked household members"
      description="Everyone in the household with the bot wired up. Visible to owners only."
    >
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
    </Panel>
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

// ---------------------------------------------------------------------
// Pending link-code card — countdown timer + copy button.
// ---------------------------------------------------------------------

function PendingCodeCard({
  code,
  expiresAt,
}: {
  code: string;
  expiresAt?: string | null;
}) {
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
        Send <code>/link {code}</code> in your Telegram bot before it
        expires. Codes are intentionally short-lived so a leaked screen
        can&apos;t be used to hijack your account.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Anniversary projector — mirror of the backend `_next_anniversary`
// helper so the inline hint and the producer agree on what "next" is.
// ---------------------------------------------------------------------

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

// ---------------------------------------------------------------------
// Settings form (left column) — schedule, timezone, anniversary,
// household-wide rituals (Sunday brief + leaderboard). Single Save
// button at the bottom; the "All changes saved." badge appears when
// the form matches the server snapshot.
// ---------------------------------------------------------------------

function SettingsForm({ initial }: { initial: CoupleSettings }) {
  const qc = useQueryClient();

  const buildForm = (s: CoupleSettings) => ({
    morning_brief_local: s.morning_brief_local.slice(0, 5),
    morning_brief_tz: s.morning_brief_tz,
    quiet_hours_start: s.quiet_hours_start.slice(0, 5),
    quiet_hours_end: s.quiet_hours_end.slice(0, 5),
    sunday_brief_enabled: s.sunday_brief_enabled,
    leaderboard_enabled: s.leaderboard_enabled,
    anniversary_date: s.anniversary_date ?? "",
  });

  const [form, setForm] = useState(buildForm(initial));

  useEffect(() => {
    setForm(buildForm(initial));
  }, [initial]);

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
      sunday_brief_enabled: form.sunday_brief_enabled,
      leaderboard_enabled: form.leaderboard_enabled,
      anniversary_date: form.anniversary_date || null,
    });
  };

  // Anniversary hint — show next computed anniversary so a wedding
  // date in the past still feels meaningful.
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
    return `Next: ${formatDate(next.toISOString())} — in ${diffDays} day${diffDays === 1 ? "" : "s"}${yearStr}.`;
  }, [form.anniversary_date]);

  return (
    <form className="space-y-4" onSubmit={submit}>
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

      <Field
        icon={Globe}
        id="tz"
        label="Timezone"
        hint="Used for morning brief and quiet hours."
      >
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
          <SelectTrigger id="tz" className="h-9 w-full">
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
            className="mt-1 h-9"
            placeholder="e.g. America/Indiana/Indianapolis"
            value={form.morning_brief_tz}
            onChange={(e) =>
              setForm((f) => ({ ...f, morning_brief_tz: e.target.value }))
            }
          />
        ) : null}
      </Field>

      <div className="grid gap-3 sm:grid-cols-2">
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
      </div>

      <Field
        icon={CalendarHeart}
        id="anniversary"
        label="Anniversary"
        hint={anniversaryHint ?? undefined}
      >
        <DatePicker
          id="anniversary"
          value={form.anniversary_date}
          onChange={(v) =>
            setForm((f) => ({ ...f, anniversary_date: v }))
          }
        />
      </Field>

      <Separator />

      <div className="space-y-2">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Household rituals
        </p>
        <ToggleRow
          icon={Sun}
          title="Sunday brief"
          description="Audit-day digest right after Plaid sync."
          checked={form.sunday_brief_enabled}
          onChange={(v) =>
            setForm((f) => ({ ...f, sunday_brief_enabled: v }))
          }
        />
        <ToggleRow
          icon={Trophy}
          title="Couple leaderboard"
          description="Weekly per-category top spender, included in the Sunday brief."
          checked={form.leaderboard_enabled}
          onChange={(v) =>
            setForm((f) => ({ ...f, leaderboard_enabled: v }))
          }
        />
      </div>

      <div className="flex items-center justify-end gap-3 border-t pt-3">
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

// ---------------------------------------------------------------------
// Alerts panel (right column)
// ---------------------------------------------------------------------

function AlertsPanel() {
  const qc = useQueryClient();
  const prefs = useQuery({
    queryKey: ["bot", "notification-prefs"],
    queryFn: botApi.listNotificationPrefs,
  });

  // Per-row pending tracking — Tanstack's mutation isPending is a single
  // boolean shared across all calls, so it would block every switch when
  // one is in flight. A Set scoped to alert_type keeps each row independent.
  const [inFlight, setInFlight] = useState<Set<string>>(new Set());
  const toggle = useMutation({
    mutationFn: ({ key, enabled }: { key: string; enabled: boolean }) =>
      botApi.setNotificationPref(key, enabled),
    onMutate: ({ key }) =>
      setInFlight((prev) => {
        const next = new Set(prev);
        next.add(key);
        return next;
      }),
    onSettled: (_d, _e, vars) =>
      setInFlight((prev) => {
        const next = new Set(prev);
        next.delete(vars.key);
        return next;
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["bot", "notification-prefs"] }),
    onError: onMutationError("Couldn't toggle that alert."),
  });

  if (prefs.isLoading) {
    return (
      <ul className="divide-y rounded-md border">
        {Array.from({ length: 5 }).map((_, i) => (
          <li key={i} className="flex items-center justify-between px-3 py-2.5">
            <div className="space-y-1.5">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-56" />
            </div>
            <Skeleton className="h-5 w-9 rounded-full" />
          </li>
        ))}
      </ul>
    );
  }

  if (!prefs.data?.length) {
    return (
      <div className="grid place-items-center rounded-md border border-dashed py-8 text-center">
        <Bell className="mb-2 h-5 w-5 text-muted-foreground" aria-hidden />
        <p className="text-xs text-muted-foreground">No alert types defined.</p>
      </div>
    );
  }

  return (
    <ul className="divide-y rounded-md border">
      {prefs.data.map((p) => (
        <AlertRow
          key={p.alert_type}
          pref={p}
          pending={inFlight.has(p.alert_type)}
          onToggle={(enabled) => toggle.mutate({ key: p.alert_type, enabled })}
        />
      ))}
    </ul>
  );
}

function AlertRow({
  pref,
  pending,
  onToggle,
}: {
  pref: NotificationPref;
  pending: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const Icon = ALERT_ICONS[pref.alert_type] ?? AlertTriangle;
  const { tier, tone } = priorityFor(pref.alert_type);
  return (
    <li
      className={cn(
        "flex items-start justify-between gap-3 px-3 py-2.5 transition-colors",
        "hover:bg-muted/40",
        !pref.enabled && "opacity-70",
      )}
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <span
          className={cn(
            "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md transition-colors",
            pref.enabled
              ? "bg-primary/10 text-primary"
              : "bg-muted text-muted-foreground",
          )}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-sm font-medium">
            {pref.label}
            <span className={cn("text-[10px] font-semibold tracking-wider", tone)}>
              {tier}
            </span>
          </div>
          {pref.description ? (
            <div className="text-xs leading-snug text-muted-foreground">
              {pref.description}
            </div>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2 pt-1">
        {pending ? (
          <Loader2
            className="h-3.5 w-3.5 animate-spin text-muted-foreground"
            aria-label="Saving"
          />
        ) : null}
        <Switch
          checked={pref.enabled}
          onCheckedChange={onToggle}
          disabled={pending}
          aria-label={`Toggle ${pref.label}`}
        />
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------
// TimePicker — two-Select inline picker (HH : MM, 5-minute granularity).
// ---------------------------------------------------------------------

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

// ---------------------------------------------------------------------
// DatePicker — Month / Day / Year inline selects, day list bounded to
// the actual days of the chosen month.
// ---------------------------------------------------------------------

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
    const length = 81;
    return Array.from({ length }, (_, i) => String(start + i));
  }, [fallbackYear]);

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
        "flex items-center justify-between gap-3 rounded-md border bg-background/40 p-2.5 transition-colors",
        "hover:bg-muted/30",
      )}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className={cn(
            "grid h-7 w-7 shrink-0 place-items-center rounded-md transition-colors",
            checked ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
          )}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0">
          <div className="text-sm font-medium leading-tight">{title}</div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </div>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}
