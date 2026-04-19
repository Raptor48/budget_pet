"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout/app-layout";
import {
  CATEGORY_COLORS,
  CategoryDonutChart,
  CategoryLegend,
} from "@/components/charts/category-donut-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MonthYearPicker } from "@/components/ui/month-year-picker";
import { ArrowLeft, PieChart } from "lucide-react";
import { IncomeTab } from "@/components/reports/income-tab";
import { reportsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  CashFlowMonth,
  CategorySpend,
  FinancialHealthScore,
  MerchantSpend,
  NetWorthSnapshot,
} from "@/types/v2";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getCurrentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

function shortMonthLabel(ym: string): string {
  const d = new Date(`${ym}-01T12:00:00`);
  if (Number.isNaN(d.getTime())) return ym;
  return d.toLocaleString("en-US", { month: "short" });
}

function sortCashFlowMonths(rows: CashFlowMonth[]): CashFlowMonth[] {
  return [...rows].sort((a, b) => a.month.localeCompare(b.month));
}

function formatRatioPercent(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}


function NetWorthLineChart({ data }: { data: NetWorthSnapshot[] }) {
  const sorted = useMemo(
    () =>
      [...data].sort((a, b) =>
        String(a.snapshot_date).localeCompare(String(b.snapshot_date)),
      ),
    [data],
  );

  const { points, pathD, minV, maxV } = useMemo(() => {
    if (!sorted.length) {
      return { points: [] as { x: number; y: number; label: string }[], pathD: "", minV: 0, maxV: 0 };
    }
    const values = sorted.map((s) => s.net_worth_cents);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = max === min ? 1 : (max - min) * 0.08;
    const minV = min - pad;
    const maxV = max + pad;
    const w = 100;
    const h = 40;
    const pts = sorted.map((s, i) => {
      const x = sorted.length === 1 ? w / 2 : (i / (sorted.length - 1)) * w;
      const t = maxV === minV ? 0.5 : (s.net_worth_cents - minV) / (maxV - minV);
      const y = h - t * h;
      return {
        x,
        y,
        label: String(s.snapshot_date).slice(0, 7),
      };
    });
    const pathD = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
    return { points: pts, pathD, minV, maxV };
  }, [sorted]);

  if (!sorted.length) {
    return (
      <p className="text-muted-foreground text-sm py-8 text-center">No history yet.</p>
    );
  }

  return (
    <div className="space-y-2">
      <svg
        viewBox="0 0 100 42"
        className="w-full h-40 text-primary"
        preserveAspectRatio="none"
        role="img"
        aria-label="Net worth over time"
      >
        <defs>
          <linearGradient id="nwFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.25" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path
          d={`${pathD} L ${points[points.length - 1]?.x ?? 0} 42 L ${points[0]?.x ?? 0} 42 Z`}
          fill="url(#nwFill)"
          className="text-primary"
        />
        <path
          d={pathD}
          fill="none"
          stroke="currentColor"
          strokeWidth="0.6"
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {points.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="0.9" fill="currentColor" className="text-primary" />
        ))}
      </svg>
      <div className="flex justify-between text-xs text-muted-foreground px-1">
        <span>{points[0]?.label}</span>
        <span>{points[points.length - 1]?.label}</span>
      </div>
      <p className="text-xs text-muted-foreground text-center">
        Range: {formatMoney(minV)} — {formatMoney(maxV)}
      </p>
    </div>
  );
}

