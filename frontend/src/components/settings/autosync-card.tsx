"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, Loader2, Clock } from "lucide-react";

import { appSettingsApi } from "@/lib/api";
import { onMutationError, notify } from "@/lib/notify";
import type { AutosyncConfig } from "@/types/v2";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";

/**
 * Convert a UTC hour+minute into the local-time "HH:MM" string rendered by
 * an <input type="time">. Uses today's date as the reference point; a daily
 * schedule is stable across DST transitions because we store UTC on the
 * server and re-derive local values on every render.
 */
function utcToLocalHHMM(hourUtc: number, minuteUtc: number): string {
  const now = new Date();
  const utc = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hourUtc, minuteUtc, 0),
  );
  const hh = String(utc.getHours()).padStart(2, "0");
  const mm = String(utc.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

/** Reverse of `utcToLocalHHMM`: local HH:MM → UTC hour/minute. */
function localHHMMToUtc(hhmm: string): { hour_utc: number; minute_utc: number } | null {
  const match = /^(\d{2}):(\d{2})$/.exec(hhmm);
  if (!match) return null;
  const hh = Number(match[1]);
  const mm = Number(match[2]);
  if (!Number.isFinite(hh) || !Number.isFinite(mm)) return null;
  const now = new Date();
  const local = new Date(now.getFullYear(), now.getMonth(), now.getDate(), hh, mm, 0);
  return { hour_utc: local.getUTCHours(), minute_utc: local.getUTCMinutes() };
}

function formatNextRun(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

function localTimezoneLabel(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "local time";
  } catch {
    return "local time";
  }
}

export function AutosyncCard() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery<AutosyncConfig>({
    queryKey: ["app-settings"],
    queryFn: appSettingsApi.get,
  });

  const [timeLocal, setTimeLocal] = useState<string>("");

  useEffect(() => {
    if (data) {
      setTimeLocal(utcToLocalHHMM(data.hour_utc, data.minute_utc));
    }
  }, [data]);

  const tzLabel = useMemo(() => localTimezoneLabel(), []);

  const updateMutation = useMutation({
    mutationFn: appSettingsApi.update,
    onSuccess: (next) => {
      queryClient.setQueryData(["app-settings"], next);
      queryClient.invalidateQueries({ queryKey: ["audit-log"] });
      notify.success("Autosync schedule updated");
    },
    onError: onMutationError("Could not update autosync schedule"),
  });

  const handleToggle = (enabled: boolean) => {
    updateMutation.mutate({ enabled });
  };

  const handleTimeChange = (value: string) => {
    setTimeLocal(value);
    const utc = localHHMMToUtc(value);
    if (!utc) return;
    if (data && utc.hour_utc === data.hour_utc && utc.minute_utc === data.minute_utc) return;
    updateMutation.mutate(utc);
  };

  if (isLoading || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-5 w-5" />
            Autosync
          </CardTitle>
          <CardDescription>Daily background sync of Plaid transactions</CardDescription>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-20 w-full" />
        </CardContent>
      </Card>
    );
  }

  const disabled = updateMutation.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="h-5 w-5" />
          Autosync
        </CardTitle>
        <CardDescription>
          Daily background sync for all connected banks. Time is shown in your
          timezone ({tzLabel}).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between gap-4 rounded-lg border border-border/60 px-4 py-3">
          <div className="space-y-0.5">
            <Label htmlFor="autosync-toggle" className="text-base">
              Enable daily sync
            </Label>
            <p className="text-sm text-muted-foreground">
              When off, Plaid data refreshes only when you press Sync now or when
              a webhook push arrives.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {disabled ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
            <Switch
              id="autosync-toggle"
              checked={data.enabled}
              onCheckedChange={handleToggle}
              disabled={disabled}
            />
          </div>
        </div>

        <div className="flex flex-col gap-3 rounded-lg border border-border/60 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-0.5">
            <Label htmlFor="autosync-time" className="text-base">
              Sync time
            </Label>
            <p className="text-sm text-muted-foreground">
              Stored as {String(data.hour_utc).padStart(2, "0")}:
              {String(data.minute_utc).padStart(2, "0")} UTC. Next run: {formatNextRun(data.next_run_at)}
            </p>
          </div>
          <Input
            id="autosync-time"
            type="time"
            step={60}
            value={timeLocal}
            onChange={(e) => handleTimeChange(e.target.value)}
            disabled={disabled || !data.enabled}
            className="w-full sm:w-36"
          />
        </div>

        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            Plaid rate-limits background syncs and each run counts against our
            Plaid plan. One daily pull is enough to keep transactions, balances
            and recurring streams fresh — webhooks already cover instant
            updates when a new charge posts.
          </AlertDescription>
        </Alert>

        {data.updated_by_username ? (
          <p className="text-xs text-muted-foreground">
            Last changed by {data.updated_by_username}
            {data.updated_at
              ? ` on ${new Date(data.updated_at).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}`
              : null}
            .
          </p>
        ) : null}

        {updateMutation.isPending ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Saving…
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default AutosyncCard;
