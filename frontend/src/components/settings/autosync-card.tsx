"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Clock, Webhook } from "lucide-react";

import { appSettingsApi } from "@/lib/api";
import { onMutationError, notify } from "@/lib/notify";
import type { AutosyncConfig, AutosyncFrequency } from "@/types/v2";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";

/**
 * Human-readable description of each frequency option, including the anchor
 * day the backend uses so the user knows *exactly* when the job fires. These
 * strings mirror `web/app_settings/models.py::AutosyncConfig` — keep them in
 * sync if the backend anchors ever change.
 */
const FREQUENCY_OPTIONS: Array<{
  value: AutosyncFrequency;
  label: string;
  hint: string;
}> = [
  { value: "off", label: "Off", hint: "No scheduled sync — use the Sync button manually." },
  { value: "daily", label: "Every day", hint: "Runs every day at the chosen time." },
  { value: "weekly", label: "Every week", hint: "Runs every Sunday at the chosen time." },
  {
    value: "semimonthly",
    label: "Twice a month",
    hint: "Runs on the 1st and 15th of each month.",
  },
  { value: "monthly", label: "Every month", hint: "Runs on the 1st of each month." },
];

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

/**
 * `AutosyncPanel` renders the autosync + webhook controls *without* its own
 * Card wrapper, so it can be embedded inside the Bank Connections card (the
 * two concepts are tightly coupled — autosync only matters when at least one
 * bank is connected, and the "Sync now" button lives in the same panel).
 */
export function AutosyncPanel() {
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
      // When a webhook reconcile just happened, surface the Plaid-side result
      // directly so the user knows whether their toggle actually took effect.
      const reconcile = next.webhook_reconcile;
      if (reconcile && reconcile.total > 0) {
        if (reconcile.failed === 0) {
          notify.success(
            `Webhooks ${next.webhooks_enabled ? "enabled" : "disabled"} for ${reconcile.updated} bank${reconcile.updated === 1 ? "" : "s"}.`,
          );
        } else {
          notify.error(
            `Plaid rejected ${reconcile.failed} of ${reconcile.total} webhook updates. See log tab.`,
          );
        }
      } else if (reconcile && reconcile.total === 0 && reconcile.errors.length > 0) {
        notify.error(reconcile.errors[0]);
      } else {
        notify.success("Autosync settings updated");
      }
    },
    onError: onMutationError("Could not update autosync settings"),
  });

  const handleFrequencyChange = (frequency: AutosyncFrequency) => {
    updateMutation.mutate({ frequency });
  };

  const handleWebhooksToggle = (webhooks_enabled: boolean) => {
    updateMutation.mutate({ webhooks_enabled });
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
      <div className="rounded-lg border border-border/60 p-4">
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  const disabled = updateMutation.isPending;
  const frequencyMeta = FREQUENCY_OPTIONS.find((o) => o.value === data.frequency);
  const timeDisabled = disabled || data.frequency === "off";

  return (
    <div className="space-y-3 rounded-lg border border-border/60 bg-muted/10 p-4">
      <div className="flex items-center gap-2">
        <Clock className="h-4 w-4 text-muted-foreground" />
        <p className="text-sm font-medium">Autosync schedule</p>
      </div>

      <div className="flex flex-col gap-3 sm:grid sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end sm:gap-4">
        <div className="space-y-1.5">
          <Label htmlFor="autosync-frequency" className="text-xs text-muted-foreground">
            Frequency
          </Label>
          <Select
            value={data.frequency}
            onValueChange={(v) => handleFrequencyChange(v as AutosyncFrequency)}
            disabled={disabled}
          >
            <SelectTrigger id="autosync-frequency" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FREQUENCY_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="autosync-time" className="text-xs text-muted-foreground">
            Time ({tzLabel})
          </Label>
          <Input
            id="autosync-time"
            type="time"
            step={60}
            value={timeLocal}
            onChange={(e) => handleTimeChange(e.target.value)}
            disabled={timeDisabled}
            className="w-full sm:w-32"
          />
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        {frequencyMeta?.hint}{" "}
        {data.frequency !== "off" ? (
          <>
            Stored as {String(data.hour_utc).padStart(2, "0")}
            :{String(data.minute_utc).padStart(2, "0")} UTC · Next run:{" "}
            {formatNextRun(data.next_run_at)}
          </>
        ) : null}
      </p>

      <div className="flex items-start justify-between gap-4 rounded-md border border-border/60 bg-background/50 px-3 py-2.5">
        <div className="space-y-0.5">
          <Label htmlFor="webhooks-toggle" className="flex items-center gap-2 text-sm">
            <Webhook className="h-3.5 w-3.5" />
            Instant updates (webhooks)
          </Label>
          <p className="text-xs text-muted-foreground">
            Plaid pushes new transactions the moment they post — each push costs a Balance
            call. Turn off to rely on the schedule above and cut Plaid costs roughly 2&times;.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {disabled ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
          <Switch
            id="webhooks-toggle"
            checked={data.webhooks_enabled}
            onCheckedChange={handleWebhooksToggle}
            disabled={disabled || (!data.webhooks_enabled && !data.webhook_url_configured)}
          />
        </div>
      </div>

      {!data.webhook_url_configured && data.webhooks_enabled === false ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            Webhooks can&apos;t be enabled until the server has{" "}
            <code className="font-mono text-xs">PLAID_WEBHOOK_URL</code> configured.
            Ask the app owner to set it, then flip the toggle.
          </AlertDescription>
        </Alert>
      ) : null}

      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription className="text-xs">
          Plaid bills <strong>$0.10 per Balance call</strong>. Fewer scheduled runs + webhooks
          off is typically enough for personal / family budgeting (data stays fresh to within
          one sync interval).
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
    </div>
  );
}

export default AutosyncPanel;
