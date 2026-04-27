"use client";

/**
 * Notifications tab — toggle each alert type the bot sends.
 *
 * The keys (alert_type) match the producers in web/notifications/producers.py
 * and the renderer registry in web/notifications/builders.py. The order here
 * is purely cosmetic; the backend always returns its canonical order.
 *
 * Per-row pending state is tracked via the `inFlight` Set — flipping one
 * switch never disables the others, so a slow connection still feels
 * responsive when the user wants to flip several toggles in a row.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDownToDot,
  Bell,
  CalendarClock,
  ClipboardCheck,
  Loader2,
  Plug,
  Smile,
  Sparkles,
  Trophy,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { botApi, type NotificationPref } from "@/lib/api";
import { onMutationError } from "@/lib/notify";

const ALERT_ICONS: Record<string, LucideIcon> = {
  budget_threshold: TrendingUp,
  recurring_tomorrow: CalendarClock,
  plaid_reauth: Plug,
  new_merchant: Sparkles,
  subscription_creep: ArrowDownToDot,
  milestone: Trophy,
  mood_check: Smile,
  leaderboard: Trophy,
  sunday_brief: ClipboardCheck,
};

// P0 / P1 / P2 labels live next to each toggle so the user can decide at a
// glance whether flipping something off is "I miss it tomorrow morning"
// (P1) or "the bank stays broken until I notice" (P0).
function priorityFor(alertType: string): { tier: "P0" | "P1" | "P2"; tone: string } {
  if (alertType === "plaid_reauth") return { tier: "P0", tone: "text-destructive" };
  if (alertType === "leaderboard" || alertType === "sunday_brief")
    return { tier: "P2", tone: "text-muted-foreground" };
  return { tier: "P1", tone: "text-muted-foreground" };
}

export function BotNotificationsTab() {
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
    onSettled: (_data, _err, vars) =>
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
      <div className="space-y-2">
        <Skeleton className="h-4 w-2/3" />
        <ul className="divide-y rounded-md border">
          {Array.from({ length: 5 }).map((_, i) => (
            <li key={i} className="flex items-center justify-between px-4 py-3">
              <div className="space-y-1.5">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-64" />
              </div>
              <Skeleton className="h-5 w-9 rounded-full" />
            </li>
          ))}
        </ul>
      </div>
    );
  }

  if (!prefs.data?.length) {
    return (
      <div className="grid place-items-center rounded-md border border-dashed py-12 text-center">
        <Bell className="mb-2 h-6 w-6 text-muted-foreground" aria-hidden />
        <p className="text-sm text-muted-foreground">No alert types defined.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Each toggle controls whether the bot enqueues the corresponding alert.
        <span className="mx-1.5 inline-flex items-center gap-1 align-middle">
          <Badge variant="outline" className="border-destructive/40 text-destructive">
            P0
          </Badge>
          push immediately
        </span>·
        <span className="mx-1.5 inline-flex items-center gap-1 align-middle">
          <Badge variant="outline">P1</Badge>
          wait for your morning brief
        </span>·
        <span className="mx-1.5 inline-flex items-center gap-1 align-middle">
          <Badge variant="outline">P2</Badge>
          ride along on the Sunday brief
        </span>.
      </p>
      <ul className="divide-y rounded-md border">
        {prefs.data.map((p) => (
          <NotificationRow
            key={p.alert_type}
            pref={p}
            pending={inFlight.has(p.alert_type)}
            onToggle={(enabled) => toggle.mutate({ key: p.alert_type, enabled })}
          />
        ))}
      </ul>
    </div>
  );
}

function NotificationRow({
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
        "flex items-center justify-between gap-4 px-4 py-3 transition-colors",
        "hover:bg-muted/40",
        !pref.enabled && "opacity-70",
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        <span
          className={cn(
            "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md transition-colors",
            pref.enabled ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
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
            <div className="text-xs text-muted-foreground">{pref.description}</div>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
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
