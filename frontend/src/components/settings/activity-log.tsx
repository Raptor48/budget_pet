"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Cloud,
  CreditCard,
  Eraser,
  Link2,
  LogIn,
  LogOut,
  RefreshCw,
  ShieldAlert,
  Settings as SettingsIcon,
  Trash2,
  XCircle,
} from "lucide-react";

import { auditApi, plaidApi } from "@/lib/api";
import type { AuditEntry } from "@/types/v2";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/auth-context";

const CATEGORY_CHOICES: { id: string; label: string; category: string | null }[] = [
  { id: "all", label: "All", category: null },
  { id: "plaid", label: "Plaid", category: "plaid" },
  { id: "auth", label: "Auth", category: "auth" },
  { id: "settings", label: "Settings", category: "settings" },
];

const PAGE_SIZE = 50;

type Meta = Record<string, unknown>;

function iconFor(eventType: string) {
  if (eventType.startsWith("auth.login_failed")) return ShieldAlert;
  if (eventType.startsWith("auth.login")) return LogIn;
  if (eventType.startsWith("auth.logout")) return LogOut;
  if (eventType === "plaid.item_connect") return Link2;
  if (eventType === "plaid.item_remove") return Trash2;
  if (eventType === "plaid.cursor_reset") return RefreshCw;
  if (eventType === "plaid.sync_scheduled") return Cloud;
  if (eventType === "plaid.sync_manual") return RefreshCw;
  if (eventType === "plaid.sandbox_wiped") return Trash2;
  if (eventType.startsWith("settings.")) return SettingsIcon;
  return CircleDot;
}

function formatRelative(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const abs = Math.abs(diff);
    const mins = Math.round(abs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    const hours = Math.round(mins / 60);
    if (hours < 24) return `${hours} h ago`;
    const days = Math.round(hours / 24);
    if (days < 14) return `${days} d ago`;
    return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
  } catch {
    return iso;
  }
}

