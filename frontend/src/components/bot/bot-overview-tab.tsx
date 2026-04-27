"use client";

/**
 * Overview tab — link your Telegram chat, see core settings, tweak the
 * morning brief / quiet hours / mood threshold from one place.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNowStrict } from "date-fns";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { botApi, type CoupleSettingsUpdate } from "@/lib/api";

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
  });
  const unlink = useMutation({
    mutationFn: () => botApi.unlinkTelegram(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bot", "telegram-status"] }),
  });

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-2 text-base font-semibold">Telegram link</h2>
        {status.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : status.data?.linked ? (
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="secondary">Linked</Badge>
            <span className="text-sm">
              Chat&nbsp;
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                {status.data.chat_id}
              </code>
              {status.data.telegram_username
                ? ` (@${status.data.telegram_username})`
                : null}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => unlink.mutate()}
              disabled={unlink.isPending}
            >
              Unlink
            </Button>
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
              Generate code
            </Button>
          </div>
        )}
      </section>

      <Separator />

      <section>
        <h2 className="mb-3 text-base font-semibold">Morning brief & quiet hours</h2>
        {settings.isLoading || !settings.data ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <SettingsForm
            initial={settings.data}
            onSave={async (patch) => {
              await botApi.updateSettings(patch);
              qc.invalidateQueries({ queryKey: ["bot", "settings"] });
            }}
          />
        )}
      </section>
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

  const onCopy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      void navigator.clipboard.writeText(code);
    }
  };

  return (
    <div className="rounded-md border border-dashed bg-muted/40 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground">Code</span>
        <code className="rounded bg-background px-2 py-1 font-mono text-base tracking-widest">
          {code}
        </code>
        <Button variant="ghost" size="sm" onClick={onCopy}>
          Copy
        </Button>
      </div>
      <div className={cn("mt-1.5 text-xs", expired ? "text-destructive" : "text-muted-foreground")}>
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

function SettingsForm({
  initial,
  onSave,
}: {
  initial: NonNullable<ReturnType<typeof botApi.getSettings> extends Promise<infer T> ? T : never>;
  onSave: (patch: CoupleSettingsUpdate) => Promise<void>;
}) {
  const [form, setForm] = useState({
    morning_brief_local: initial.morning_brief_local.slice(0, 5),
    morning_brief_tz: initial.morning_brief_tz,
    quiet_hours_start: initial.quiet_hours_start.slice(0, 5),
    quiet_hours_end: initial.quiet_hours_end.slice(0, 5),
    mood_threshold_dollars: (initial.mood_threshold_cents / 100).toFixed(0),
    sunday_brief_enabled: initial.sunday_brief_enabled,
    leaderboard_enabled: initial.leaderboard_enabled,
    anniversary_date: initial.anniversary_date ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Reset whenever the source row changes externally.
  useEffect(() => {
    setForm({
      morning_brief_local: initial.morning_brief_local.slice(0, 5),
      morning_brief_tz: initial.morning_brief_tz,
      quiet_hours_start: initial.quiet_hours_start.slice(0, 5),
      quiet_hours_end: initial.quiet_hours_end.slice(0, 5),
      mood_threshold_dollars: (initial.mood_threshold_cents / 100).toFixed(0),
      sunday_brief_enabled: initial.sunday_brief_enabled,
      leaderboard_enabled: initial.leaderboard_enabled,
      anniversary_date: initial.anniversary_date ?? "",
    });
  }, [initial]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await onSave({
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
      setSavedAt(Date.now());
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
      <div className="grid gap-1.5">
        <Label htmlFor="brief">Morning brief</Label>
        <Input
          id="brief"
          type="time"
          value={form.morning_brief_local}
          onChange={(e) =>
            setForm((f) => ({ ...f, morning_brief_local: e.target.value }))
          }
        />
        <span className="text-xs text-muted-foreground">
          Bundles overnight P1 alerts into one push.
        </span>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="tz">Timezone</Label>
        <Input
          id="tz"
          placeholder="America/New_York"
          value={form.morning_brief_tz}
          onChange={(e) =>
            setForm((f) => ({ ...f, morning_brief_tz: e.target.value }))
          }
        />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="quiet-start">Quiet hours start</Label>
        <Input
          id="quiet-start"
          type="time"
          value={form.quiet_hours_start}
          onChange={(e) =>
            setForm((f) => ({ ...f, quiet_hours_start: e.target.value }))
          }
        />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="quiet-end">Quiet hours end</Label>
        <Input
          id="quiet-end"
          type="time"
          value={form.quiet_hours_end}
          onChange={(e) =>
            setForm((f) => ({ ...f, quiet_hours_end: e.target.value }))
          }
        />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="mood">Mood-check threshold ($)</Label>
        <Input
          id="mood"
          type="number"
          min={0}
          value={form.mood_threshold_dollars}
          onChange={(e) =>
            setForm((f) => ({ ...f, mood_threshold_dollars: e.target.value }))
          }
        />
        <span className="text-xs text-muted-foreground">
          Default {formatCents(initial.mood_threshold_cents)}.
        </span>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="anniversary">Anniversary</Label>
        <Input
          id="anniversary"
          type="date"
          value={form.anniversary_date}
          onChange={(e) =>
            setForm((f) => ({ ...f, anniversary_date: e.target.value }))
          }
        />
      </div>

      <div className="flex items-center justify-between rounded-md border p-3 sm:col-span-2">
        <div>
          <div className="text-sm font-medium">Sunday brief</div>
          <div className="text-xs text-muted-foreground">
            Audit-day digest right after Plaid sync.
          </div>
        </div>
        <Switch
          checked={form.sunday_brief_enabled}
          onCheckedChange={(v) =>
            setForm((f) => ({ ...f, sunday_brief_enabled: v }))
          }
        />
      </div>

      <div className="flex items-center justify-between rounded-md border p-3 sm:col-span-2">
        <div>
          <div className="text-sm font-medium">Couple leaderboard</div>
          <div className="text-xs text-muted-foreground">
            Weekly per-category top spender, included in the Sunday brief.
          </div>
        </div>
        <Switch
          checked={form.leaderboard_enabled}
          onCheckedChange={(v) =>
            setForm((f) => ({ ...f, leaderboard_enabled: v }))
          }
        />
      </div>

      <div className="flex items-center justify-end gap-3 sm:col-span-2">
        {savedAt ? (
          <span className="text-xs text-muted-foreground">Saved.</span>
        ) : null}
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}
