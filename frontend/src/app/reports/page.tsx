"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
import { ArrowLeft, ChevronRight, Loader2, PieChart } from "lucide-react";
import { IncomeTab } from "@/components/reports/income-tab";
import { ExpensesTab } from "@/components/reports/expenses-tab";
import { CashFlowHistoryChart } from "@/components/reports/cash-flow-history-chart";
import { TrendsTab } from "@/components/reports/trends-tab";
import { AnimatedMoney } from "@/components/ui/animated-money";
import { reportsApi, transactionsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  CategorySpend,
  FinancialHealthScore,
  MerchantSpend,
  NetWorthSnapshot,
  Transaction,
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

const REPORT_TABS = [
  "cashflow",
  "trends",
  "income",
  "expenses",
  "category",
  "networth",
  "merchants",
  "health",
] as const;
type ReportTab = (typeof REPORT_TABS)[number];

function isReportTab(value: string | null): value is ReportTab {
  return value != null && (REPORT_TABS as readonly string[]).includes(value);
}

export default function Reports() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialTab: ReportTab = isReportTab(searchParams.get("tab"))
    ? (searchParams.get("tab") as ReportTab)
    : "cashflow";

  const [tab, setTab] = useState<ReportTab>(initialTab);
  const [month, setMonth] = useState(getCurrentMonth);
  const [catHoveredIdx, setCatHoveredIdx] = useState<number | null>(null);
  const [catLockedIdx, setCatLockedIdx] = useState<number | null>(null);

  // Keep `?tab=...` in the URL so deep-links work and the Cash Flow summary
  // cards can navigate cross-tab via plain `next/link` or router.replace.
  useEffect(() => {
    const current = searchParams.get("tab");
    if (current === tab) return;
    const params = new URLSearchParams(searchParams.toString());
    if (tab === "cashflow") {
      params.delete("tab");
    } else {
      params.set("tab", tab);
    }
    const qs = params.toString();
    router.replace(qs ? `?${qs}` : "?", { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  // Respond to back/forward that changes `?tab=` out from under us.
  useEffect(() => {
    const fromUrl = searchParams.get("tab");
    const next: ReportTab = isReportTab(fromUrl) ? fromUrl : "cashflow";
    if (next !== tab) setTab(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const handleTabChange = useCallback((value: string) => {
    if (!isReportTab(value)) return;
    // Use the View Transitions API for a smooth cross-fade between tab
    // panels when the browser supports it. Falls back to a plain
    // synchronous state update everywhere else.
    const doc = typeof document !== "undefined" ? document : null;
    const startVT = (doc as unknown as { startViewTransition?: (cb: () => void) => void } | null)?.startViewTransition;
    if (typeof startVT === "function") {
      startVT.call(doc, () => setTab(value));
    } else {
      setTab(value);
    }
  }, []);
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

  // Deep-link support: `/reports?tab=category&category=<id>` opens the
  // By Category tab already focused on a specific primary bucket. This
  // powers CTAs from Insights ("Open Category" on e.g. top_category or
  // category_trend), so landing on the tab shows the same drill-down
  // the user would have reached by clicking the pie slice manually.
  //
  // Runs only when:
  //   - we're on the category tab,
  //   - a numeric `category` id is in the URL,
  //   - nothing is focused yet,
  //   - and the primary-rollup query has resolved (we need the row to
  //     populate `focusedParent` with its full CategorySpend shape,
  //     matching what handleSliceDrilldown would have produced).
  //
  // If the id isn't found in the primary rollup (e.g. it's a detailed
  // PFC child), we don't try to recover — the user still lands on the
  // tab and can pick manually. Better than an incorrect focus.
  const paramCategoryId = searchParams.get("category");
  useEffect(() => {
    if (tab !== "category") return;
    if (focusedParent) return;
    if (!paramCategoryId) return;
    const numeric = Number(paramCategoryId);
    if (!Number.isFinite(numeric)) return;
    if (byCategoryQuery.isLoading) return;
    const row = byCategoryQuery.data?.find((r) => r.category_id === numeric);
    if (!row) return;
    // Only focus parents that actually have children — otherwise the
    // "detailed" rollup query would return an empty bucket and the
    // header would say "No subcategory spending in X", which is worse
    // UX than showing the transaction list on the primary row instead.
    const hasChildren = (row.children_count ?? 0) > 0;
    if (!hasChildren) return;
    setFocusedParent(row);
    resetCategoryHighlight();
    // We intentionally don't strip `category` from the URL — keeping it
    // means the state survives a refresh / back navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    tab,
    paramCategoryId,
    focusedParent,
    byCategoryQuery.isLoading,
    byCategoryQuery.data,
  ]);

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

        <Tabs value={tab} onValueChange={handleTabChange} className="gap-6">
          <TabsList className="grid h-auto w-full max-w-5xl grid-cols-2 gap-1 p-1 sm:grid-cols-4 lg:grid-cols-8">
            <TabsTrigger value="cashflow">Cash Flow</TabsTrigger>
            <TabsTrigger value="trends">Trends</TabsTrigger>
            <TabsTrigger value="income">Income</TabsTrigger>
            <TabsTrigger value="expenses">Expenses</TabsTrigger>
            <TabsTrigger value="category">By Category</TabsTrigger>
            <TabsTrigger value="networth">Net Worth</TabsTrigger>
            <TabsTrigger value="merchants">Top Merchants</TabsTrigger>
            <TabsTrigger value="health" className="col-span-2 sm:col-span-1">
              Financial Health
            </TabsTrigger>
          </TabsList>

          <TabsContent value="cashflow" className="reports-tab-content space-y-6">
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
                    <button
                      type="button"
                      onClick={() => setTab("income")}
                      className="group rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-5 py-4 text-left transition-colors hover:border-emerald-500/40 hover:bg-emerald-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60"
                      aria-label="Open Income tab"
                    >
                      <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
                        Income
                      </p>
                      <AnimatedMoney
                        cents={cf.income_cents}
                        as="p"
                        className="text-2xl font-semibold text-emerald-600 dark:text-emerald-400"
                      />
                      <p className="mt-1 text-[11px] text-muted-foreground group-hover:text-emerald-700/80">
                        View breakdown →
                      </p>
                    </button>
                    <button
                      type="button"
                      onClick={() => setTab("expenses")}
                      className="group rounded-xl border border-rose-500/20 bg-rose-500/5 px-5 py-4 text-left transition-colors hover:border-rose-500/40 hover:bg-rose-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/60"
                      aria-label="Open Expenses tab"
                    >
                      <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
                        Expenses
                      </p>
                      <AnimatedMoney
                        cents={cf.expenses_cents}
                        as="p"
                        className="text-2xl font-semibold text-rose-600 dark:text-rose-400"
                      />
                      <p className="mt-1 text-[11px] text-muted-foreground group-hover:text-rose-700/80">
                        View breakdown →
                      </p>
                    </button>
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
                      <AnimatedMoney
                        cents={cf.net_cents}
                        as="p"
                        className={`text-2xl font-semibold ${
                          cf.net_cents >= 0
                            ? "text-sky-600 dark:text-sky-400"
                            : "text-amber-700 dark:text-amber-400"
                        }`}
                      />
                      {cf.internal_transfer_cents > 0 && (
                        <p
                          className="mt-1 text-[11px] text-muted-foreground"
                          title="Intra-family transfers (credit card payments, Zelle between spouses, savings sweeps). Excluded from income and expenses."
                        >
                          + {formatMoney(cf.internal_transfer_cents)} in
                          internal transfers
                        </p>
                      )}
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
                    <CashFlowHistoryChart
                      months={cashFlowHistoryQuery.data}
                      activeMonth={month}
                      onSelectMonth={setMonth}
                    />
                  )}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="trends" className="reports-tab-content space-y-6">
            <TrendsTab />
          </TabsContent>

          <TabsContent value="income" className="reports-tab-content space-y-6">
            <IncomeTab month={month} onMonthChange={setMonth} />
          </TabsContent>

          <TabsContent value="expenses" className="reports-tab-content space-y-6">
            <ExpensesTab month={month} onMonthChange={setMonth} />
          </TabsContent>

          <TabsContent value="category" className="reports-tab-content space-y-6">
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
                              <CategorySpendRow
                                key={`${row.category_id ?? "none"}-${row.category_name}`}
                                row={row}
                                index={i}
                                month={month}
                                colorIndex={i}
                                isActive={isActive}
                                canDrillToSubcategories={canDrill}
                                onHover={() => setCatHoveredIdx(i)}
                                onLeave={() => setCatHoveredIdx(null)}
                                onDrillToSubcategories={() => handleSliceDrilldown(row, i)}
                                onLock={() =>
                                  setCatLockedIdx((prev) => (prev === i ? null : i))
                                }
                                mode={focusedParent ? "detailed" : "primary"}
                              />
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

          <TabsContent value="networth" className="reports-tab-content space-y-6">
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

          <TabsContent value="merchants" className="reports-tab-content space-y-6">
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
                        {merchantsQuery.data.map((m: MerchantSpend, i: number) => (
                          <tr
                            key={m.merchant_name}
                            className="border-b border-border/50 last:border-0 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300"
                            style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}
                          >
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

          <TabsContent value="health" className="reports-tab-content space-y-6">
            <Card className="hero-glow border-border/80 shadow-sm overflow-hidden">
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

// ---------------------------------------------------------------------------
// By Category row — expandable, mirrors the Income / Expenses drill-down
// ---------------------------------------------------------------------------

function transactionLabel(tx: Transaction): string {
  return tx.display_title || tx.merchant_name || tx.name || "Untitled";
}

function formatShortDate(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * One row in the Reports → By Category table. Click toggles an inline list
 * of the underlying transactions for the selected month — same affordance
 * the Income / Expenses tabs use when the user drills into a per-person
 * category total. `transaction_class: "expense"` keeps refunds in the
 * picture so the drilldown sum matches the bucket number even when the
 * category received a net credit.
 *
 * Primary view: `parent_category_id` rolls up the primary bucket + every
 * PFC-detailed child (`categories.parent_id`), mirroring the COALESCE
 * rule in /api/reports/by-category. Focus view: exact `category_id`.
 *
 * Drill-into-subcategories stays on the pie slice / legend (not on the
 * row click) — otherwise a single click would be ambiguous.
 */
function CategorySpendRow({
  row,
  index = 0,
  month,
  colorIndex,
  isActive,
  canDrillToSubcategories,
  onHover,
  onLeave,
  onDrillToSubcategories,
  onLock,
  mode,
}: {
  row: CategorySpend;
  index?: number;
  month: string;
  colorIndex: number;
  isActive: boolean;
  canDrillToSubcategories: boolean;
  onHover: () => void;
  onLeave: () => void;
  onDrillToSubcategories: () => void;
  onLock: () => void;
  mode: "primary" | "detailed";
}) {
  const [expanded, setExpanded] = useState(false);
  const hasCategoryId = row.category_id != null;
  const drillable = hasCategoryId;

  const txQuery = useQuery({
    queryKey: [
      "reports",
      "by-category",
      "transactions",
      month,
      mode,
      row.category_id,
    ],
    queryFn: () =>
      transactionsApi.list({
        month,
        ...(mode === "primary"
          ? { parent_category_id: row.category_id ?? undefined }
          : { category_id: row.category_id ?? undefined }),
        transaction_class: "expense",
        limit: 500,
      }),
    enabled: drillable && expanded,
    staleTime: 30_000,
  });

  return (
    <>
      <tr
        className={cn(
          "border-b border-border/50 last:border-0 transition-colors",
          "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300",
          isActive ? "bg-muted/50" : "hover:bg-muted/20",
          drillable ? "cursor-pointer" : "cursor-default",
        )}
        style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}
        onMouseEnter={onHover}
        onMouseLeave={onLeave}
        onClick={() => {
          if (!drillable) {
            onLock();
            return;
          }
          setExpanded((v) => !v);
        }}
        aria-expanded={drillable ? expanded : undefined}
      >
        <td className="px-4 py-3">
          <span className="inline-flex items-center gap-2 font-medium">
            {drillable ? (
              <ChevronRight
                className={cn(
                  "size-3.5 shrink-0 text-muted-foreground transition-transform",
                  expanded ? "rotate-90" : undefined,
                )}
                aria-hidden
              />
            ) : (
              <span className="size-3.5 shrink-0" aria-hidden />
            )}
            <span
              className="size-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: CATEGORY_COLORS[colorIndex % CATEGORY_COLORS.length] }}
            />
            <span className="truncate">{row.category_name}</span>
            {canDrillToSubcategories ? (
              <button
                type="button"
                className="shrink-0 rounded-full border border-border/60 bg-muted/40 px-2 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:border-border hover:bg-muted/80 hover:text-foreground"
                onClick={(event) => {
                  // Stop the row's toggle so "Focus" is a distinct action
                  // from "expand transactions". Mirror: pie slice click
                  // also drills into subcategories; row click expands.
                  event.stopPropagation();
                  onDrillToSubcategories();
                }}
                title={`Focus on ${row.children_count} subcategor${row.children_count === 1 ? "y" : "ies"}`}
              >
                {row.children_count}× subcategories
              </button>
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
                  backgroundColor: CATEGORY_COLORS[colorIndex % CATEGORY_COLORS.length],
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
      {expanded && drillable ? (
        <tr className="border-b border-border/50 last:border-0 bg-muted/10">
          <td colSpan={3} className="px-4 py-3">
            <CategoryTransactionsList
              isLoading={txQuery.isLoading}
              isError={txQuery.isError}
              error={txQuery.error as Error | null}
              rows={txQuery.data ?? []}
            />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function CategoryTransactionsList({
  isLoading,
  isError,
  error,
  rows,
}: {
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  rows: Transaction[];
}) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        Loading transactions…
      </div>
    );
  }
  if (isError) {
    return (
      <p className="py-2 text-xs text-destructive">
        {error?.message || "Failed to load transactions."}
      </p>
    );
  }
  if (rows.length === 0) {
    return (
      <p className="py-2 text-xs text-muted-foreground">
        No transactions in this category for the selected month.
      </p>
    );
  }
  return (
    <ul className="space-y-1">
      {rows.map((tx) => {
        const isRefund = tx.amount_cents < 0;
        return (
          <li
            key={tx.id}
            className="flex items-center justify-between gap-2 text-xs"
          >
            <span className="flex min-w-0 items-center gap-2">
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {formatShortDate(tx.authorized_date || tx.date)}
              </span>
              <span className="truncate">{transactionLabel(tx)}</span>
              {tx.is_pending ? (
                <span className="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400">
                  pending
                </span>
              ) : null}
              {tx.is_private ? (
                <span className="shrink-0 rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-medium text-violet-700 dark:text-violet-400">
                  private
                </span>
              ) : null}
              {isRefund ? (
                <span className="shrink-0 rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-400">
                  refund
                </span>
              ) : null}
            </span>
            <span
              className={cn(
                "shrink-0 tabular-nums",
                isRefund
                  ? "text-emerald-700 dark:text-emerald-400"
                  : "text-rose-700 dark:text-rose-400",
              )}
            >
              {isRefund ? "−" : ""}
              {formatMoney(Math.abs(tx.amount_cents))}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
