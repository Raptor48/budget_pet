"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BellOff,
  CalendarClock,
  CheckSquare2,
  ChevronDown,
  ChevronUp,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  Square,
  TrendingDown,
  TrendingUp,
  Wallet,
  X,
  XCircle,
} from "lucide-react";

import { AppLayout } from "@/components/layout/app-layout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { formatAccountPickerLabel } from "@/lib/account-picker-label";
import { ApiError, accountsApi, categoriesApi, recurringApi } from "@/lib/api";
import { confirm, notify, onMutationError } from "@/lib/notify";
import {
  formatNextRecurringDate,
  formatRecurringDate,
} from "@/lib/recurring-dates";
import { cn } from "@/lib/utils";
import { formatMoney } from "@/components/accounts/helpers";
import { PriceChangeBadge, classifyPriceChange } from "@/components/ui/price-change-badge";
import type { RecurringStream } from "@/types/v2";

import { CalendarView } from "./_components/calendar-view";
import {
  PRICE_CHANGE_THRESHOLD_PCT,
  SNOOZE_DAYS_DEFAULT,
  StreamAvatar,
  UserStatusPill,
  accountTag,
  effectiveUserStatus,
  formatFrequency,
  isSnoozedNow,
  monthlyCostCents,
  parsePriceChangePct,
  streamTitle,
} from "./_components/recurring-helpers";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Direction = "outflow" | "inflow";
type StatusFilter = "active" | "paused" | "cancelled" | "all";
type ViewMode = "list" | "by-category" | "calendar";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RecurringPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const streamHighlight = searchParams.get("stream");

  const [direction, setDirection] = useState<Direction>("outflow");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftLabel, setDraftLabel] = useState("");
  const [draftCategoryId, setDraftCategoryId] = useState<string>("none");

  const [createOpen, setCreateOpen] = useState(false);
  const [cAccountId, setCAccountId] = useState("");
  const [cDesc, setCDesc] = useState("");
  const [cFreq, setCFreq] = useState("MONTHLY");
  const [cAmount, setCAmount] = useState("");

  const [showAllPriceChanges, setShowAllPriceChanges] = useState(false);

  const userStatuses = useMemo<Array<"active" | "paused" | "cancelled">>(() => {
    if (statusFilter === "all") return ["active", "paused", "cancelled"];
    return [statusFilter];
  }, [statusFilter]);

  const streamsQuery = useQuery({
    queryKey: ["recurring", "streams", direction, userStatuses],
    queryFn: () => recurringApi.list(direction, true, userStatuses),
  });

  const priceChangesQuery = useQuery({
    queryKey: ["recurring", "price-changes"],
    queryFn: () => recurringApi.getPriceChanges(),
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
  });

  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => accountsApi.list(true),
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["recurring"] });
    // Insights surface recurring info — keep them in sync after a flip.
    queryClient.invalidateQueries({ queryKey: ["insights"] });
  };

  const createMutation = useMutation({
    mutationFn: () => {
      const account_id = Number(cAccountId);
      const average_amount_cents = Math.round(Number.parseFloat(cAmount) * 100);
      if (!Number.isFinite(account_id) || account_id <= 0) {
        return Promise.reject(new Error("Choose an account."));
      }
      if (!cDesc.trim()) return Promise.reject(new Error("Enter a description."));
      if (!Number.isFinite(average_amount_cents) || average_amount_cents <= 0) {
        return Promise.reject(new Error("Enter a positive amount."));
      }
      return recurringApi.create({
        account_id,
        direction,
        description: cDesc.trim(),
        frequency: cFreq,
        average_amount_cents,
      });
    },
    onSuccess: () => {
      invalidateAll();
      setCreateOpen(false);
      setCAccountId("");
      setCDesc("");
      setCAmount("");
      notify.success("Manual recurring stream added");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: number;
      payload: { user_label?: string; category_id?: number | null };
    }) => recurringApi.update(id, payload),
    onSuccess: () => {
      invalidateAll();
      setEditingId(null);
    },
    onError: onMutationError("Failed to update stream."),
  });

  const bulkMutation = useMutation({
    mutationFn: recurringApi.bulk,
    onSuccess: (res) => {
      invalidateAll();
      setSelected(new Set());
      notify.success(`Updated ${res.updated} stream${res.updated === 1 ? "" : "s"}`);
    },
    onError: onMutationError("Bulk update failed."),
  });

  const streams = useMemo(() => streamsQuery.data ?? [], [streamsQuery.data]);
  const categories = categoriesQuery.data ?? [];
  const priceAlerts = useMemo(
    () => priceChangesQuery.data ?? [],
    [priceChangesQuery.data],
  );

  // Effective monthly $ impact of a price change — drives sort order in the
  // movers section ("AT&T −$65/mo" beats "Adobe −$7/mo" even if the % is
  // smaller).
  const movers = useMemo(() => {
    const items = priceAlerts
      .map((s) => {
        const pct = parsePriceChangePct(s.price_change_pct);
        const last = s.last_amount_cents ?? 0;
        const avg = s.average_amount_cents ?? 0;
        const monthlyDeltaCents = (last - avg) * monthlyCadenceMultiplier(s.frequency);
        return { stream: s, pct, monthlyDeltaCents };
      })
      .filter((x) => x.pct != null);
    return items.sort((a, b) => Math.abs(b.monthlyDeltaCents) - Math.abs(a.monthlyDeltaCents));
  }, [priceAlerts]);

  useEffect(() => {
    if (!streamHighlight || streams.length === 0) return;
    const id = Number(streamHighlight);
    if (!Number.isFinite(id)) return;
    const el = document.getElementById(`recurring-row-${id}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      window.setTimeout(() => {
        if (typeof window !== "undefined" && window.history?.replaceState) {
          window.history.replaceState(null, "", "/recurring");
        }
      }, 400);
    }
  }, [streamHighlight, streams]);

  // Drop selection when filters change so we don't carry IDs that are no
  // longer visible in the list.
  useEffect(() => {
    setSelected(new Set());
  }, [direction, statusFilter, viewMode]);

  const errorMessage =
    streamsQuery.error instanceof ApiError
      ? streamsQuery.error.message
      : streamsQuery.error instanceof Error
        ? streamsQuery.error.message
        : null;

  const startEdit = (row: RecurringStream) => {
    setEditingId(row.id);
    setDraftLabel(row.user_label ?? "");
    setDraftCategoryId(row.category_id != null ? String(row.category_id) : "none");
  };

  const cancelEdit = () => {
    setEditingId(null);
    updateMutation.reset();
  };

  const saveEdit = (id: number) => {
    const trimmed = draftLabel.trim();
    updateMutation.mutate({
      id,
      payload: {
        user_label: trimmed.length ? trimmed : "",
        category_id: draftCategoryId === "none" ? null : Number(draftCategoryId),
      },
    });
  };

  const toggleSelect = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const selectAllVisible = (rows: RecurringStream[]) =>
    setSelected((prev) => {
      const allIds = rows.map((r) => r.id);
      const allSelected = allIds.every((id) => prev.has(id));
      if (allSelected) return new Set();
      return new Set(allIds);
    });

  const handleSingleAction = async (
    stream: RecurringStream,
    action: "cancel" | "pause" | "reactivate" | "snooze_price_change",
  ) => {
    if (action === "cancel") {
      const ok = await confirm({
        title: `Mark “${streamTitle(stream)}” as cancelled?`,
        description:
          "Plaid can't actually cancel the subscription with the merchant — you still need to do that yourself. This just hides the stream from KPIs and Insights, keeping the history.",
        confirmLabel: "Mark cancelled",
        destructive: true,
      });
      if (!ok) return;
    }
    bulkMutation.mutate({ ids: [stream.id], action });
  };

  // ---------------------------------------------------------------------------
  // Derived KPIs (client-side; small list, no need for a server endpoint)
  // ---------------------------------------------------------------------------

  // KPIs always reflect *active* streams of the current direction, regardless
  // of the visible status filter — otherwise switching to "Cancelled" tab
  // would lie and tell the user their monthly burn is $0.
  const kpiStreams = useMemo(() => {
    if (statusFilter === "active") return streams;
    // fall back to a separate fetch path: refetch active set… but cheaper —
    // when the filter is broad, derive from the in-memory slice.
    return streams.filter((s) => effectiveUserStatus(s) === "active");
  }, [streams, statusFilter]);

  const monthlyTotalCents = useMemo(
    () => kpiStreams.reduce((acc, s) => acc + monthlyCostCents(s), 0),
    [kpiStreams],
  );
  const annualTotalCents = monthlyTotalCents * 12;
  const activeCount = kpiStreams.length;
  const nextUp = useMemo(() => {
    // streams come pre-sorted by next payment in the API.
    return kpiStreams.find(
      (s) => s.last_date && s.frequency && s.frequency !== "UNKNOWN",
    );
  }, [kpiStreams]);

  const visibleRows = streams; // already filtered server-side
  const allVisibleSelected =
    visibleRows.length > 0 && visibleRows.every((r) => selected.has(r.id));

  return (
    <AppLayout>
      <TooltipProvider>
        <div className="space-y-6 pb-24">
          {/* Header */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">Recurring</h1>
              <p className="text-muted-foreground text-sm">
                Subscriptions and recurring inflows synced from your bank. Add manual
                bills that behave like Plaid streams.
              </p>
            </div>
            <button
              type="button"
              className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              onClick={() => {
                createMutation.reset();
                setCreateOpen(true);
              }}
            >
              <Plus className="size-4" />
              Add manual recurring
            </button>
          </div>

          {/* KPI strip */}
          <KpiStrip
            direction={direction}
            monthlyCents={monthlyTotalCents}
            annualCents={annualTotalCents}
            activeCount={activeCount}
            nextUp={nextUp ?? null}
          />

          {/* Movers (price changes) */}
          {movers.length > 0 && direction === "outflow" ? (
            <MoversSection
              movers={movers}
              showAll={showAllPriceChanges}
              onToggleShowAll={() => setShowAllPriceChanges((v) => !v)}
              onChipClick={(id) => {
                const el = document.getElementById(`recurring-row-${id}`);
                if (el) {
                  el.scrollIntoView({ behavior: "smooth", block: "center" });
                  el.classList.add("ring-2", "ring-primary", "ring-offset-2", "ring-offset-background");
                  window.setTimeout(() => {
                    el.classList.remove("ring-2", "ring-primary", "ring-offset-2", "ring-offset-background");
                  }, 2000);
                }
              }}
              onSnooze={(id) =>
                bulkMutation.mutate({
                  ids: [id],
                  action: "snooze_price_change",
                  snooze_days: SNOOZE_DAYS_DEFAULT,
                })
              }
            />
          ) : null}

          {errorMessage ? (
            <p className="text-destructive text-sm" role="alert">
              {errorMessage}
            </p>
          ) : null}

          {/* Tabs + filters */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <Tabs
              value={direction === "outflow" ? "out" : "in"}
              onValueChange={(v) => setDirection(v === "out" ? "outflow" : "inflow")}
            >
              <TabsList>
                <TabsTrigger value="out">Outflows</TabsTrigger>
                <TabsTrigger value="in">Inflows</TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="flex flex-wrap items-center gap-2">
              <StatusFilterBar value={statusFilter} onChange={setStatusFilter} />
              <ViewModeBar value={viewMode} onChange={setViewMode} />
            </div>
          </div>

          {/* Body */}
          {streamsQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">Loading…</p>
          ) : visibleRows.length === 0 ? (
            <EmptyState statusFilter={statusFilter} />
          ) : viewMode === "list" ? (
            <ListView
              rows={visibleRows}
              streamHighlight={streamHighlight}
              selected={selected}
              allVisibleSelected={allVisibleSelected}
              onToggleAll={() => selectAllVisible(visibleRows)}
              onToggleSelect={toggleSelect}
              editingId={editingId}
              draftLabel={draftLabel}
              draftCategoryId={draftCategoryId}
              setDraftLabel={setDraftLabel}
              setDraftCategoryId={setDraftCategoryId}
              categories={categories}
              startEdit={startEdit}
              cancelEdit={cancelEdit}
              saveEdit={saveEdit}
              isUpdating={updateMutation.isPending}
              onAction={handleSingleAction}
              monthlyTotalCents={monthlyTotalCents}
              annualTotalCents={annualTotalCents}
            />
          ) : viewMode === "by-category" ? (
            <ByCategoryView
              rows={visibleRows}
              streamHighlight={streamHighlight}
              selected={selected}
              onToggleSelect={toggleSelect}
              onAction={handleSingleAction}
            />
          ) : (
            <CalendarView
              rows={visibleRows}
              onJumpToRow={(id) => {
                setViewMode("list");
                // The list-view row scroll is handled by the same effect
                // that watches `?stream=`. Defer to the next tick so the
                // List re-renders with rows present before we scroll.
                window.setTimeout(() => {
                  const el = document.getElementById(`recurring-row-${id}`);
                  if (el) {
                    el.scrollIntoView({ behavior: "smooth", block: "center" });
                    el.classList.add("ring-2", "ring-primary", "ring-offset-2", "ring-offset-background");
                    window.setTimeout(() => {
                      el.classList.remove("ring-2", "ring-primary", "ring-offset-2", "ring-offset-background");
                    }, 2000);
                  }
                }, 50);
              }}
            />
          )}
        </div>

        {/* Floating bulk action bar */}
        {selected.size > 0 ? (
          <BulkActionBar
            count={selected.size}
            monthlySavingsCents={visibleRows
              .filter((s) => selected.has(s.id))
              .reduce((acc, s) => acc + monthlyCostCents(s), 0)}
            disabled={bulkMutation.isPending}
            onClear={() => setSelected(new Set())}
            onCancel={async () => {
              const ok = await confirm({
                title: `Mark ${selected.size} stream${
                  selected.size === 1 ? "" : "s"
                } as cancelled?`,
                description:
                  "Plaid can't actually cancel subscriptions with merchants — you still need to do that yourself. This hides them from KPIs and Insights.",
                confirmLabel: "Mark cancelled",
                destructive: true,
              });
              if (!ok) return;
              bulkMutation.mutate({
                ids: Array.from(selected),
                action: "cancel",
              });
            }}
            onPause={() =>
              bulkMutation.mutate({
                ids: Array.from(selected),
                action: "pause",
              })
            }
            onReactivate={() =>
              bulkMutation.mutate({
                ids: Array.from(selected),
                action: "reactivate",
              })
            }
            onSnooze={() =>
              bulkMutation.mutate({
                ids: Array.from(selected),
                action: "snooze_price_change",
                snooze_days: SNOOZE_DAYS_DEFAULT,
              })
            }
          />
        ) : null}

        {/* Add-manual dialog */}
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add manual recurring</DialogTitle>
              <DialogDescription>
                Creates a stream in the same list as Plaid data. Plaid sync will not
                overwrite it.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-3 py-2">
              <div className="grid gap-2">
                <Label>Direction (tab)</Label>
                <p className="text-muted-foreground text-xs">
                  Uses the current tab: {direction}.
                </p>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="mr-acct">Account</Label>
                <Select value={cAccountId} onValueChange={setCAccountId}>
                  <SelectTrigger id="mr-acct">
                    <SelectValue placeholder="Select account" />
                  </SelectTrigger>
                  <SelectContent>
                    {(accountsQuery.data ?? []).map((a) => (
                      <SelectItem key={a.id} value={String(a.id)}>
                        {formatAccountPickerLabel(a)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="mr-desc">Description</Label>
                <Input
                  id="mr-desc"
                  value={cDesc}
                  onChange={(e) => setCDesc(e.target.value)}
                  maxLength={200}
                />
              </div>
              <div className="grid gap-2">
                <Label>Frequency</Label>
                <Select value={cFreq} onValueChange={setCFreq}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[
                      "WEEKLY",
                      "BIWEEKLY",
                      "SEMI_MONTHLY",
                      "MONTHLY",
                      "ANNUALLY",
                      "UNKNOWN",
                    ].map((f) => (
                      <SelectItem key={f} value={f}>
                        {f.replaceAll("_", " ")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="mr-amt">Amount (USD, per period)</Label>
                <Input
                  id="mr-amt"
                  inputMode="decimal"
                  placeholder="e.g. 49.99"
                  value={cAmount}
                  onChange={(e) => setCAmount(e.target.value)}
                />
              </div>
              {createMutation.isError ? (
                <p className="text-destructive text-sm">
                  {createMutation.error instanceof Error
                    ? createMutation.error.message
                    : "Could not create."}
                </p>
              ) : null}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                disabled={createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                Save
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </TooltipProvider>
    </AppLayout>
  );
}

// ---------------------------------------------------------------------------
// KPI strip
// ---------------------------------------------------------------------------

function KpiStrip({
  direction,
  monthlyCents,
  annualCents,
  activeCount,
  nextUp,
}: {
  direction: Direction;
  monthlyCents: number;
  annualCents: number;
  activeCount: number;
  nextUp: RecurringStream | null;
}) {
  const isOut = direction === "outflow";
  const monthLabel = isOut ? "Monthly outflows" : "Monthly inflows";
  const yearLabel = isOut ? "Annual outflows" : "Annual inflows";
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KpiCard
        icon={<Wallet className="size-4" aria-hidden />}
        label={monthLabel}
        value={formatMoney(monthlyCents)}
        sub={`${activeCount} active stream${activeCount === 1 ? "" : "s"}`}
      />
      <KpiCard
        icon={<TrendingUp className="size-4" aria-hidden />}
        label={yearLabel}
        value={formatMoney(annualCents)}
        sub="Estimate · 12× monthly equivalent"
      />
      <KpiCard
        icon={<CalendarClock className="size-4" aria-hidden />}
        label="Next payment"
        value={
          nextUp
            ? formatNextRecurringDate(nextUp.last_date, nextUp.frequency)
            : "—"
        }
        sub={
          nextUp
            ? `${streamTitle(nextUp)} · ${formatMoney(
                Math.abs(nextUp.last_amount_cents ?? nextUp.average_amount_cents ?? 0),
              )}`
            : "Nothing scheduled"
        }
      />
      <KpiCard
        icon={<AlertTriangle className="size-4" aria-hidden />}
        label="Plaid limitation"
        value="Read-only"
        sub="We can mark cancelled — you still cancel with the merchant."
      />
    </div>
  );
}

function KpiCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <Card className="border-border/70">
      <CardContent className="flex flex-col gap-1 p-4">
        <div className="text-muted-foreground inline-flex items-center gap-1.5 text-xs uppercase tracking-wide">
          {icon}
          <span>{label}</span>
        </div>
        <div className="text-2xl font-semibold tracking-tight tabular-nums">
          {value}
        </div>
        {sub ? <div className="text-muted-foreground text-xs">{sub}</div> : null}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Movers (price changes) — top hikes + drops by $ impact, click → scroll, snooze
// ---------------------------------------------------------------------------

function monthlyCadenceMultiplier(freq: string | null | undefined): number {
  const f = (freq || "").toUpperCase();
  switch (f) {
    case "WEEKLY":
      return 52 / 12;
    case "BIWEEKLY":
      return 26 / 12;
    case "SEMI_MONTHLY":
      return 2;
    case "MONTHLY":
      return 1;
    case "ANNUALLY":
      return 1 / 12;
    default:
      return 1;
  }
}

type Mover = {
  stream: RecurringStream;
  pct: number | null;
  monthlyDeltaCents: number;
};

function MoversSection({
  movers,
  showAll,
  onToggleShowAll,
  onChipClick,
  onSnooze,
}: {
  movers: Mover[];
  showAll: boolean;
  onToggleShowAll: () => void;
  onChipClick: (id: number) => void;
  onSnooze: (id: number) => void;
}) {
  const hikes = movers.filter((m) => m.monthlyDeltaCents > 0);
  const drops = movers.filter((m) => m.monthlyDeltaCents < 0);
  const HIDDEN_TAKE = 3;
  const hikesToShow = showAll ? hikes : hikes.slice(0, HIDDEN_TAKE);
  const dropsToShow = showAll ? drops : drops.slice(0, HIDDEN_TAKE);
  const hiddenCount = hikes.length + drops.length - hikesToShow.length - dropsToShow.length;

  return (
    <Card className="border-border/70 bg-muted/20">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Price changes</CardTitle>
        <p className="text-muted-foreground text-xs">
          Streams with notable movement vs the long-term average. Sorted by monthly
          $ impact, not %. Click a chip to jump to the row.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {hikesToShow.length > 0 ? (
          <MoverRow
            heading="Got more expensive"
            tone="warn"
            movers={hikesToShow}
            onChipClick={onChipClick}
            onSnooze={onSnooze}
          />
        ) : null}
        {dropsToShow.length > 0 ? (
          <MoverRow
            heading="Got cheaper"
            tone="good"
            movers={dropsToShow}
            onChipClick={onChipClick}
            onSnooze={onSnooze}
          />
        ) : null}
        {hiddenCount > 0 || showAll ? (
          <button
            type="button"
            onClick={onToggleShowAll}
            className="text-muted-foreground hover:text-foreground self-start text-xs underline-offset-2 hover:underline"
          >
            {showAll
              ? "Show fewer"
              : `Show ${hiddenCount} more change${hiddenCount === 1 ? "" : "s"}`}
          </button>
        ) : null}
      </CardContent>
    </Card>
  );
}

function MoverRow({
  heading,
  tone,
  movers,
  onChipClick,
  onSnooze,
}: {
  heading: string;
  tone: "warn" | "good";
  movers: Mover[];
  onChipClick: (id: number) => void;
  onSnooze: (id: number) => void;
}) {
  const Icon = tone === "warn" ? TrendingUp : TrendingDown;
  const toneClass =
    tone === "warn"
      ? "border-orange-500/50 bg-orange-500/10 text-orange-800 hover:bg-orange-500/20 dark:text-orange-200"
      : "border-emerald-500/50 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-300";
  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-muted-foreground inline-flex items-center gap-1 text-[11px] uppercase tracking-wide">
        <Icon className="size-3" aria-hidden />
        <span>{heading}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {movers.map(({ stream, monthlyDeltaCents, pct }) => {
          const label = streamTitle(stream);
          const dollar = formatMoney(Math.abs(monthlyDeltaCents));
          const pctLabel = pct != null ? `${pct > 0 ? "+" : "−"}${Math.abs(Math.round(pct))}%` : "";
          return (
            <div
              key={stream.id}
              className={cn(
                "group inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs",
                toneClass,
              )}
            >
              <button
                type="button"
                className="inline-flex max-w-[260px] items-center gap-1.5 truncate"
                onClick={() => onChipClick(stream.id)}
                title={`${label}: ${monthlyDeltaCents > 0 ? "+" : "−"}${dollar}/mo (${pctLabel})`}
              >
                <span className="truncate font-medium">{label}</span>
                <span className="shrink-0 tabular-nums">
                  {monthlyDeltaCents > 0 ? "+" : "−"}
                  {dollar}/mo
                </span>
                <span className="shrink-0 opacity-70 tabular-nums">{pctLabel}</span>
              </button>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSnooze(stream.id);
                    }}
                    className="opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
                    aria-label="Snooze this alert for 30 days"
                  >
                    <BellOff className="size-3" />
                  </button>
                </TooltipTrigger>
                <TooltipContent>Snooze for {SNOOZE_DAYS_DEFAULT} days</TooltipContent>
              </Tooltip>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status + view filter bars
// ---------------------------------------------------------------------------

function StatusFilterBar({
  value,
  onChange,
}: {
  value: StatusFilter;
  onChange: (v: StatusFilter) => void;
}) {
  const options: Array<{ key: StatusFilter; label: string }> = [
    { key: "active", label: "Active" },
    { key: "paused", label: "Paused" },
    { key: "cancelled", label: "Cancelled" },
    { key: "all", label: "All" },
  ];
  return (
    <div className="bg-muted text-muted-foreground inline-flex h-9 items-center rounded-md p-1">
      {options.map((opt) => (
        <button
          key={opt.key}
          type="button"
          onClick={() => onChange(opt.key)}
          className={cn(
            "h-7 rounded-sm px-2.5 text-xs transition-colors",
            value === opt.key
              ? "bg-background text-foreground shadow-sm"
              : "hover:text-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function ViewModeBar({
  value,
  onChange,
}: {
  value: ViewMode;
  onChange: (v: ViewMode) => void;
}) {
  return (
    <div className="bg-muted text-muted-foreground inline-flex h-9 items-center rounded-md p-1">
      {[
        { key: "list" as const, label: "List" },
        { key: "by-category" as const, label: "By category" },
        { key: "calendar" as const, label: "Calendar" },
      ].map((opt) => (
        <button
          key={opt.key}
          type="button"
          onClick={() => onChange(opt.key)}
          className={cn(
            "h-7 rounded-sm px-2.5 text-xs transition-colors",
            value === opt.key
              ? "bg-background text-foreground shadow-sm"
              : "hover:text-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState({ statusFilter }: { statusFilter: StatusFilter }) {
  const message =
    statusFilter === "cancelled"
      ? "No cancelled streams yet. Streams you mark cancelled show up here."
      : statusFilter === "paused"
        ? "Nothing paused. Use the row menu to pause a stream."
        : "No recurring streams for this tab. Add a manual one or wait for Plaid sync.";
  return (
    <div className="rounded-lg border border-dashed py-12 text-center text-sm text-muted-foreground">
      {message}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List view (table)
// ---------------------------------------------------------------------------

type ListViewProps = {
  rows: RecurringStream[];
  streamHighlight: string | null;
  selected: Set<number>;
  allVisibleSelected: boolean;
  onToggleAll: () => void;
  onToggleSelect: (id: number) => void;
  editingId: number | null;
  draftLabel: string;
  draftCategoryId: string;
  setDraftLabel: (v: string) => void;
  setDraftCategoryId: (v: string) => void;
  categories: Array<{ id: number; name: string }>;
  startEdit: (row: RecurringStream) => void;
  cancelEdit: () => void;
  saveEdit: (id: number) => void;
  isUpdating: boolean;
  onAction: (
    stream: RecurringStream,
    action: "cancel" | "pause" | "reactivate" | "snooze_price_change",
  ) => void;
  monthlyTotalCents: number;
  annualTotalCents: number;
};

function ListView({
  rows,
  streamHighlight,
  selected,
  allVisibleSelected,
  onToggleAll,
  onToggleSelect,
  editingId,
  draftLabel,
  draftCategoryId,
  setDraftLabel,
  setDraftCategoryId,
  categories,
  startEdit,
  cancelEdit,
  saveEdit,
  isUpdating,
  onAction,
  monthlyTotalCents,
  annualTotalCents,
}: ListViewProps) {
  return (
    <div className="overflow-hidden rounded-md border">
      {/* Mobile select-all bar — visually compact, mirrors the desktop header. */}
      <div className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2 text-xs sm:hidden">
        <button
          type="button"
          onClick={onToggleAll}
          className="hover:text-foreground inline-flex size-5 items-center justify-center text-muted-foreground"
          aria-label={allVisibleSelected ? "Clear selection" : "Select all visible"}
        >
          {allVisibleSelected ? (
            <CheckSquare2 className="size-4" />
          ) : (
            <Square className="size-4" />
          )}
        </button>
        <span className="text-muted-foreground">
          {allVisibleSelected ? "Clear selection" : "Select all visible"}
        </span>
      </div>
      {/* Desktop column header. Widths match RecurringRow's per-column shrink-0. */}
      <div className="hidden bg-muted/30 items-center gap-3 border-b px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground sm:flex">
        <button
          type="button"
          onClick={onToggleAll}
          className="hover:text-foreground inline-flex size-5 shrink-0 items-center justify-center"
          aria-label={allVisibleSelected ? "Clear selection" : "Select all visible"}
        >
          {allVisibleSelected ? (
            <CheckSquare2 className="size-4" />
          ) : (
            <Square className="size-4" />
          )}
        </button>
        {/* 36 (avatar) + 12 (gap) align the Description label to row content. */}
        <span className="ml-[48px] flex-1">Description</span>
        <span className="w-[120px] shrink-0">Next payment</span>
        <span className="w-[110px] shrink-0 text-right">Amount</span>
        <span className="w-[160px] shrink-0">Category</span>
        <span className="w-8 shrink-0 sr-only">Actions</span>
      </div>
      {rows.map((row) => (
        <RecurringRow
          key={row.id}
          row={row}
          isHighlighted={streamHighlight === String(row.id)}
          isSelected={selected.has(row.id)}
          onToggleSelect={() => onToggleSelect(row.id)}
          isEditing={editingId === row.id}
          draftLabel={draftLabel}
          draftCategoryId={draftCategoryId}
          setDraftLabel={setDraftLabel}
          setDraftCategoryId={setDraftCategoryId}
          categories={categories}
          onStartEdit={() => startEdit(row)}
          onCancelEdit={cancelEdit}
          onSaveEdit={() => saveEdit(row.id)}
          isUpdating={isUpdating}
          editLockedByOther={editingId != null && editingId !== row.id}
          onAction={(action) => onAction(row, action)}
        />
      ))}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t bg-muted/20 px-3 py-2 text-xs sm:px-4">
        <span className="text-muted-foreground">
          {rows.length} stream{rows.length === 1 ? "" : "s"}
        </span>
        <span className="inline-flex items-center gap-3 tabular-nums">
          <span className="font-medium">{formatMoney(monthlyTotalCents)}/mo</span>
          <span className="text-muted-foreground">
            ≈ {formatMoney(annualTotalCents)}/yr
          </span>
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single row
// ---------------------------------------------------------------------------

function RecurringRow({
  row,
  isHighlighted,
  isSelected,
  onToggleSelect,
  isEditing,
  draftLabel,
  draftCategoryId,
  setDraftLabel,
  setDraftCategoryId,
  categories,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  isUpdating,
  editLockedByOther,
  onAction,
}: {
  row: RecurringStream;
  isHighlighted: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
  isEditing: boolean;
  draftLabel: string;
  draftCategoryId: string;
  setDraftLabel: (v: string) => void;
  setDraftCategoryId: (v: string) => void;
  categories: Array<{ id: number; name: string }>;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  isUpdating: boolean;
  editLockedByOther: boolean;
  onAction: (
    action: "cancel" | "pause" | "reactivate" | "snooze_price_change",
  ) => void;
}) {
  const title = streamTitle(row);
  const pct = parsePriceChangePct(row.price_change_pct);
  const showPriceAlert =
    pct != null && Math.abs(pct) > PRICE_CHANGE_THRESHOLD_PCT && !isSnoozedNow(row);
  const lifecycle = effectiveUserStatus(row);
  const muted = lifecycle === "cancelled";
  const categoryColor = row.primary_category_color ?? null;
  const categoryName = row.primary_category_name?.trim() || null;
  const acctTag = accountTag(row);

  return (
    <div
      id={`recurring-row-${row.id}`}
      className={cn(
        "group relative flex items-start gap-2 border-b px-3 py-3 last:border-b-0 sm:items-center sm:gap-3 sm:px-4",
        "transition-colors hover:bg-muted/40",
        isSelected && "bg-primary/5",
        isHighlighted && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        muted && "opacity-60",
      )}
    >
      {/* Category color accent painted as a left bar */}
      {categoryColor ? (
        <span
          aria-hidden
          className="absolute inset-y-2 left-0 w-[3px] rounded-r"
          style={{ backgroundColor: categoryColor }}
        />
      ) : null}

      {/* Checkbox */}
      <button
        type="button"
        onClick={onToggleSelect}
        className="hover:text-primary mt-1 inline-flex size-5 shrink-0 items-center justify-center text-muted-foreground sm:mt-0"
        aria-label={isSelected ? "Deselect" : "Select"}
      >
        {isSelected ? <CheckSquare2 className="size-4" /> : <Square className="size-4" />}
      </button>

      {/* Avatar */}
      <StreamAvatar stream={row} size={36} />

      {/* Description / edit form */}
      <div className="min-w-0 flex-1">
        {isEditing ? (
          <div className="flex flex-col gap-2">
            <Input
              value={draftLabel}
              onChange={(e) => setDraftLabel(e.target.value)}
              placeholder="Custom label"
            />
            <Select value={draftCategoryId} onValueChange={setDraftCategoryId}>
              <SelectTrigger className="h-9 w-full min-w-0">
                <SelectValue placeholder="Category" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Uncategorized</SelectItem>
                {categories.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex gap-1">
              <Button
                type="button"
                size="sm"
                onClick={onSaveEdit}
                disabled={isUpdating}
              >
                Save
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onCancelEdit}
                disabled={isUpdating}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <span
                    className="min-w-0 max-w-full truncate text-sm font-medium leading-tight"
                    title={row.description}
                  >
                    {title}
                  </span>
                </TooltipTrigger>
                {acctTag ? (
                  <TooltipContent side="top" align="start">
                    Charged to {acctTag}
                  </TooltipContent>
                ) : null}
              </Tooltip>
              <UserStatusPill status={lifecycle} />
              {showPriceAlert ? (
                <PriceChangeBadge pct={pct} direction={row.direction} compact />
              ) : null}
              {isSnoozedNow(row) ? (
                <span
                  className="text-muted-foreground inline-flex items-center gap-1 rounded-full border bg-muted/40 px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
                  title={`Price-change alerts snoozed until ${row.price_change_snoozed_until}`}
                >
                  <BellOff className="size-2.5" />
                  Snoozed
                </span>
              ) : null}
            </div>
            <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
              <span>{formatFrequency(row.frequency)}</span>
              {acctTag ? (
                <>
                  <span aria-hidden>·</span>
                  <span className="truncate">{acctTag}</span>
                </>
              ) : null}
            </div>
            {/* Mobile-only secondary line — fold the desktop columns
                (next-payment + category) into the description block so the
                whole row stays readable on a phone. Hidden ≥ sm where the
                dedicated columns take over. */}
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs sm:hidden">
              <span className="text-muted-foreground inline-flex items-center gap-1">
                <CalendarClock className="size-3" aria-hidden />
                <span className="text-foreground tabular-nums">
                  {formatNextRecurringDate(row.last_date, row.frequency)}
                </span>
                {row.last_date ? (
                  <span>· last {formatRecurringDate(row.last_date)}</span>
                ) : null}
              </span>
              {categoryName ? (
                <span
                  className="inline-flex max-w-full items-center gap-1 truncate rounded-full bg-muted/60 px-1.5 py-0.5"
                  title={categoryName}
                >
                  {categoryColor ? (
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ backgroundColor: categoryColor }}
                      aria-hidden
                    />
                  ) : null}
                  <span className="truncate">{categoryName}</span>
                </span>
              ) : null}
            </div>
          </>
        )}
      </div>

      {/* Desktop-only: Next payment column */}
      <div className="hidden w-[120px] shrink-0 text-xs leading-tight sm:block">
        <div className="text-foreground tabular-nums">
          {formatNextRecurringDate(row.last_date, row.frequency)}
        </div>
        {row.last_date ? (
          <div className="text-muted-foreground tabular-nums">
            last {formatRecurringDate(row.last_date)}
          </div>
        ) : null}
      </div>

      {/* Amount (always visible, narrower on mobile) */}
      <div className="w-[88px] shrink-0 sm:w-[110px]">
        <AmountCell row={row} />
      </div>

      {/* Desktop-only: Category column */}
      <div className="hidden w-[160px] shrink-0 sm:block">
        {categoryName ? (
          <span
            className="inline-flex max-w-full items-center gap-1.5 truncate rounded-full bg-muted/60 px-2 py-0.5 text-xs"
            title={categoryName}
          >
            {categoryColor ? (
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: categoryColor }}
                aria-hidden
              />
            ) : null}
            <span className="truncate">{categoryName}</span>
          </span>
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        )}
      </div>

      {/* Actions: always visible on touch (no hover), hover-only on desktop */}
      <div className="flex shrink-0 items-center justify-end gap-1 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100">
        <RowActionsMenu
          stream={row}
          onAction={onAction}
          onStartEdit={onStartEdit}
          editLockedByOther={editLockedByOther}
        />
      </div>
    </div>
  );
}

function AmountCell({ row }: { row: RecurringStream }) {
  const last = row.last_amount_cents ?? 0;
  const avg = row.average_amount_cents ?? 0;
  const pct = parsePriceChangePct(row.price_change_pct);
  const tone = classifyPriceChange(pct, row.direction);
  const lastClass =
    tone === "warn"
      ? "text-orange-700 dark:text-orange-300"
      : tone === "good"
        ? "text-emerald-700 dark:text-emerald-300"
        : "text-foreground";
  return (
    <div className="text-right tabular-nums leading-tight">
      <div className={cn("text-sm font-semibold", lastClass)}>
        {formatMoney(Math.abs(last))}
      </div>
      <div className="text-muted-foreground text-xs">
        avg {formatMoney(Math.abs(avg))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row actions popover
// ---------------------------------------------------------------------------

function RowActionsMenu({
  stream,
  onAction,
  onStartEdit,
  editLockedByOther,
}: {
  stream: RecurringStream;
  onAction: (
    action: "cancel" | "pause" | "reactivate" | "snooze_price_change",
  ) => void;
  onStartEdit: () => void;
  editLockedByOther: boolean;
}) {
  const [open, setOpen] = useState(false);
  const status = effectiveUserStatus(stream);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label="Stream actions"
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-52 p-1">
        <RowActionItem
          icon={<Pencil className="size-4" />}
          label="Edit label & category"
          disabled={editLockedByOther}
          onClick={() => {
            setOpen(false);
            onStartEdit();
          }}
        />
        {status !== "paused" ? (
          <RowActionItem
            icon={<Pause className="size-4" />}
            label="Pause"
            onClick={() => {
              setOpen(false);
              onAction("pause");
            }}
          />
        ) : null}
        {status !== "active" ? (
          <RowActionItem
            icon={<Play className="size-4" />}
            label="Reactivate"
            onClick={() => {
              setOpen(false);
              onAction("reactivate");
            }}
          />
        ) : null}
        <RowActionItem
          icon={<BellOff className="size-4" />}
          label={`Snooze price alert ${SNOOZE_DAYS_DEFAULT}d`}
          onClick={() => {
            setOpen(false);
            onAction("snooze_price_change");
          }}
        />
        {status !== "cancelled" ? (
          <RowActionItem
            icon={<XCircle className="size-4" />}
            label="Mark cancelled"
            destructive
            onClick={() => {
              setOpen(false);
              onAction("cancel");
            }}
          />
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

function RowActionItem({
  icon,
  label,
  onClick,
  disabled,
  destructive,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  destructive?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm transition-colors",
        "disabled:pointer-events-none disabled:opacity-50",
        destructive
          ? "text-destructive hover:bg-destructive/10"
          : "hover:bg-muted",
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Bulk action bar (floating at bottom)
// ---------------------------------------------------------------------------

function BulkActionBar({
  count,
  monthlySavingsCents,
  disabled,
  onClear,
  onCancel,
  onPause,
  onReactivate,
  onSnooze,
}: {
  count: number;
  monthlySavingsCents: number;
  disabled: boolean;
  onClear: () => void;
  onCancel: () => void;
  onPause: () => void;
  onReactivate: () => void;
  onSnooze: () => void;
}) {
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-3 z-30 flex justify-center px-3">
      <div className="bg-background pointer-events-auto inline-flex max-w-full flex-wrap items-center gap-1.5 rounded-2xl border px-2.5 py-1.5 shadow-lg sm:gap-2 sm:rounded-full sm:px-3 sm:py-2">
        <span className="text-sm font-medium">{count} selected</span>
        <span className="text-muted-foreground hidden tabular-nums text-xs sm:inline">
          ≈ {formatMoney(monthlySavingsCents)}/mo
        </span>
        <span className="bg-border mx-0.5 h-5 w-px sm:mx-1" aria-hidden />
        <BulkButton
          icon={<Pause className="size-3.5" />}
          label="Pause"
          disabled={disabled}
          onClick={onPause}
        />
        <BulkButton
          icon={<Play className="size-3.5" />}
          label="Reactivate"
          disabled={disabled}
          onClick={onReactivate}
        />
        <BulkButton
          icon={<BellOff className="size-3.5" />}
          label="Snooze"
          disabled={disabled}
          onClick={onSnooze}
        />
        <BulkButton
          icon={<XCircle className="size-3.5" />}
          label="Cancel"
          variant="destructive"
          disabled={disabled}
          onClick={onCancel}
        />
        <button
          type="button"
          onClick={onClear}
          className="text-muted-foreground hover:text-foreground ml-1 rounded-full p-1"
          aria-label="Clear selection"
          disabled={disabled}
        >
          <X className="size-4" />
        </button>
      </div>
    </div>
  );
}

function BulkButton({
  icon,
  label,
  onClick,
  disabled,
  variant = "ghost",
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled: boolean;
  variant?: "ghost" | "destructive";
}) {
  return (
    <Button
      size="sm"
      variant={variant}
      disabled={disabled}
      onClick={onClick}
      className="gap-1"
      aria-label={label}
      title={label}
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </Button>
  );
}

// ---------------------------------------------------------------------------
// By-category view
// ---------------------------------------------------------------------------

function ByCategoryView({
  rows,
  streamHighlight,
  selected,
  onToggleSelect,
  onAction,
}: {
  rows: RecurringStream[];
  streamHighlight: string | null;
  selected: Set<number>;
  onToggleSelect: (id: number) => void;
  onAction: (
    stream: RecurringStream,
    action: "cancel" | "pause" | "reactivate" | "snooze_price_change",
  ) => void;
}) {
  type Group = {
    key: string;
    name: string;
    color: string | null;
    rows: RecurringStream[];
    monthlyCents: number;
  };
  const groups = useMemo<Group[]>(() => {
    const map = new Map<string, Group>();
    for (const r of rows) {
      const key = String(r.primary_category_id ?? "uncat");
      const name = r.primary_category_name?.trim() || "Uncategorized";
      const color = r.primary_category_color ?? null;
      const g = map.get(key) ?? { key, name, color, rows: [], monthlyCents: 0 };
      g.rows.push(r);
      g.monthlyCents += monthlyCostCents(r);
      map.set(key, g);
    }
    return Array.from(map.values()).sort(
      (a, b) => Math.abs(b.monthlyCents) - Math.abs(a.monthlyCents),
    );
  }, [rows]);

  return (
    <div className="space-y-2">
      {groups.map((g) => (
        <CategoryGroup
          key={g.key}
          group={g}
          streamHighlight={streamHighlight}
          selected={selected}
          onToggleSelect={onToggleSelect}
          onAction={onAction}
        />
      ))}
    </div>
  );
}

function CategoryGroup({
  group,
  streamHighlight,
  selected,
  onToggleSelect,
  onAction,
}: {
  group: {
    key: string;
    name: string;
    color: string | null;
    rows: RecurringStream[];
    monthlyCents: number;
  };
  streamHighlight: string | null;
  selected: Set<number>;
  onToggleSelect: (id: number) => void;
  onAction: (
    stream: RecurringStream,
    action: "cancel" | "pause" | "reactivate" | "snooze_price_change",
  ) => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="overflow-hidden rounded-md border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="bg-muted/30 hover:bg-muted/50 flex w-full items-center gap-2 px-3 py-2 text-left sm:gap-3 sm:px-4"
      >
        {group.color ? (
          <span
            className="size-3 shrink-0 rounded-full"
            style={{ backgroundColor: group.color }}
            aria-hidden
          />
        ) : null}
        <span className="min-w-0 truncate text-sm font-medium">{group.name}</span>
        <span className="text-muted-foreground hidden text-xs sm:inline">
          {group.rows.length} stream{group.rows.length === 1 ? "" : "s"}
        </span>
        <span className="ml-auto inline-flex shrink-0 items-center gap-2">
          <span className="text-sm tabular-nums font-medium">
            {formatMoney(group.monthlyCents)}/mo
          </span>
          {open ? (
            <ChevronUp className="size-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="size-4 text-muted-foreground" />
          )}
        </span>
      </button>
      {open ? (
        <div>
          {group.rows.map((row) => (
            <CategoryGroupRow
              key={row.id}
              row={row}
              isHighlighted={streamHighlight === String(row.id)}
              isSelected={selected.has(row.id)}
              onToggleSelect={() => onToggleSelect(row.id)}
              onAction={(action) => onAction(row, action)}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function CategoryGroupRow({
  row,
  isHighlighted,
  isSelected,
  onToggleSelect,
  onAction,
}: {
  row: RecurringStream;
  isHighlighted: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
  onAction: (
    action: "cancel" | "pause" | "reactivate" | "snooze_price_change",
  ) => void;
}) {
  const title = streamTitle(row);
  const lifecycle = effectiveUserStatus(row);
  const muted = lifecycle === "cancelled";
  const pct = parsePriceChangePct(row.price_change_pct);
  const showPriceAlert =
    pct != null && Math.abs(pct) > PRICE_CHANGE_THRESHOLD_PCT && !isSnoozedNow(row);
  return (
    <div
      id={`recurring-row-${row.id}`}
      className={cn(
        "group flex items-center gap-2 border-b px-3 py-2.5 last:border-b-0 hover:bg-muted/40 sm:gap-3 sm:px-4",
        isSelected && "bg-primary/5",
        isHighlighted && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        muted && "opacity-60",
      )}
    >
      <button
        type="button"
        onClick={onToggleSelect}
        className="hover:text-primary inline-flex size-5 shrink-0 items-center justify-center text-muted-foreground"
      >
        {isSelected ? <CheckSquare2 className="size-4" /> : <Square className="size-4" />}
      </button>
      <StreamAvatar stream={row} size={28} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="min-w-0 max-w-full truncate text-sm font-medium">
            {title}
          </span>
          <UserStatusPill status={lifecycle} />
          {showPriceAlert ? (
            <PriceChangeBadge pct={pct} direction={row.direction} compact />
          ) : null}
        </div>
        <div className="text-muted-foreground text-xs">
          {formatFrequency(row.frequency)} · next{" "}
          {formatNextRecurringDate(row.last_date, row.frequency)}
        </div>
      </div>
      <div className="shrink-0 text-right tabular-nums">
        <div className="text-sm font-semibold">
          {formatMoney(Math.abs(row.last_amount_cents ?? 0))}
        </div>
        <div className="text-muted-foreground text-xs">
          ≈ {formatMoney(monthlyCostCents(row))}/mo
        </div>
      </div>
      <div className="shrink-0 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100">
        <RowActionsMenu
          stream={row}
          onAction={onAction}
          onStartEdit={() => {
            /* category-grouped view doesn't support inline edit */
            notify.info("Use the List view to edit a stream's label or category.");
          }}
          editLockedByOther={false}
        />
      </div>
    </div>
  );
}

