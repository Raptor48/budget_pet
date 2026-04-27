"use client";

/**
 * Overview tab — link your Telegram chat, see core settings, tweak the
 * morning brief / quiet hours / mood threshold from one place.
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
  Sparkles,
  Sun,
  Trophy,
  Unlink,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { botApi, type CoupleSettings, type CoupleSettingsUpdate } from "@/lib/api";
import { notify, onMutationError } from "@/lib/notify";

import { formatCents } from "./bot-helpers";

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
  const sendTest = useMutation({
    mutationFn: () => botApi.sendTestAlert(),
    onSuccess: (res) => {
      if (res.sent) {
        // Drain runs in the background, so the actual Telegram push lands
        // a second or two later. Wording reflects that without making the
        // user wait on this toast.
        notify.success("Test alert queued — should pop up in Telegram any moment.");
      } else if (res.deduped) {
        notify.info("Already sent one in the last second — check Telegram.");
      }
    },
    onError: onMutationError("Couldn't send the test alert."),
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
                variant="outline"
                size="sm"
                onClick={() => sendTest.mutate()}
                disabled={sendTest.isPending}
                title="Push a one-shot test message through the full pipeline"
              >
                {sendTest.isPending ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="mr-1 h-3.5 w-3.5" />
                )}
                Send test
              </Button>
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

  return (
    <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
      <FieldWithIcon
        icon={Sun}
        id="brief"
        label="Morning brief"
        hint="Bundles overnight P1 alerts into one push."
      >
        <Input
          id="brief"
          type="time"
          value={form.morning_brief_local}
          onChange={(e) =>
            setForm((f) => ({ ...f, morning_brief_local: e.target.value }))
          }
        />
      </FieldWithIcon>

      <FieldWithIcon icon={Globe} id="tz" label="Timezone">
        <Input
          id="tz"
          placeholder="America/New_York"
          value={form.morning_brief_tz}
          onChange={(e) =>
            setForm((f) => ({ ...f, morning_brief_tz: e.target.value }))
          }
        />
      </FieldWithIcon>

      <FieldWithIcon icon={MoonStar} id="quiet-start" label="Quiet hours start">
        <Input
          id="quiet-start"
          type="time"
          value={form.quiet_hours_start}
          onChange={(e) =>
            setForm((f) => ({ ...f, quiet_hours_start: e.target.value }))
          }
        />
      </FieldWithIcon>

      <FieldWithIcon icon={Clock} id="quiet-end" label="Quiet hours end">
        <Input
          id="quiet-end"
          type="time"
          value={form.quiet_hours_end}
          onChange={(e) =>
            setForm((f) => ({ ...f, quiet_hours_end: e.target.value }))
          }
        />
      </FieldWithIcon>

      <FieldWithIcon
        icon={DollarSign}
        id="mood"
        label="Mood-check threshold ($)"
        hint={`Default ${formatCents(initial.mood_threshold_cents)}.`}
      >
        <Input
          id="mood"
          type="number"
          min={0}
          value={form.mood_threshold_dollars}
          onChange={(e) =>
            setForm((f) => ({ ...f, mood_threshold_dollars: e.target.value }))
          }
        />
      </FieldWithIcon>

      <FieldWithIcon icon={CalendarHeart} id="anniversary" label="Anniversary">
        <Input
          id="anniversary"
          type="date"
          value={form.anniversary_date}
          onChange={(e) =>
            setForm((f) => ({ ...f, anniversary_date: e.target.value }))
          }
        />
      </FieldWithIcon>

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

function FieldWithIcon({
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
      <Label htmlFor={id} className="flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        {label}
      </Label>
      {children}
      {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
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
