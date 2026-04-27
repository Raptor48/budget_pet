"use client";

/**
 * Notifications tab — toggle each alert type the bot sends.
 *
 * The keys (alert_type) match the producers in web/notifications/producers.py
 * and the renderer registry in web/notifications/builders.py. The order here
 * is purely cosmetic; the backend always returns its canonical order.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Switch } from "@/components/ui/switch";
import { botApi } from "@/lib/api";

export function BotNotificationsTab() {
  const qc = useQueryClient();
  const prefs = useQuery({
    queryKey: ["bot", "notification-prefs"],
    queryFn: botApi.listNotificationPrefs,
  });
  const toggle = useMutation({
    mutationFn: ({ key, enabled }: { key: string; enabled: boolean }) =>
      botApi.setNotificationPref(key, enabled),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["bot", "notification-prefs"] }),
  });

  if (prefs.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!prefs.data?.length)
    return <p className="text-sm text-muted-foreground">No alert types defined.</p>;

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        Each toggle controls whether the bot enqueues the corresponding alert.
        P0 alerts (bank re-auth) push immediately; P1 alerts wait for your
        morning brief; P2 alerts ride along on the Sunday brief.
      </p>
      <ul className="divide-y rounded-md border">
        {prefs.data.map((p) => (
          <li
            key={p.alert_type}
            className="flex items-center justify-between gap-4 px-4 py-3"
          >
            <div className="min-w-0">
              <div className="text-sm font-medium">{p.label}</div>
              {p.description ? (
                <div className="truncate text-xs text-muted-foreground">
                  {p.description}
                </div>
              ) : null}
            </div>
            <Switch
              checked={p.enabled}
              onCheckedChange={(v) =>
                toggle.mutate({ key: p.alert_type, enabled: v })
              }
              disabled={toggle.isPending}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
