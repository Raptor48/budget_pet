"use client";

/**
 * Activity tab — recent bot events from the bot_activity_log table.
 *
 * Saves the user from digging through Railway logs to figure out why a
 * push didn't fire or a photo didn't parse. Errors land at the top of
 * the list with a red badge and a click-to-expand traceback. The tab
 * auto-refreshes every 10 seconds while it's the active view.
 *
 * Owners get an extra "Everyone" scope toggle so they can see rows
 * belonging to other linked users — handy when one partner reports the
 * bot misfired and the admin wants the traceback without juggling logins.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowUpFromLine,
  Camera,
  Check,
  ChevronDown,
  CircleAlert,
  Copy,
  Eraser,
  Info,
  Keyboard,
  Link2,
  Loader2,
  MousePointerClick,
  ReceiptText,
  RefreshCw,
} from "lucide-react";
import { formatDistanceToNowStrict } from "date-fns";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { appSettingsApi, botApi, type BotActivityEntry } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";
import { confirm, notify, onMutationError } from "@/lib/notify";

type SeverityFilter = "all" | "error" | "warn" | "info";
type KindFilter = "all" | "error" | "incoming." | "outgoing." | "ocr." | "link.";
type ScopeFilter = "self" | "all";

const SEVERITY_LABEL: Record<Exclude<SeverityFilter, "all">, string> = {
  error: "Errors",
  warn: "Warnings",
  info: "Info",
};

const KIND_OPTIONS: { value: KindFilter; label: string }[] = [
  { value: "all", label: "All kinds" },
  { value: "error", label: "Errors only" },
  { value: "incoming.", label: "Incoming (msg / photo / callback)" },
  { value: "outgoing.", label: "Outgoing pushes" },
  { value: "ocr.", label: "OCR" },
  { value: "link.", label: "Telegram link events" },
];

const SEVERITY_ICONS = {
  error: AlertCircle,
  warn: AlertTriangle,
  info: Info,
} as const;

function pickKindIcon(kind: string) {
  if (kind === "error") return AlertCircle;
  if (kind.startsWith("ocr.")) return Camera;
  if (kind === "incoming.photo") return Camera;
  if (kind === "incoming.text") return Keyboard;
  if (kind === "incoming.callback") return MousePointerClick;
  if (kind === "incoming.command") return Keyboard;
  if (kind === "outgoing.push") return ArrowUpFromLine;
  if (kind.startsWith("link.")) return Link2;
  return ReceiptText;
}

export function BotActivityTab() {
  const qc = useQueryClient();
  const [severity, setSeverity] = useState<SeverityFilter>("all");
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [scope, setScope] = useState<ScopeFilter>("self");

  const me = useQuery({
    queryKey: ["auth", "me"],
    queryFn: getCurrentUser,
    staleTime: 60_000,
  });
  const isOwner = !!me.data?.is_owner;

  // Effective scope: only owners can fetch the cross-user view, so guard
  // against a non-owner ever being stuck in `all` mode (e.g. ownership
  // revoked while the page was open).
  const effectiveScope: ScopeFilter = isOwner ? scope : "self";

  const list = useQuery({
    queryKey: ["bot", "activity", severity, kindFilter, effectiveScope],
    queryFn: () =>
      botApi.listActivity({
        limit: 200,
        severity: severity === "all" ? undefined : severity,
        kind_prefix: kindFilter === "all" ? undefined : kindFilter,
        scope: effectiveScope,
      }),
    // Slightly chatty refresh — 10 seconds is short enough that you can
    // press a button in Telegram and watch the corresponding row appear,
    // long enough that this tab isn't a load test.
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  });

  const clearAll = useMutation({
    mutationFn: () => botApi.clearActivity(0),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "activity"] });
      notify.success("Activity cleared.");
    },
    onError: onMutationError("Couldn't clear activity."),
  });

  const requestClear = async () => {
    const ok = await confirm({
      title: "Clear all activity?",
      description:
        "Deletes every row tied to your account in the bot activity log. Outgoing push delivery is unaffected.",
      destructive: true,
      confirmLabel: "Clear",
    });
    if (ok) clearAll.mutate();
  };

  const counts = useMemo(() => {
    const data = list.data ?? [];
    return {
      total: data.length,
      errors: data.filter((r) => r.severity === "error").length,
      warns: data.filter((r) => r.severity === "warn").length,
    };
  }, [list.data]);

  // Auto-prune toggle — owner-only since it changes household-wide config.
  // 7-day window when on; 30-day safety cap when off (set in dispatcher).
  const appSettings = useQuery({
    queryKey: ["app", "settings"],
    queryFn: appSettingsApi.get,
    enabled: isOwner,
    staleTime: 60_000,
  });
  const updateAutoPrune = useMutation({
    mutationFn: (enabled: boolean) =>
      appSettingsApi.update({ bot_activity_auto_prune_enabled: enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["app", "settings"] }),
    onError: onMutationError("Couldn't change auto-clean."),
  });
  const autoPruneOn = !!appSettings.data?.bot_activity_auto_prune_enabled;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Live feed of what the bot has been up to — every photo it received,
        every push it sent, every uncaught error. Auto-refreshes every 10s.
        Errors and warnings show a click-to-expand traceback.
        {isOwner ? (
          <span className="ml-1">
            Owners can switch scope to <em>Everyone</em> to see rows from
            other linked users.
          </span>
        ) : null}
      </p>

      {isOwner ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2 text-sm">
          <div className="min-w-0">
            <div className="font-medium">Auto-clean every 7 days</div>
            <div className="text-xs text-muted-foreground">
              When on, the daily prune deletes rows older than 7 days. When
              off, a 30-day safety cap still applies so storage doesn&apos;t
              grow forever.
            </div>
          </div>
          <Switch
            checked={autoPruneOn}
            onCheckedChange={(v) => updateAutoPrune.mutate(v)}
            disabled={appSettings.isLoading || updateAutoPrune.isPending}
            aria-label="Auto-clean every 7 days"
          />
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={severity}
          onValueChange={(v) => setSeverity(v as SeverityFilter)}
        >
          <SelectTrigger className="h-9 w-[160px] text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All severities</SelectItem>
            {(["error", "warn", "info"] as const).map((s) => (
              <SelectItem key={s} value={s}>
                {SEVERITY_LABEL[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={kindFilter}
          onValueChange={(v) => setKindFilter(v as KindFilter)}
        >
          <SelectTrigger className="h-9 w-[260px] text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {KIND_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {isOwner ? (
          <Select
            value={scope}
            onValueChange={(v) => setScope(v as ScopeFilter)}
          >
            <SelectTrigger className="h-9 w-[140px] text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="self">Just me</SelectItem>
              <SelectItem value="all">Everyone</SelectItem>
            </SelectContent>
          </Select>
        ) : null}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => list.refetch()}
          disabled={list.isFetching}
          className="ml-auto"
        >
          {list.isFetching ? (
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="mr-1 h-3.5 w-3.5" />
          )}
          Refresh
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={requestClear}
          disabled={clearAll.isPending || !list.data?.length}
        >
          {clearAll.isPending ? (
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Eraser className="mr-1 h-3.5 w-3.5" />
          )}
          Clear
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{counts.total} events</span>
        {counts.errors > 0 ? (
          <Badge variant="outline" className="border-destructive/40 text-destructive">
            {counts.errors} error{counts.errors === 1 ? "" : "s"}
          </Badge>
        ) : null}
        {counts.warns > 0 ? (
          <Badge variant="outline" className="border-amber-500/40 text-amber-600 dark:text-amber-400">
            {counts.warns} warn{counts.warns === 1 ? "" : "s"}
          </Badge>
        ) : null}
      </div>

      {list.isLoading ? (
        <ul className="divide-y rounded-md border">
          {Array.from({ length: 6 }).map((_, i) => (
            <li
              key={i}
              className="flex items-start gap-3 px-4 py-3"
            >
              <Skeleton className="h-7 w-7 rounded-md" />
              <div className="flex-1 space-y-1">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-32" />
              </div>
            </li>
          ))}
        </ul>
      ) : !list.data?.length ? (
        <div className="grid place-items-center rounded-md border border-dashed py-12 text-center">
          <CircleAlert className="mb-2 h-7 w-7 text-muted-foreground" aria-hidden />
          <p className="text-sm font-medium">No activity yet</p>
          <p className="text-xs text-muted-foreground">
            Send a message or take an action — events will land here within a
            second or two.
          </p>
        </div>
      ) : (
        <ul className="divide-y rounded-md border">
          {list.data.map((entry) => (
            <ActivityRow key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ActivityRow({ entry }: { entry: BotActivityEntry }) {
  const [open, setOpen] = useState(false);
  const KindIcon = pickKindIcon(entry.kind);
  const SeverityIcon = SEVERITY_ICONS[entry.severity];
  const expandable = !!entry.error || Object.keys(entry.payload || {}).length > 0;

  return (
    <li
      className={cn(
        "flex flex-col gap-2 px-4 py-3 text-sm transition-colors",
        "hover:bg-muted/40",
        entry.severity === "error" && "bg-destructive/5",
        entry.severity === "warn" && "bg-amber-500/5",
      )}
    >
      <div
        className={cn(
          "flex items-start gap-3",
          expandable && "cursor-pointer",
        )}
        onClick={() => expandable && setOpen((v) => !v)}
        role={expandable ? "button" : undefined}
        tabIndex={expandable ? 0 : undefined}
        onKeyDown={(e) => {
          if (!expandable) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
      >
        <span
          className={cn(
            "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md",
            entry.severity === "error"
              ? "bg-destructive/15 text-destructive"
              : entry.severity === "warn"
                ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                : "bg-muted text-muted-foreground",
          )}
        >
          <KindIcon className="h-3.5 w-3.5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              {entry.kind}
            </span>
            {entry.severity !== "info" ? (
              <span
                className={cn(
                  "inline-flex items-center gap-0.5 text-[10px] font-semibold",
                  entry.severity === "error"
                    ? "text-destructive"
                    : "text-amber-600 dark:text-amber-400",
                )}
              >
                <SeverityIcon className="h-2.5 w-2.5" />
                {entry.severity.toUpperCase()}
              </span>
            ) : null}
          </div>
          <div className="text-sm font-medium leading-snug">{entry.summary}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {formatDistanceToNowStrict(new Date(entry.created_at), {
              addSuffix: true,
            })}
            {entry.username
              ? ` · @${entry.username}`
              : entry.user_id
                ? ` · user ${entry.user_id}`
                : ""}
            {entry.chat_id ? ` · chat ${entry.chat_id}` : ""}
          </div>
        </div>
        {expandable ? (
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
              open && "rotate-180",
            )}
          />
        ) : null}
      </div>
      {open ? (
        <div className="pl-10 pr-2 pb-1">
          {entry.error || Object.keys(entry.payload || {}).length > 0 ? (
            <div className="mb-1 flex items-center justify-end">
              <CopyButton entry={entry} />
            </div>
          ) : null}
          {entry.error ? (
            <pre className="max-h-[280px] overflow-auto rounded-md border bg-muted/30 p-2 text-[11px] leading-snug">
              {entry.error}
            </pre>
          ) : null}
          {Object.keys(entry.payload || {}).length > 0 ? (
            <pre className="mt-2 max-h-[200px] overflow-auto rounded-md border bg-muted/20 p-2 text-[11px] leading-snug">
              {JSON.stringify(entry.payload, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * Copy the row's traceback + payload + headline to the clipboard so the
 * user can paste it back into chat without a back-and-forth screenshot.
 * Uses navigator.clipboard with a 1.2s "copied" confirmation state.
 */
function CopyButton({ entry }: { entry: BotActivityEntry }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    const lines: string[] = [
      `[${entry.severity.toUpperCase()}] ${entry.kind}`,
      entry.summary,
      `at ${entry.created_at}`,
    ];
    if (entry.username) lines.push(`user: @${entry.username}`);
    if (entry.error) lines.push("", "Error:", entry.error);
    if (Object.keys(entry.payload || {}).length > 0) {
      lines.push("", "Payload:", JSON.stringify(entry.payload, null, 2));
    }
    const text = lines.join("\n");
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      } else {
        notify.error("Clipboard not available in this browser.");
      }
    } catch {
      notify.error("Couldn't copy to clipboard.");
    }
  };
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={onCopy}
      className="h-7 px-2 text-xs"
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
  );
}