function CashFlowBarGroups({ months }: { months: CashFlowMonth[] }) {
  const sorted = sortCashFlowMonths(months);
  const maxVal = useMemo(() => {
    let m = 1;
    for (const row of sorted) {
      m = Math.max(m, row.income_cents, row.expenses_cents);
    }
    return m;
  }, [sorted]);

  if (!sorted.length) {
    return <p className="text-muted-foreground text-sm py-6 text-center">No data for this range.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-stretch justify-between gap-1 sm:gap-2 h-52 pt-4 border-b border-border/60">
        {sorted.map((row) => {
          const hIn = maxVal > 0 ? (row.income_cents / maxVal) * 100 : 0;
          const hEx = maxVal > 0 ? (row.expenses_cents / maxVal) * 100 : 0;
          return (
            <div
              key={row.month}
              className="flex flex-1 flex-col items-center gap-1 min-w-0 h-full"
              title={`${row.month}: in ${formatMoney(row.income_cents)}, out ${formatMoney(row.expenses_cents)}`}
            >
              <div className="flex flex-1 min-h-0 w-full max-w-[2.5rem] items-end justify-center gap-0.5 mx-auto">
                <div
                  className="w-[42%] max-w-3 rounded-t-md bg-emerald-500/90 shadow-sm transition-all"
                  style={{ height: `${Math.max(hIn, 1)}%` }}
                />
                <div
                  className="w-[42%] max-w-3 rounded-t-md bg-rose-500/90 shadow-sm transition-all"
                  style={{ height: `${Math.max(hEx, 1)}%` }}
                />
              </div>
              <span className="text-[10px] sm:text-xs text-muted-foreground truncate w-full text-center shrink-0">
                {shortMonthLabel(row.month)}
              </span>
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center justify-center gap-6 text-sm">
        <span className="inline-flex items-center gap-2">
          <span className="size-2.5 rounded-sm bg-emerald-500" /> Income
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="size-2.5 rounded-sm bg-rose-500" /> Expenses
        </span>
      </div>
    </div>
  );
}

function MerchantLogo({ url, name }: { url: string | null; name: string }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return (
      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-xs font-semibold text-muted-foreground">
        {name.slice(0, 2).toUpperCase()}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt=""
      width={36}
      height={36}
      className="size-9 shrink-0 rounded-lg object-cover bg-muted"
      onError={() => setFailed(true)}
    />
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Reports() {
  const [month, setMonth] = useState(getCurrentMonth);
  const [catHoveredIdx, setCatHoveredIdx] = useState<number | null>(null);
  const [catLockedIdx, setCatLockedIdx] = useState<number | null>(null);
  /**
   * Focus-mode: when the user drills into a primary category, we pin it here
   * and switch the query to rollup=detailed with parent_category_id.
   * null = show primary (rolled-up) view.
   */
  const [focusedParent, setFocusedParent] = useState<CategorySpend | null>(null);
  const catActiveIdx = catHoveredIdx ?? catLockedIdx;

  const resetCategoryHighlight = () => {
    setCatHoveredIdx(null);
    setCatLockedIdx(null);
  };

  const exitFocus = () => {
    setFocusedParent(null);
    resetCategoryHighlight();
  };

  const handleSliceDrilldown = (row: CategorySpend, index: number) => {
    if (focusedParent) {
      setCatLockedIdx((prev) => (prev === index ? null : index));
      return;
    }
    const hasChildren = (row.children_count ?? 0) > 0;
    if (!hasChildren) {
      setCatLockedIdx((prev) => (prev === index ? null : index));
      return;
    }
    setFocusedParent(row);
    resetCategoryHighlight();
  };

  const cashFlowQuery = useQuery({
    queryKey: ["reports", "cash-flow", month],
    queryFn: () => reportsApi.getCashFlow(month),
  });

  const cashFlowHistoryQuery = useQuery({
    queryKey: ["reports", "cash-flow-history", 12],
    queryFn: () => reportsApi.getCashFlowHistory(12),
  });

  const byCategoryQuery = useQuery({
    queryKey: [
      "reports",
      "by-category",
      month,
      focusedParent ? `parent:${focusedParent.category_id}` : "primary",
    ],
    queryFn: () =>
      reportsApi.getByCategory(month, {
        rollup: focusedParent ? "detailed" : "primary",
        parent_category_id: focusedParent?.category_id ?? undefined,
      }),
  });

  const netWorthQuery = useQuery({
    queryKey: ["reports", "net-worth"],
    queryFn: () => reportsApi.getNetWorth(),
  });

  const netWorthHistoryQuery = useQuery({
    queryKey: ["reports", "net-worth-history", 12],
    queryFn: () => reportsApi.getNetWorthHistory(12),
  });

  const merchantsQuery = useQuery({
    queryKey: ["reports", "merchants", month, 10],
    queryFn: () => reportsApi.getTopMerchants(month, 10),
  });

  const healthQuery = useQuery({
    queryKey: ["reports", "financial-health"],
    queryFn: () => reportsApi.getFinancialHealth(),
  });

  const cf = cashFlowQuery.data;
  const net = netWorthQuery.data;
  const health = healthQuery.data;

  return (
    <AppLayout>
      <div className="mx-auto max-w-6xl space-y-8 pb-10">
        <header className="space-y-1">
          <h1 className="text-3xl font-semibold tracking-tight">Reports</h1>
          <p className="text-muted-foreground text-sm max-w-2xl">
            Cash flow, spending breakdown, net worth trend, and financial health — updated from your
            linked accounts.
          </p>
        </header>

        <Tabs defaultValue="cashflow" className="gap-6">
          <TabsList className="grid h-auto w-full max-w-4xl grid-cols-2 gap-1 p-1 sm:grid-cols-3 lg:grid-cols-6">
            <TabsTrigger value="cashflow">Cash Flow</TabsTrigger>
            <TabsTrigger value="income">Income</TabsTrigger>
            <TabsTrigger value="category">By Category</TabsTrigger>
            <TabsTrigger value="networth">Net Worth</TabsTrigger>
            <TabsTrigger value="merchants">Top Merchants</TabsTrigger>
            <TabsTrigger value="health" className="col-span-2 sm:col-span-1">
              Financial Health
            </TabsTrigger>
          </TabsList>

          <TabsContent value="cashflow" className="space-y-6">
            <Card className="border-border/80 shadow-sm">
              <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-4">
                <div>
                  <CardTitle>Cash flow</CardTitle>
                  <CardDescription>Income, expenses, and net for the selected month.</CardDescription>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-muted-foreground">Month</span>
                  <MonthYearPicker value={month} onChange={setMonth} />
                </div>
              </CardHeader>
              <CardContent className="space-y-8">
                {cashFlowQuery.isLoading && (
                  <p className="text-muted-foreground text-sm">Loading cash flow…</p>
                )}
                {cashFlowQuery.isError && (
                  <p className="text-destructive text-sm">
                    {(cashFlowQuery.error as Error)?.message || "Failed to load cash flow."}
                  </p>
                )}
                {cf && (
                  <div className="grid gap-4 sm:grid-cols-3">
                    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-5 py-4">
                      <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
                        Income
                      </p>
                      <p className="text-2xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                        {formatMoney(cf.income_cents)}
                      </p>
                    </div>
                    <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 px-5 py-4">
                      <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
                        Expenses
                      </p>
                      <p className="text-2xl font-semibold tabular-nums text-rose-600 dark:text-rose-400">
                        {formatMoney(cf.expenses_cents)}
                      </p>
                    </div>
                    <div
                      className={`rounded-xl border px-5 py-4 ${
                        cf.net_cents >= 0
                          ? "border-sky-500/25 bg-sky-500/5"
                          : "border-amber-500/25 bg-amber-500/5"
                      }`}
                    >
                      <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
                        Net
                      </p>
                      <p
                        className={`text-2xl font-semibold tabular-nums ${
                          cf.net_cents >= 0
                            ? "text-sky-600 dark:text-sky-400"
                            : "text-amber-700 dark:text-amber-400"
                        }`}
                      >
                        {formatMoney(cf.net_cents)}
                      </p>
                    </div>
                  </div>
                )}

                <div>
                  <h3 className="text-sm font-medium mb-4">12-month history</h3>
                  {cashFlowHistoryQuery.isLoading && (
                    <p className="text-muted-foreground text-sm">Loading history…</p>
                  )}
                  {cashFlowHistoryQuery.isError && (
                    <p className="text-destructive text-sm">Could not load history.</p>
                  )}
                  {cashFlowHistoryQuery.data && (
                    <CashFlowBarGroups months={cashFlowHistoryQuery.data} />
                  )}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="income" className="space-y-6">
            <IncomeTab month={month} onMonthChange={setMonth} />
          </TabsContent>

          <TabsContent value="category" className="space-y-6">
            <Card className="border-border/80 shadow-sm">
              <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-4">
                <div className="min-w-0 space-y-1">
                  <CardTitle className="flex flex-wrap items-center gap-2">
                    {focusedParent ? (
                      <>
                        <span className="text-muted-foreground font-normal">Spending in</span>
                        <span className="truncate">{focusedParent.category_name}</span>
                      </>
                    ) : (
                      <>Spending by category</>
                    )}
                  </CardTitle>
                  <CardDescription>
                    {focusedParent
                      ? `Subcategories under ${focusedParent.category_name} for the selected month.`
                      : "Share of expenses per category for the month. Click a slice to focus on its subcategories."}
                  </CardDescription>
                </div>
                <div className="flex items-end gap-3">
                  {focusedParent ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={exitFocus}
                      className="gap-1"
                    >
                      <ArrowLeft className="size-3.5" aria-hidden />
                      Back to all
                    </Button>
                  ) : null}
                  <div className="flex flex-col gap-1">
                    <span className="text-xs font-medium text-muted-foreground">Month</span>
                    <MonthYearPicker
                      value={month}
                      onChange={(m) => {
                        setMonth(m);
                        resetCategoryHighlight();
                      }}
                    />
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-6">
                {byCategoryQuery.isLoading && (
                  <p className="text-muted-foreground text-sm">Loading categories…</p>
                )}
                {byCategoryQuery.isError && (
                  <p className="text-destructive text-sm">Could not load category breakdown.</p>
                )}
                {byCategoryQuery.data && byCategoryQuery.data.length > 0 && (
                  <>
                    {/* Chart + interactive legend */}
                    <div className="grid gap-4 sm:grid-cols-[280px_1fr]">
                      <CategoryDonutChart
                        data={byCategoryQuery.data}
                        hoveredIdx={catHoveredIdx}
                        lockedIdx={catLockedIdx}
                        onHover={setCatHoveredIdx}
                        onLock={setCatLockedIdx}
                        onSliceClick={focusedParent ? undefined : handleSliceDrilldown}
                      />
                      <CategoryLegend
                        data={byCategoryQuery.data}
                        hoveredIdx={catHoveredIdx}
                        lockedIdx={catLockedIdx}
                        onHover={setCatHoveredIdx}
                        onLock={setCatLockedIdx}
                        onSliceClick={focusedParent ? undefined : handleSliceDrilldown}
                      />
                    </div>
                    {!focusedParent && (
                      <p className="text-xs text-muted-foreground">
                        Tip: click a slice or legend row to focus on subcategories.
                      </p>
                    )}

                    {/* Detailed table */}
                    <div className="overflow-x-auto rounded-lg border border-border/60">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                            <th className="px-4 py-3">Category</th>
                            <th className="px-4 py-3 text-right">Amount</th>
                            <th className="px-4 py-3 w-52">Share</th>
                          </tr>
                        </thead>
                        <tbody>
                          {byCategoryQuery.data.map((row: CategorySpend, i: number) => {
                            const isActive = catActiveIdx === i;
                            const hasChildren = (row.children_count ?? 0) > 0;
                            const canDrill = !focusedParent && hasChildren;
                            return (
                              <tr
                                key={row.category_name}
                                className={cn(
                                  "border-b border-border/50 last:border-0 cursor-pointer transition-colors",
                                  isActive ? "bg-muted/50" : "hover:bg-muted/20",
                                )}
                                onMouseEnter={() => setCatHoveredIdx(i)}
                                onMouseLeave={() => setCatHoveredIdx(null)}
                                onClick={() => {
                                  if (canDrill) {
                                    handleSliceDrilldown(row, i);
                                  } else {
                                    setCatLockedIdx((prev) => (prev === i ? null : i));
                                  }
                                }}
                              >
                                <td className="px-4 py-3">
                                  <span className="inline-flex items-center gap-2 font-medium">
                                    <span
                                      className="size-2.5 shrink-0 rounded-full"
                                      style={{ backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}
                                    />
                                    <span className="truncate">{row.category_name}</span>
                                    {canDrill ? (
                                      <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                                        {row.children_count}×
                                      </span>
                                    ) : null}
                                  </span>
                                </td>
                                <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                                  {formatMoney(row.amount_cents)}
                                </td>
                                <td className="px-4 py-3">
                                  <div className="flex items-center gap-2">
                                    <div className="h-2 flex-1 max-w-[140px] overflow-hidden rounded-full bg-muted">
                                      <div
                                        className="h-full rounded-full transition-all"
                                        style={{
                                          width: `${Math.min(100, Math.max(0, row.percent))}%`,
                                          backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
                                          opacity: isActive ? 1 : 0.7,
                                        }}
                                      />
                                    </div>
                                    <span className="w-12 tabular-nums text-muted-foreground text-right text-xs">
                                      {row.percent.toFixed(1)}%
                                    </span>
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
                {byCategoryQuery.data?.length === 0 && (
                  <div className="flex flex-col items-center gap-2 py-12 text-center">
                    <div className="flex size-12 items-center justify-center rounded-full bg-muted">
                      <PieChart className="size-6 text-muted-foreground" />
                    </div>
                    <p className="font-medium">
                      {focusedParent
                        ? `No subcategory spending in ${focusedParent.category_name}`
                        : "No spending in this month"}
                    </p>
                    <p className="text-muted-foreground max-w-xs text-sm">
                      {focusedParent
                        ? "This primary bucket has no subcategory detail for the selected month."
                        : "Pick a different month or add a cash transaction to see your spending breakdown."}
                    </p>
                    {focusedParent ? (
                      <Button variant="outline" size="sm" onClick={exitFocus} className="mt-2 gap-1">
                        <ArrowLeft className="size-3.5" aria-hidden />
                        Back to all categories
                      </Button>
                    ) : null}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="networth" className="space-y-6">
            <Card className="border-border/80 shadow-sm">
              <CardHeader>
                <CardTitle>Net worth</CardTitle>
                <CardDescription>Liquid, investments, debt, and total net worth — last 12 snapshots.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-8">
                {netWorthQuery.isLoading && (
                  <p className="text-muted-foreground text-sm">Loading balances…</p>
                )}
                {netWorthQuery.isError && (
                  <p className="text-destructive text-sm">Could not load net worth.</p>
                )}
                {net && (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <MetricTile label="Cash & Savings" value={formatMoney(net.liquid_cents)} accent="neutral" />
                    <MetricTile label="Portfolio" value={formatMoney(net.investment_cents)} accent="blue" />
                    <MetricTile label="Loans & Debt" value={formatMoney(net.debt_cents)} accent="rose" />
                    <MetricTile label="Net Worth" value={formatMoney(net.net_worth_cents)} accent="primary" />
                  </div>
                )}

                <div>
                  <h3 className="text-sm font-medium mb-2">12-month trend</h3>
                  {netWorthHistoryQuery.isLoading && (
                    <p className="text-muted-foreground text-sm">Loading history…</p>
                  )}
                  {netWorthHistoryQuery.isError && (
                    <p className="text-destructive text-sm">Could not load net worth history.</p>
                  )}
                  {netWorthHistoryQuery.data && (
                    <NetWorthLineChart data={netWorthHistoryQuery.data} />
                  )}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="merchants" className="space-y-6">
            <Card className="border-border/80 shadow-sm">
              <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-4">
                <div>
                  <CardTitle>Top merchants</CardTitle>
                  <CardDescription>Where you spent the most this month.</CardDescription>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-muted-foreground">Month</span>
                  <MonthYearPicker value={month} onChange={setMonth} />
                </div>
              </CardHeader>
              <CardContent>
                {merchantsQuery.isLoading && (
                  <p className="text-muted-foreground text-sm">Loading merchants…</p>
                )}
                {merchantsQuery.isError && (
                  <p className="text-destructive text-sm">Could not load merchants.</p>
                )}
                {merchantsQuery.data && (
                  <div className="overflow-x-auto rounded-lg border border-border/60">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-muted/40 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          <th className="px-4 py-3 w-14"> </th>
                          <th className="px-4 py-3">Merchant</th>
                          <th className="px-4 py-3 text-right">Amount</th>
                          <th className="px-4 py-3 text-right">Txns</th>
                        </tr>
                      </thead>
                      <tbody>
                        {merchantsQuery.data.map((m: MerchantSpend) => (
                          <tr key={m.merchant_name} className="border-b border-border/50 last:border-0">
                            <td className="px-4 py-2">
                              <MerchantLogo url={m.logo_url} name={m.merchant_name} />
                            </td>
                            <td className="px-4 py-2 font-medium">{m.merchant_name}</td>
                            <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                              {formatMoney(m.amount_cents)}
                            </td>
                            <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                              {m.transaction_count}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {merchantsQuery.data?.length === 0 && (
                  <p className="text-muted-foreground text-sm text-center py-8">No merchant data this month.</p>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="health" className="space-y-6">
            <Card className="border-border/80 shadow-sm overflow-hidden">
              <CardHeader>
                <CardTitle>Financial health</CardTitle>
                <CardDescription>Holistic score from debt, utilization, savings, and safety buffer.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-8">
                {healthQuery.isLoading && (
                  <p className="text-muted-foreground text-sm">Loading health score…</p>
                )}
                {healthQuery.isError && (
                  <p className="text-destructive text-sm">Could not load financial health.</p>
                )}
                {health && <FinancialHealthPanel score={health} />}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </AppLayout>
  );
}

function MetricTile({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: "neutral" | "blue" | "rose" | "primary";
}) {
  const ring =
    accent === "blue"
      ? "border-sky-500/20 bg-sky-500/5"
      : accent === "rose"
        ? "border-rose-500/20 bg-rose-500/5"
        : accent === "primary"
          ? "border-primary/25 bg-primary/5"
          : "border-border/80 bg-card";
  return (
    <div className={`rounded-xl border px-4 py-3 ${ring}`}>
      <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">{label}</p>
      <p className="text-lg font-semibold tabular-nums tracking-tight">{value}</p>
    </div>
  );
}

function FinancialHealthPanel({ score }: { score: FinancialHealthScore }) {
  const ringPct = Math.min(100, Math.max(0, score.score));
  return (
    <div className="space-y-8">
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-center sm:gap-10">
        <div className="relative size-36">
          <svg viewBox="0 0 100 100" className="size-full -rotate-90" aria-hidden>
            <circle cx="50" cy="50" r="42" fill="none" className="stroke-muted" strokeWidth="10" />
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke={score.color}
              strokeWidth="10"
              strokeLinecap="round"
              strokeDasharray={`${(ringPct / 100) * 264} 264`}
              className="transition-all duration-500"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-3xl font-bold tabular-nums">{score.score}</span>
            <span className="text-xs text-muted-foreground">/ 100</span>
          </div>
        </div>
        <div className="text-center sm:text-left space-y-1">
          <p className="text-lg font-semibold" style={{ color: score.color }}>
            {score.label}
          </p>
          <p className="text-muted-foreground text-sm max-w-md leading-relaxed">{score.advice}</p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <HealthMetric label="Debt-to-income" value={formatRatioPercent(score.debt_to_income)} />
        <HealthMetric label="Credit utilization" value={formatRatioPercent(score.credit_utilization)} />
        <HealthMetric label="Savings rate" value={formatRatioPercent(score.savings_rate)} />
        <HealthMetric
          label="Emergency fund"
          value={
            score.emergency_fund_months != null
              ? `${score.emergency_fund_months.toFixed(1)} mo`
              : "—"
          }
        />
        <HealthMetric
          label="Overdue accounts"
          value={score.has_overdue ? "Yes — action needed" : "None"}
          highlight={score.has_overdue}
        />
      </div>
    </div>
  );
}

function HealthMetric({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border px-4 py-3 ${highlight ? "border-destructive/40 bg-destructive/5" : "border-border/60 bg-muted/20"}`}
    >
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className={`mt-1 font-semibold tabular-nums ${highlight ? "text-destructive" : ""}`}>{value}</p>
    </div>
  );
}
