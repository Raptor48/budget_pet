"use client";

import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Check, ChevronDown, Plus, Sparkles, X } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { AnimatedMoney } from "@/components/ui/animated-money";
import { CATEGORY_COLORS } from "@/components/charts/category-donut-chart";
import { cn } from "@/lib/utils";
import { reportsApi } from "@/lib/api";
import type { CategorySpend } from "@/types/v2";
import { TrendsLoadingOverlay } from "./trends-loading-overlay";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

function shortMonth(ym: string): string {
  const d = new Date(`${ym}-01T12:00:00`);
  if (Number.isNaN(d.getTime())) return ym;
  return d.toLocaleString("en-US", { month: "short" });
}

function longMonth(ym: string): string {
  const d = new Date(`${ym}-01T12:00:00`);
  if (Number.isNaN(d.getTime())) return ym;
  return d.toLocaleString("en-US", { month: "short", year: "2-digit" });
}

/**
 * Produce a list of the last N months in YYYY-MM form, oldest first and
 * ending with the current month. Deterministic so TanStack Query keys
 * stay stable across renders within the same day.
 */
export function buildMonthList(n: number, reference = new Date()): string[] {
  const out: string[] = [];
  const year = reference.getFullYear();
  const month = reference.getMonth(); // 0-based
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(year, month - i, 1);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    out.push(`${y}-${m}`);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Period pill picker
// ---------------------------------------------------------------------------

function PeriodPicker({
  value,
  onChange,
}: {
  value: 6 | 12;
  onChange: (v: 6 | 12) => void;
}) {
  return (
    <div
      className="inline-flex items-center rounded-full border border-border/70 bg-muted/40 p-0.5 shadow-sm"
      role="tablist"
      aria-label="Time range"
    >
      {[6, 12].map((n) => {
        const active = value === n;
        return (
          <button
            key={n}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(n as 6 | 12)}
            className={cn(
              "relative rounded-full px-4 py-1.5 text-xs font-semibold transition-all",
              active
                ? "bg-card text-foreground shadow"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {n} months
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chart tooltip (shared style)
// ---------------------------------------------------------------------------

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; color?: string; dataKey?: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-border/70 bg-popover/95 px-3 py-2 shadow-xl backdrop-blur-md">
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="space-y-0.5 text-xs">
        {payload.map((entry) => (
          <div
            key={String(entry.dataKey ?? entry.name)}
            className="flex items-center justify-between gap-3"
          >
            <span className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span
                className="size-2 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              {entry.name}
            </span>
            <span className="font-semibold tabular-nums text-foreground">
              {formatMoney(Number(entry.value ?? 0))}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Multi-select for categories
// ---------------------------------------------------------------------------

function CategoryMultiSelect({
  allCategories,
  selectedIds,
  onChange,
  colors,
}: {
  allCategories: { id: number; name: string; total: number }[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  colors: Map<number, string>;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return allCategories;
    return allCategories.filter((c) => c.name.toLowerCase().includes(needle));
  }, [allCategories, search]);

  function toggle(id: number) {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((x) => x !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Plus className="size-3.5" />
          Add / remove categories
          <ChevronDown className="size-3.5 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="end">
        <div className="border-b border-border/60 p-2">
          <Input
            autoFocus
            placeholder="Search categories…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 text-sm"
          />
        </div>
        <div className="max-h-72 overflow-auto py-1">
          {filtered.length === 0 && (
            <p className="px-3 py-4 text-center text-xs text-muted-foreground">
              No categories match.
            </p>
          )}
          {filtered.map((c) => {
            const selected = selectedIds.includes(c.id);
            const color = colors.get(c.id) ?? CATEGORY_COLORS[0];
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => toggle(c.id)}
                className={cn(
                  "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-sm transition-colors hover:bg-muted/50",
                  selected && "bg-muted/40",
                )}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className="size-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                  <span className="truncate">{c.name}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="text-[10px] tabular-nums text-muted-foreground">
                    {formatMoney(c.total)}
                  </span>
                  {selected ? (
                    <Check className="size-3.5 text-primary" />
                  ) : (
                    <span className="size-3.5" />
                  )}
                </span>
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// ---------------------------------------------------------------------------
// Trends tab
// ---------------------------------------------------------------------------

const MIN_OVERLAY_MS = 400;

/**
 * Multi-month spending report.
 *
 * Data strategy: one `/api/reports/by-category` request per month run in
 * parallel through `useQueries`. Query keys line up with the ones used on
 * the single-month By Category tab, so cached data is reused across tabs
 * and re-visits.
 */
export function TrendsTab() {
  const [months, setMonths] = useState<6 | 12>(12);
  const monthList = useMemo(() => buildMonthList(months), [months]);

  const cashFlowHistoryQuery = useQuery({
    queryKey: ["reports", "cash-flow-history", 12],
    queryFn: () => reportsApi.getCashFlowHistory(12),
    staleTime: 5 * 60_000,
  });

  const categoryQueries = useQueries({
    queries: monthList.map((ym) => ({
      queryKey: ["reports", "by-category", ym, "primary"],
      queryFn: () =>
        reportsApi.getByCategory(ym, { rollup: "primary" }),
      staleTime: 5 * 60_000,
    })),
  });

  const loadedCount = categoryQueries.filter((q) => !q.isLoading).length;
  const anyLoading = categoryQueries.some((q) => q.isLoading);
  const someErrored = categoryQueries.some((q) => q.isError);

  // ---- Prepare aggregated data -------------------------------------------------

  const monthlyCashFlow = useMemo(() => {
    const rows = cashFlowHistoryQuery.data ?? [];
    // Limit to the selected window (the source query always returns 12 months).
    const set = new Set(monthList);
    const kept = rows.filter((r) => set.has(r.month));
    kept.sort((a, b) => a.month.localeCompare(b.month));
    return kept.map((r) => ({
      month: r.month,
      label: longMonth(r.month),
      income: r.income_cents,
      expenses: r.expenses_cents,
      net: r.net_cents,
    }));
  }, [cashFlowHistoryQuery.data, monthList]);

  const totals = useMemo(() => {
    let income = 0;
    let expenses = 0;
    for (const r of monthlyCashFlow) {
      income += r.income;
      expenses += r.expenses;
    }
    return { income, expenses, net: income - expenses };
  }, [monthlyCashFlow]);

  // month × category spend. Missing data is 0.
  const categoryMatrix = useMemo(() => {
    const seen = new Map<number, { name: string; total: number }>();
    // monthIdx -> categoryId -> amount
    const perMonth: Map<string, Map<number, number>> = new Map();

    monthList.forEach((ym, idx) => {
      const q = categoryQueries[idx];
      const rows: CategorySpend[] = (q?.data as CategorySpend[] | undefined) ?? [];
      const bucket = new Map<number, number>();
      perMonth.set(ym, bucket);
      for (const row of rows) {
        if (row.category_id == null) continue;
        bucket.set(row.category_id, row.amount_cents);
        const existing = seen.get(row.category_id);
        if (existing) {
          existing.total += row.amount_cents;
        } else {
          seen.set(row.category_id, {
            name: row.category_name,
            total: row.amount_cents,
          });
        }
      }
    });

    const allCategories = Array.from(seen.entries())
      .map(([id, { name, total }]) => ({ id, name, total }))
      .sort((a, b) => b.total - a.total);

    return { allCategories, perMonth };
  }, [categoryQueries, monthList]);

  // Stable color map by rank (top-spending → CATEGORY_COLORS[0], etc.)
  const colorByCategory = useMemo(() => {
    const map = new Map<number, string>();
    categoryMatrix.allCategories.forEach((c, i) => {
      map.set(c.id, CATEGORY_COLORS[i % CATEGORY_COLORS.length]);
    });
    return map;
  }, [categoryMatrix.allCategories]);

  // Default selection: top 5.
  const [selectedCategoryIds, setSelectedCategoryIds] = useState<number[] | null>(
    null,
  );
  const effectiveSelection = useMemo(() => {
    if (selectedCategoryIds !== null) return selectedCategoryIds;
    return categoryMatrix.allCategories.slice(0, 5).map((c) => c.id);
  }, [selectedCategoryIds, categoryMatrix.allCategories]);

  const categoryChartData = useMemo(() => {
    return monthList.map((ym) => {
      const row: Record<string, number | string> = {
        month: ym,
        label: longMonth(ym),
      };
      const perCat = categoryMatrix.perMonth.get(ym) ?? new Map<number, number>();
      for (const cid of effectiveSelection) {
        const amount = perCat.get(cid) ?? 0;
        const meta = categoryMatrix.allCategories.find((c) => c.id === cid);
        if (!meta) continue;
        row[meta.name] = amount;
      }
      return row;
    });
  }, [monthList, categoryMatrix, effectiveSelection]);

  // ---- Minimum overlay duration to avoid flicker ------------------------------

  const [overlayGate, setOverlayGate] = useState(true);
  useEffect(() => {
    const t = window.setTimeout(() => setOverlayGate(false), MIN_OVERLAY_MS);
    return () => window.clearTimeout(t);
  }, []);
  const showOverlay = anyLoading || overlayGate;

  // ---- Render ------------------------------------------------------------------

  return (
    <div className="space-y-6">
      <Card className="border-border/80 shadow-sm">
        <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-4">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="size-4 text-primary" />
              Trends
            </CardTitle>
            <CardDescription>
              Income, expenses, and category breakdown over the selected period.
            </CardDescription>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              Range
            </span>
            <PeriodPicker value={months} onChange={setMonths} />
          </div>
        </CardHeader>
        <CardContent className="space-y-8">
          {someErrored && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
              Some months failed to load — partial data shown.
            </div>
          )}

          {showOverlay ? (
            <TrendsLoadingOverlay loaded={loadedCount} total={monthList.length} />
          ) : (
            <>
              {/* ---- Cashflow trend ---- */}
              <section className="space-y-3">
                <div className="flex items-baseline justify-between">
                  <h3 className="text-sm font-semibold">Cash flow</h3>
                  <span className="text-[11px] text-muted-foreground">
                    Last {monthList.length} months
                  </span>
                </div>

                <div className="h-64 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={monthlyCashFlow}
                      margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
                    >
                      <defs>
                        <linearGradient id="trends-income" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#10b981" stopOpacity={0.6} />
                          <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="trends-expenses" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.55} />
                          <stop offset="100%" stopColor="#f43f5e" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid
                        vertical={false}
                        stroke="currentColor"
                        strokeOpacity={0.08}
                      />
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 11, fill: "currentColor", opacity: 0.6 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tickFormatter={(v: number) =>
                          Math.abs(v) >= 1_000_00
                            ? `${Math.round(v / 100_000)}k`
                            : `${Math.round(v / 100)}`
                        }
                        tick={{ fontSize: 11, fill: "currentColor", opacity: 0.6 }}
                        tickLine={false}
                        axisLine={false}
                        width={50}
                      />
                      <Tooltip content={<ChartTooltip />} cursor={{ opacity: 0.15 }} />
                      <Legend
                        verticalAlign="top"
                        height={28}
                        wrapperStyle={{ fontSize: 12 }}
                      />
                      <Area
                        type="monotone"
                        name="Income"
                        dataKey="income"
                        stroke="#10b981"
                        strokeWidth={2}
                        fill="url(#trends-income)"
                        animationDuration={600}
                      />
                      <Area
                        type="monotone"
                        name="Expenses"
                        dataKey="expenses"
                        stroke="#f43f5e"
                        strokeWidth={2}
                        fill="url(#trends-expenses)"
                        animationDuration={600}
                      />
                      <Line
                        type="monotone"
                        name="Net"
                        dataKey="net"
                        stroke="#6366f1"
                        strokeWidth={2}
                        strokeDasharray="4 4"
                        dot={false}
                        animationDuration={600}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>

                {/* Totals tiles */}
                <div className="grid gap-3 sm:grid-cols-3">
                  <TotalTile
                    label="Total income"
                    value={totals.income}
                    tone="emerald"
                  />
                  <TotalTile
                    label="Total expenses"
                    value={totals.expenses}
                    tone="rose"
                  />
                  <TotalTile
                    label={totals.net >= 0 ? "Net surplus" : "Net deficit"}
                    value={totals.net}
                    tone={totals.net >= 0 ? "sky" : "amber"}
                  />
                </div>
              </section>

              {/* ---- Categories over time ---- */}
              <section className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold">Categories over time</h3>
                    <p className="text-[11px] text-muted-foreground">
                      Select one or more categories to compare monthly spend.
                    </p>
                  </div>
                  <CategoryMultiSelect
                    allCategories={categoryMatrix.allCategories}
                    selectedIds={effectiveSelection}
                    onChange={setSelectedCategoryIds}
                    colors={colorByCategory}
                  />
                </div>

                {/* Selected chips */}
                {effectiveSelection.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {effectiveSelection.map((cid) => {
                      const meta = categoryMatrix.allCategories.find(
                        (c) => c.id === cid,
                      );
                      if (!meta) return null;
                      const color = colorByCategory.get(cid) ?? CATEGORY_COLORS[0];
                      return (
                        <button
                          key={cid}
                          type="button"
                          onClick={() =>
                            setSelectedCategoryIds(
                              effectiveSelection.filter((x) => x !== cid),
                            )
                          }
                          className="group inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-muted/40 px-2.5 py-0.5 text-[11px] font-medium transition-colors hover:border-destructive/40 hover:bg-destructive/10"
                        >
                          <span
                            className="size-2 rounded-full"
                            style={{ backgroundColor: color }}
                          />
                          <span>{meta.name}</span>
                          <X className="size-3 opacity-60 transition-opacity group-hover:opacity-100" />
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="rounded-lg border border-dashed border-border/60 bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
                    Pick at least one category to see the trend.
                  </p>
                )}

                {effectiveSelection.length > 0 && (
                  <div className="h-72 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={categoryChartData}
                        margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
                      >
                        <CartesianGrid
                          vertical={false}
                          stroke="currentColor"
                          strokeOpacity={0.08}
                        />
                        <XAxis
                          dataKey="label"
                          tick={{
                            fontSize: 11,
                            fill: "currentColor",
                            opacity: 0.6,
                          }}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          tickFormatter={(v: number) =>
                            Math.abs(v) >= 1_000_00
                              ? `${Math.round(v / 100_000)}k`
                              : `${Math.round(v / 100)}`
                          }
                          tick={{
                            fontSize: 11,
                            fill: "currentColor",
                            opacity: 0.6,
                          }}
                          tickLine={false}
                          axisLine={false}
                          width={50}
                        />
                        <Tooltip
                          content={<ChartTooltip />}
                          cursor={{ opacity: 0.15 }}
                        />
                        <Legend
                          verticalAlign="top"
                          height={28}
                          wrapperStyle={{ fontSize: 12 }}
                        />
                        {effectiveSelection.map((cid) => {
                          const meta = categoryMatrix.allCategories.find(
                            (c) => c.id === cid,
                          );
                          if (!meta) return null;
                          return (
                            <Line
                              key={cid}
                              type="monotone"
                              dataKey={meta.name}
                              name={meta.name}
                              stroke={
                                colorByCategory.get(cid) ?? CATEGORY_COLORS[0]
                              }
                              strokeWidth={2}
                              dot={{ r: 2 }}
                              activeDot={{ r: 4 }}
                              animationDuration={700}
                            />
                          );
                        })}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {effectiveSelection.length > 0 && (
                  <CategoryTrendTable
                    monthList={monthList}
                    perMonth={categoryMatrix.perMonth}
                    selected={effectiveSelection
                      .map((cid) =>
                        categoryMatrix.allCategories.find((c) => c.id === cid),
                      )
                      .filter((x): x is NonNullable<typeof x> => x != null)}
                    colorByCategory={colorByCategory}
                  />
                )}

                {categoryMatrix.allCategories.length === 0 && (
                  <p className="rounded-lg border border-dashed border-border/60 bg-muted/20 px-3 py-8 text-center text-xs text-muted-foreground">
                    No expense categories with activity in this range.
                  </p>
                )}
              </section>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TotalTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "emerald" | "rose" | "sky" | "amber";
}) {
  const ring = {
    emerald: "border-emerald-500/25 bg-emerald-500/5",
    rose: "border-rose-500/25 bg-rose-500/5",
    sky: "border-sky-500/25 bg-sky-500/5",
    amber: "border-amber-500/30 bg-amber-500/5",
  }[tone];
  const text = {
    emerald: "text-emerald-600 dark:text-emerald-400",
    rose: "text-rose-600 dark:text-rose-400",
    sky: "text-sky-600 dark:text-sky-400",
    amber: "text-amber-700 dark:text-amber-400",
  }[tone];
  return (
    <div className={cn("rounded-xl border px-4 py-3", ring)}>
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <AnimatedMoney
        cents={value}
        as="p"
        className={cn("mt-0.5 text-xl font-semibold", text)}
      />
    </div>
  );
}

function CategoryTrendTable({
  monthList,
  perMonth,
  selected,
  colorByCategory,
}: {
  monthList: string[];
  perMonth: Map<string, Map<number, number>>;
  selected: { id: number; name: string; total: number }[];
  colorByCategory: Map<number, string>;
}) {
  const months = monthList.length;
  return (
    <div className="overflow-x-auto rounded-lg border border-border/60">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b bg-muted/40 text-left text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            <th className="px-3 py-2">Category</th>
            {monthList.map((ym) => (
              <th
                key={ym}
                className="px-2 py-2 text-right font-medium tabular-nums"
              >
                {shortMonth(ym)}
              </th>
            ))}
            <th className="px-3 py-2 text-right">Total</th>
            <th className="px-3 py-2 text-right">Avg/mo</th>
          </tr>
        </thead>
        <tbody>
          {selected.map((c, i) => {
            let total = 0;
            const cells = monthList.map((ym) => {
              const v = perMonth.get(ym)?.get(c.id) ?? 0;
              total += v;
              return v;
            });
            const avg = months > 0 ? total / months : 0;
            const color = colorByCategory.get(c.id) ?? CATEGORY_COLORS[0];
            return (
              <tr
                key={c.id}
                className="border-b border-border/50 last:border-0 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300"
                style={{
                  animationDelay: `${Math.min(i, 8) * 40}ms`,
                }}
              >
                <td className="px-3 py-2">
                  <span className="inline-flex items-center gap-2">
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ backgroundColor: color }}
                    />
                    <span className="truncate">{c.name}</span>
                  </span>
                </td>
                {cells.map((v, j) => (
                  <td
                    key={`${c.id}-${j}`}
                    className="px-2 py-2 text-right tabular-nums text-muted-foreground"
                  >
                    {v > 0 ? formatMoney(v) : "—"}
                  </td>
                ))}
                <td className="px-3 py-2 text-right font-semibold tabular-nums">
                  {formatMoney(total)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                  {formatMoney(avg)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