function formatAbsolute(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

function actorLabel(entry: AuditEntry): string {
  if (entry.source === "scheduler") return "Scheduler";
  if (entry.source === "webhook") return "Plaid webhook";
  if (entry.source === "system") return "System";
  return entry.actor_username ?? "Someone";
}

function summaryFor(entry: AuditEntry): string {
  const meta: Meta = entry.metadata || {};
  const who = actorLabel(entry);
  switch (entry.event_type) {
    case "auth.login":
      return `${who} signed in`;
    case "auth.login_failed":
      return `Failed login attempt for "${String(meta.username ?? "unknown")}"`;
    case "auth.logout":
      return `${who} signed out`;
    case "plaid.item_connect": {
      const bank = String(meta.institution_name ?? "a bank");
      return `${who} connected ${bank}`;
    }
    case "plaid.item_remove": {
      const bank = String(meta.institution_name ?? "a bank");
      const purged = meta.purge ? " (with data purge)" : "";
      return `${who} removed ${bank}${purged}`;
    }
    case "plaid.cursor_reset":
      return `${who} reset the sync cursor for ${String(meta.institution_name ?? "a bank")}`;
    case "plaid.sync_manual": {
      const items = Number(meta.items_synced ?? 0);
      const txns = Number(meta.transactions_added ?? 0);
      return `${who} ran a manual sync — +${txns} transactions across ${items} ${items === 1 ? "bank" : "banks"}`;
    }
    case "plaid.sync_scheduled": {
      const items = Number(meta.items_synced ?? 0);
      const txns = Number(meta.transactions_added ?? 0);
      const errors = Array.isArray(meta.errors) ? meta.errors.length : 0;
      const base = `Scheduled sync — +${txns} transactions across ${items} ${items === 1 ? "bank" : "banks"}`;
      return errors ? `${base}, ${errors} error${errors === 1 ? "" : "s"}` : base;
    }
    case "plaid.sandbox_wiped":
      return `${who} wiped Plaid sandbox data`;
    case "settings.autosync_updated": {
      const enabled = meta.enabled;
      const hh = String(Number(meta.hour_utc ?? 0)).padStart(2, "0");
      const mm = String(Number(meta.minute_utc ?? 0)).padStart(2, "0");
      return `${who} set autosync to ${enabled ? `daily ${hh}:${mm} UTC` : "off"}`;
    }
    default:
      return `${who} — ${entry.event_type}`;
  }
}

function sourceBadge(entry: AuditEntry) {
  const variant =
    entry.source === "scheduler"
      ? "outline"
      : entry.source === "system"
      ? "secondary"
      : entry.event_type === "auth.login_failed"
      ? "destructive"
      : "secondary";
  return (
    <Badge variant={variant} className="uppercase tracking-wide text-[10px]">
      {entry.source}
    </Badge>
  );
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  const [open, setOpen] = useState(false);
  const Icon = iconFor(entry.event_type);
  const failed = entry.event_type === "auth.login_failed" ||
    (entry.event_type === "plaid.sync_scheduled" && Boolean((entry.metadata as Meta)?.failed));
  const hasMetadata = entry.metadata && Object.keys(entry.metadata).length > 0;

  return (
    <div className="rounded-lg border border-border/60 p-3">
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border",
            failed
              ? "border-destructive/40 bg-destructive/10 text-destructive"
              : "border-border/60 bg-muted/40 text-muted-foreground",
          )}
        >
          <Icon className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium">{summaryFor(entry)}</p>
            {sourceBadge(entry)}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span title={formatAbsolute(entry.created_at)}>{formatRelative(entry.created_at)}</span>
            <span>·</span>
            <code className="rounded bg-muted px-1 py-0.5 text-[11px]">{entry.event_type}</code>
            {entry.request_ip ? (
              <>
                <span>·</span>
                <span className="font-mono">{entry.request_ip}</span>
              </>
            ) : null}
          </div>
          {hasMetadata ? (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              {open ? "Hide details" : "Show details"}
            </button>
          ) : null}
          {open && hasMetadata ? (
            <pre className="mt-2 max-h-60 overflow-auto rounded-md bg-muted/40 p-3 text-[11px] leading-relaxed">
              {JSON.stringify(entry.metadata, null, 2)}
            </pre>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function EventsFeed() {
  const { user } = useAuth();
  const isOwner = Boolean(user?.is_owner);
  const queryClient = useQueryClient();
  const [categoryId, setCategoryId] = useState<string>("all");
  const [pages, setPages] = useState<AuditEntry[][]>([]);
  const [beforeId, setBeforeId] = useState<number | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);

  const current = CATEGORY_CHOICES.find((c) => c.id === categoryId) ?? CATEGORY_CHOICES[0];

  const clearMutation = useMutation({
    mutationFn: () => auditApi.clear({ category: current.category ?? null }),
    onSuccess: async () => {
      setPages([]);
      setBeforeId(null);
      setConfirmOpen(false);
      setClearError(null);
      await queryClient.invalidateQueries({ queryKey: ["audit-log"] });
    },
    onError: (err: unknown) => {
      const message =
        err && typeof err === "object" && "message" in err
          ? String((err as { message?: unknown }).message ?? "Failed to clear log")
          : "Failed to clear log";
      setClearError(message);
    },
  });

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ["audit-log", current.category, beforeId],
    queryFn: () =>
      auditApi.list({
        limit: PAGE_SIZE,
        category: current.category,
        beforeId: beforeId ?? undefined,
      }),
    staleTime: 10_000,
  });

  // Reset accumulated pages when the filter changes.
  const filterKey = current.category ?? "all";
  const [currentFilter, setCurrentFilter] = useState(filterKey);
  if (filterKey !== currentFilter) {
    setCurrentFilter(filterKey);
    setPages([]);
    setBeforeId(null);
  }

  const entries = useMemo(() => {
    const flat: AuditEntry[] = [];
    pages.forEach((p) => flat.push(...p));
    if (data?.entries && beforeId === null && pages.length === 0) {
      flat.push(...data.entries);
    }
    return flat;
  }, [pages, data, beforeId]);

  const nextCursor = data?.next_before_id ?? null;
  const showingInitial = beforeId === null && pages.length === 0 && Boolean(data?.entries);
  const visible: AuditEntry[] = showingInitial ? data?.entries ?? [] : entries;

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Activity</CardTitle>
          <CardDescription>
            Every login, manual sync, bank connect/remove, scheduled run and
            danger-zone action is recorded here.
          </CardDescription>
        </div>
        {isOwner && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setClearError(null);
              setConfirmOpen(true);
            }}
            disabled={clearMutation.isPending}
            className="text-destructive hover:text-destructive"
          >
            <Eraser className="size-4" />
            {current.category ? `Clear ${current.label}` : "Clear log"}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {CATEGORY_CHOICES.map((c) => (
            <Button
              key={c.id}
              type="button"
              size="sm"
              variant={c.id === categoryId ? "default" : "outline"}
              onClick={() => {
                setCategoryId(c.id);
                setPages([]);
                setBeforeId(null);
              }}
            >
              {c.label}
            </Button>
          ))}
        </div>

        {isLoading && !isFetching ? (
          <div className="space-y-2">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : isError ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            <div className="mb-2 flex items-center gap-2 font-medium">
              <XCircle className="size-4" /> Failed to load activity
            </div>
            <Button size="sm" variant="outline" onClick={() => refetch()}>
              Try again
            </Button>
          </div>
        ) : visible.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
            No activity yet — once someone logs in or runs a sync, it will show up here.
          </div>
        ) : (
          <div className="space-y-2">
            {visible.map((entry) => (
              <AuditRow key={entry.id} entry={entry} />
            ))}
          </div>
        )}

        {nextCursor ? (
          <div className="flex justify-center">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (data?.entries) {
                  setPages((prev) => [...prev, data.entries]);
                }
                setBeforeId(nextCursor);
              }}
              disabled={isFetching}
            >
              {isFetching ? "Loading…" : "Load more"}
            </Button>
          </div>
        ) : null}
      </CardContent>

      <ClearLogDialog
        open={confirmOpen}
        onOpenChange={(v) => {
          setConfirmOpen(v);
          if (!v) setClearError(null);
        }}
        title={current.category ? `Clear ${current.label} activity?` : "Clear activity log?"}
        description={
          current.category
            ? `This removes every "${current.label}" entry across all family members. An "audit.log_cleared" breadcrumb is kept so other family members can still see that you cleared it.`
            : "This removes every entry across all family members. An \"audit.log_cleared\" breadcrumb is kept so other family members can still see that you cleared it."
        }
        error={clearError}
        isPending={clearMutation.isPending}
        onConfirm={() => clearMutation.mutate()}
      />
    </Card>
  );
}

function ClearLogDialog({
  open,
  onOpenChange,
  title,
  description,
  error,
  isPending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  error: string | null;
  isPending: boolean;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {error && (
          <p className="rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={isPending}
          >
            {isPending ? "Clearing…" : "Clear"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PlaidSyncFeed() {
  const { user } = useAuth();
  const isOwner = Boolean(user?.is_owner);
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["plaid-sync-log-full"],
    queryFn: () => plaidApi.getSyncLog(),
    staleTime: 10_000,
  });

  const clearMutation = useMutation({
    mutationFn: () => plaidApi.clearSyncLog(),
    onSuccess: async () => {
      setConfirmOpen(false);
      setClearError(null);
      await queryClient.invalidateQueries({ queryKey: ["plaid-sync-log-full"] });
      await queryClient.invalidateQueries({ queryKey: ["plaid-sync-log"] });
    },
    onError: (err: unknown) => {
      const message =
        err && typeof err === "object" && "message" in err
          ? String((err as { message?: unknown }).message ?? "Failed to clear sync log")
          : "Failed to clear sync log";
      setClearError(message);
    },
  });

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <CreditCard className="size-5" /> Plaid sync detail
          </CardTitle>
          <CardDescription>
            The last 50 per-item sync runs with transaction/balance counts and
            the Plaid error (if any).
          </CardDescription>
        </div>
        {isOwner && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setClearError(null);
              setConfirmOpen(true);
            }}
            disabled={clearMutation.isPending || !data || data.length === 0}
            className="text-destructive hover:text-destructive"
          >
            <Eraser className="size-4" />
            Clear sync log
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : isError ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            <div className="mb-2 flex items-center gap-2 font-medium">
              <XCircle className="size-4" /> Failed to load Plaid sync log
            </div>
            <Button size="sm" variant="outline" onClick={() => refetch()}>
              Try again
            </Button>
          </div>
        ) : !data || data.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
            No Plaid syncs recorded yet.
          </div>
        ) : (
          <div className="space-y-2">
            {data.map((entry) => {
              const ok = entry.status === "ok";
              return (
                <div
                  key={entry.id}
                  className="flex flex-col gap-2 rounded-lg border border-border/60 p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm">
                      {ok ? (
                        <CircleDot className="size-4 text-emerald-600" />
                      ) : (
                        <AlertTriangle className="size-4 text-destructive" />
                      )}
                      <span className="font-medium">
                        {formatAbsolute(entry.synced_at)}
                      </span>
                      <code className="truncate rounded bg-muted px-1 py-0.5 text-[11px]">
                        {entry.item_id}
                      </code>
                    </div>
                    {entry.error_msg ? (
                      <p className="mt-1 text-xs text-destructive">{entry.error_msg}</p>
                    ) : null}
                  </div>
                  <div className="flex gap-3 text-xs text-muted-foreground">
                    <span>+{entry.transactions_added} txns</span>
                    <span>·</span>
                    <span>{entry.balances_updated} balances</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>

      <ClearLogDialog
        open={confirmOpen}
        onOpenChange={(v) => {
          setConfirmOpen(v);
          if (!v) setClearError(null);
        }}
        title="Clear Plaid sync log?"
        description={
          "This removes every per-item sync-run row, including any old "
          + "errors. The audit log keeps a \"plaid.sync_log_cleared\" entry "
          + "so it's still traceable who wiped it."
        }
        error={clearError}
        isPending={clearMutation.isPending}
        onConfirm={() => clearMutation.mutate()}
      />
    </Card>
  );
}

export function ActivityLog() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Log</h1>
        <p className="text-muted-foreground">
          Every family member can see what happened and when.
        </p>
      </div>

      <Tabs defaultValue="activity" className="space-y-4">
        <TabsList>
          <TabsTrigger value="activity">Activity</TabsTrigger>
          <TabsTrigger value="plaid">Plaid sync detail</TabsTrigger>
        </TabsList>
        <TabsContent value="activity">
          <EventsFeed />
        </TabsContent>
        <TabsContent value="plaid">
          <PlaidSyncFeed />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default ActivityLog;
