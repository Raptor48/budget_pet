"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout/app-layout";
import { CategoryDonutWidget } from "@/components/charts/category-donut-chart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  budgetsApi,
  insightsApi,
  recurringApi,
  reportsApi,
  transactionsApi,
} from "@/lib/api";
import { MonthYearPicker } from "@/components/ui/month-year-picker";
import { PlaidTxnAmount } from "@/components/ui/plaid-txn-amount";
import type { ForecastEntry, Transaction } from "@/types/v2";
import { cn } from "@/lib/utils";
import { composeInsightsBadge, pickTeaser } from "@/lib/insights-teaser";
import { Button } from "@/components/ui/button";

/** Plain currency (balances, aggregates — not Plaid signed transaction lines). */
function formatUsd(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

function currentMonthIso(): string {
  return new Date().toISOString().slice(0, 7);
}

function getDisplayName(tx: Transaction): string {
  return tx.merchant_name?.trim() || tx.name?.trim() || "Transaction";
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
  }
  if (parts.length === 1 && parts[0].length >= 2) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return (parts[0]?.[0] ?? "?").toUpperCase();
}

function sortForecastUpcoming(entries: ForecastEntry[]): ForecastEntry[] {
  return [...entries].sort(
    (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
  );
}

function topBudgetProgress<T extends { percent_used: number }>(
  rows: T[],
  n: number,
): T[] {
  return [...rows]
    .sort((a, b) => b.percent_used - a.percent_used)
    .slice(0, n);
}

function SectionSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-lg bg-muted", className)}
      aria-hidden
    />
  );
}

function MerchantAvatar({ tx }: { tx: Transaction }) {
  const name = getDisplayName(tx);
  const [failed, setFailed] = useState(false);
  const logo = tx.logo_url?.trim();

  if (logo && !failed) {
    return (
      <Image
        src={logo}
        alt=""
        width={40}
        height={40}
        className="size-10 shrink-0 rounded-full object-cover"
        onError={() => setFailed(true)}
        unoptimized
      />
    );
  }

  return (
    <div
      className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground"
      aria-hidden
    >
      {getInitials(name)}
    </div>
  );
}


function DashboardContent() {
  const month = currentMonthIso();
  const [spendMonth, setSpendMonth] = useState(month);
  const [forecastExpanded, setForecastExpanded] = useState(false);
  const [priceChangesExpanded, setPriceChangesExpanded] = useState(false);
  const [txExpanded, setTxExpanded] = useState(false);
  const [budgetExpanded, setBudgetExpanded] = useState(false);

  const netWorthQuery = useQuery({
    queryKey: ["reports", "net-worth"],
    queryFn: () => reportsApi.getNetWorth(),
    staleTime: 60_000,
  });

  const cashFlowQuery = useQuery({
    queryKey: ["reports", "cash-flow", month],
    queryFn: () => reportsApi.getCashFlow(month),
    staleTime: 60_000,
  });

  const healthQuery = useQuery({
    queryKey: ["reports", "financial-health"],
    queryFn: () => reportsApi.getFinancialHealth(),
    staleTime: 60_000,
  });

  const budgetProgressQuery = useQuery({
    queryKey: ["budgets", "progress", month],
    queryFn: () => budgetsApi.getProgress(month),
    staleTime: 60_000,
  });

  const forecastQuery = useQuery({
    queryKey: ["reports", "forecast", 30],
    queryFn: () => reportsApi.getForecast(30),
    staleTime: 60_000,
  });

  const priceChangesQuery = useQuery({
    queryKey: ["recurring", "price-changes"],
    queryFn: () => recurringApi.getPriceChanges(),
    staleTime: 60_000,
  });

  const transactionsQuery = useQuery({
    queryKey: ["transactions", "dashboard", { limit: 10 }],
    queryFn: () => transactionsApi.list({ limit: 10 }),
    staleTime: 30_000,
  });

  const byCategoryQuery = useQuery({
    queryKey: ["reports", "by-category", spendMonth, "primary"],
    queryFn: () => reportsApi.getByCategory(spendMonth, { rollup: "primary" }),
    staleTime: 60_000,
  });

  const insightsQuery = useQuery({
    queryKey: ["insights", "feed"],
    queryFn: () => insightsApi.getFeed(),
    staleTime: 120_000,
  });

  const netWorth = netWorthQuery.data;
  const cashFlow = cashFlowQuery.data;
  const health = healthQuery.data;
  const budgetRows = budgetProgressQuery.data ?? [];
  const topBudgets = topBudgetProgress(budgetRows, 5);
  const forecastSorted = sortForecastUpcoming(forecastQuery.data ?? []);
  const priceChanges = priceChangesQuery.data ?? [];
  const transactions = transactionsQuery.data ?? [];
  const byCategory = byCategoryQuery.data ?? [];
  const insights = insightsQuery.data;
  const insightsTeaser = pickTeaser(insights);

  const COMPACT_DEFAULT = 3;
  const visibleForecast = forecastExpanded ? forecastSorted : forecastSorted.slice(0, COMPACT_DEFAULT);
  const visiblePriceChanges = priceChangesExpanded ? priceChanges : priceChanges.slice(0, COMPACT_DEFAULT);
  const visibleTransactions = txExpanded ? transactions : transactions.slice(0, COMPACT_DEFAULT);
  const visibleBudgets = budgetExpanded ? topBudgets : topBudgets.slice(0, COMPACT_DEFAULT);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground text-sm">Overview for {spendMonth}</p>
      </div>

      {/* Row 1 — 4 KPI cards: Net Worth · Cash Flow · Health · Insights */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Net worth</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {netWorthQuery.isLoading ? (
              <SectionSkeleton className="h-16 w-full" />
            ) : netWorthQuery.isError ? (
              <p className="text-destructive text-sm">Could not load net worth.</p>
            ) : netWorth ? (
              <>
                <p className="text-2xl font-bold tabular-nums">
                  {formatUsd(netWorth.net_worth_cents)}
                </p>
                <dl className="space-y-1 text-xs">
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Cash & bank</dt>
                    <dd className="tabular-nums font-medium">{formatUsd(netWorth.liquid_cents)}</dd>
                  </div>
                  {netWorth.investment_cents > 0 && (
                    <div className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">Investments</dt>
                      <dd className="tabular-nums font-medium">{formatUsd(netWorth.investment_cents)}</dd>
                    </div>
                  )}
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Debt</dt>
                    <dd className="tabular-nums font-medium">{formatUsd(netWorth.debt_cents)}</dd>
                  </div>
                </dl>
              </>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Cash flow this month</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {cashFlowQuery.isLoading ? (
              <SectionSkeleton className="h-16 w-full" />
            ) : cashFlowQuery.isError ? (
              <p className="text-destructive text-sm">Could not load cash flow.</p>
            ) : cashFlow ? (
              <>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Income</span>
                  <span className="tabular-nums font-medium text-emerald-600 dark:text-emerald-400">
                    {formatUsd(cashFlow.income_cents)}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Expenses</span>
                  <span className="tabular-nums font-medium text-rose-600 dark:text-rose-400">
                    {formatUsd(cashFlow.expenses_cents)}
                  </span>
                </div>
                <div className="border-t pt-2">
                  <div className="flex justify-between text-sm font-semibold">
                    <span>Net</span>
                    <span
                      className={cn(
                        "tabular-nums",
                        cashFlow.net_cents >= 0
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-rose-600 dark:text-rose-400",
                      )}
                    >
                      {formatUsd(cashFlow.net_cents)}
                    </span>
                  </div>
                </div>
              </>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Financial health</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {healthQuery.isLoading ? (
              <SectionSkeleton className="h-16 w-full" />
            ) : healthQuery.isError ? (
              <p className="text-destructive text-sm">Could not load health score.</p>
            ) : health ? (
              <>
                <div className="flex items-center gap-2">
                  <span className="text-2xl font-bold tabular-nums">{health.score}</span>
                  <Badge className="border-0 font-medium text-white" style={{ backgroundColor: health.color }}>
                    {health.label}
                  </Badge>
                </div>
                {health.advice && (
                  <p className="text-muted-foreground text-xs leading-snug">{health.advice}</p>
                )}
              </>
            ) : null}
          </CardContent>
        </Card>

        <Link href="/insights" className="group block outline-none">
          <Card
            className={cn(
              "h-full border-primary/20 transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:shadow-lg",
              insightsTeaser?.severity === "warn" && "border-amber-500/60",
            )}
          >
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between gap-2 text-sm font-medium text-muted-foreground">
                Insights
                <Badge
                  variant={insightsTeaser?.severity === "warn" ? "destructive" : "secondary"}
                  className="font-normal"
                >
                  {composeInsightsBadge(insights)}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <p className="text-sm leading-snug text-foreground">
                {insightsTeaser?.summary ?? "Trends, health, and spending stories."}
              </p>
              {insightsTeaser?.action_url && insightsTeaser.action_label && (
                <Button
                  asChild
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Link href={insightsTeaser.action_url}>{insightsTeaser.action_label}</Link>
                </Button>
              )}
              <p className="text-primary text-xs font-medium group-hover:underline">View all insights →</p>
            </CardContent>
          </Card>
        </Link>
      </div>

      {/* Row 2 — Spending pie (2/3) + Budget compact (1/3) */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-4 space-y-0">
            <div>
              <CardTitle className="flex items-center gap-2">
                <span>Spending by category</span>
                <Link
                  href="/reports"
                  className="text-primary text-xs font-medium hover:underline"
                >
                  View full breakdown →
                </Link>
              </CardTitle>
              <CardDescription>Month total (split-aware, primary categories)</CardDescription>
            </div>
            <MonthYearPicker value={spendMonth} onChange={setSpendMonth} />
          </CardHeader>
          <CardContent>
            {byCategoryQuery.isLoading ? (
              <SectionSkeleton className="h-[240px] w-full" />
            ) : byCategoryQuery.isError ? (
              <p className="text-destructive text-sm">Could not load category data.</p>
            ) : (
              <CategoryDonutWidget data={byCategory} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 pb-3">
            <div>
              <CardTitle className="text-sm font-semibold">Budget envelopes</CardTitle>
              <CardDescription className="text-xs">Top by utilization</CardDescription>
            </div>
            <Link href="/settings/budgets" className="text-primary text-xs font-medium hover:underline shrink-0">
              View all
            </Link>
          </CardHeader>
          <CardContent className="space-y-3">
            {budgetProgressQuery.isLoading ? (
              <SectionSkeleton className="h-24 w-full" />
            ) : budgetProgressQuery.isError ? (
              <p className="text-destructive text-xs">Could not load budget progress.</p>
            ) : topBudgets.length === 0 ? (
              <p className="text-muted-foreground text-xs">No budget data for this month.</p>
            ) : (
              <>
                <ul className="space-y-2.5">
                  {visibleBudgets.map((row) => {
                    const pct = Math.min(100, Math.max(0, row.percent_used));
                    const over = row.percent_used > 100;
                    return (
                      <li key={`${row.category_id}-${row.month}`}>
                        <Link href="/settings/budgets" className="block rounded outline-none focus-visible:ring-2 focus-visible:ring-ring">
                          <div className="mb-1 flex items-center justify-between gap-1 text-xs">
                            <span className="truncate font-medium">{row.category_name}</span>
                            <span className={cn("shrink-0 tabular-nums text-muted-foreground", over && "text-destructive font-semibold")}>
                              {row.percent_used.toFixed(0)}%
                            </span>
                          </div>
                          <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
                            <div
                              className={cn("h-full rounded-full transition-all", over ? "bg-destructive" : !row.category_color ? "bg-primary" : "")}
                              style={{ width: `${pct}%`, ...(!over && row.category_color ? { backgroundColor: row.category_color } : {}) }}
                            />
                          </div>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
                {topBudgets.length > COMPACT_DEFAULT && (
                  <button
                    type="button"
                    onClick={() => setBudgetExpanded((v) => !v)}
                    className="text-xs text-primary hover:underline"
                  >
                    {budgetExpanded ? "Show less ↑" : `Show ${topBudgets.length - COMPACT_DEFAULT} more ↓`}
                  </button>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Row 3 — 3 compact cards: Forecast · Price Changes · Recent */}
      <div className="grid gap-4 md:grid-cols-3">
        {/* Forecast */}
        <Card>
          <CardHeader className="pb-2">
            <Link href="/recurring" className="outline-none focus-visible:ring-2 focus-visible:ring-ring rounded">
              <CardTitle className="text-sm font-semibold hover:underline">Cash flow forecast</CardTitle>
              <CardDescription className="text-xs">Upcoming bills — 30 days</CardDescription>
            </Link>
          </CardHeader>
          <CardContent className="p-0">
            {forecastQuery.isLoading ? (
              <div className="px-6 pb-4"><SectionSkeleton className="h-20 w-full" /></div>
            ) : forecastQuery.isError ? (
              <p className="px-6 pb-4 text-destructive text-xs">Could not load forecast.</p>
            ) : forecastSorted.length === 0 ? (
              <p className="px-6 pb-4 text-muted-foreground text-xs">No upcoming bills detected.</p>
            ) : (
              <div>
                <ul className="divide-y">
                  {visibleForecast.map((entry) => (
                    <li key={`${entry.stream_id}-${entry.date}-${entry.description}`}>
                      <Link
                        href={`/recurring?stream=${entry.stream_id}`}
                        className="flex items-center justify-between gap-2 px-4 py-1.5 text-xs transition-colors hover:bg-muted/50"
                      >
                        <div className="min-w-0">
                          <p className="truncate font-medium">{entry.description}</p>
                          <p className="text-muted-foreground tabular-nums">{entry.date}</p>
                        </div>
                        <PlaidTxnAmount cents={entry.amount_cents} size="sm" tone="flow" className="shrink-0 font-medium" />
                      </Link>
                    </li>
                  ))}
                </ul>
                {forecastSorted.length > COMPACT_DEFAULT && (
                  <button
                    type="button"
                    onClick={() => setForecastExpanded((v) => !v)}
                    className="w-full px-4 py-2 text-left text-xs text-primary hover:underline border-t"
                  >
                    {forecastExpanded ? "Show less ↑" : `Show ${forecastSorted.length - COMPACT_DEFAULT} more ↓`}
                  </button>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Price change alerts */}
        <Card>
          <CardHeader className="pb-2">
            <Link href="/recurring" className="outline-none focus-visible:ring-2 focus-visible:ring-ring rounded">
              <CardTitle className="text-sm font-semibold hover:underline">Price change alerts</CardTitle>
              <CardDescription className="text-xs">Subscriptions with recent changes</CardDescription>
            </Link>
          </CardHeader>
          <CardContent className="p-0">
            {priceChangesQuery.isLoading ? (
              <div className="px-6 pb-4"><SectionSkeleton className="h-12 w-full" /></div>
            ) : priceChangesQuery.isError ? (
              <p className="px-6 pb-4 text-destructive text-xs">Could not load price changes.</p>
            ) : priceChanges.length === 0 ? (
              <p className="px-6 pb-4 text-muted-foreground text-xs">No subscription price changes detected.</p>
            ) : (
              <div>
                <ul className="divide-y">
                  {visiblePriceChanges.map((stream) => {
                    const pct = stream.price_change_pct ?? "0";
                    return (
                      <li key={stream.id}>
                        <Link
                          href={`/recurring?stream=${stream.id}`}
                          className="flex items-center justify-between gap-2 px-4 py-1.5 text-xs transition-colors hover:bg-muted/50"
                        >
                          <div className="min-w-0">
                            <p className="truncate font-medium">
                              {stream.user_label || stream.merchant_name || stream.description}
                            </p>
                            <p className="text-muted-foreground">{stream.frequency ?? "Recurring"}</p>
                          </div>
                          <Badge variant="destructive" className="shrink-0 text-[10px] px-1.5 py-0">
                            +{pct}%
                          </Badge>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
                {priceChanges.length > COMPACT_DEFAULT && (
                  <button
                    type="button"
                    onClick={() => setPriceChangesExpanded((v) => !v)}
                    className="w-full px-4 py-2 text-left text-xs text-primary hover:underline border-t"
                  >
                    {priceChangesExpanded ? "Show less ↑" : `Show ${priceChanges.length - COMPACT_DEFAULT} more ↓`}
                  </button>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent transactions */}
        <Card>
          <CardHeader className="pb-2">
            <Link href="/transactions" className="outline-none focus-visible:ring-2 focus-visible:ring-ring rounded">
              <CardTitle className="text-sm font-semibold hover:underline">Recent transactions</CardTitle>
              <CardDescription className="text-xs">Latest activity</CardDescription>
            </Link>
          </CardHeader>
          <CardContent className="p-0">
            {transactionsQuery.isLoading ? (
              <div className="px-6 pb-4"><SectionSkeleton className="h-24 w-full" /></div>
            ) : transactionsQuery.isError ? (
              <p className="px-6 pb-4 text-destructive text-xs">Could not load transactions.</p>
            ) : transactions.length === 0 ? (
              <p className="px-6 pb-4 text-muted-foreground text-xs">No transactions yet.</p>
            ) : (
              <div>
                <ul className="divide-y">
                  {visibleTransactions.map((tx) => {
                    const when = tx.authorized_date || tx.date;
                    return (
                      <li key={tx.id}>
                        <Link
                          href={`/transactions?highlight=${tx.id}`}
                          className="flex items-center gap-2 px-4 py-1.5 text-xs transition-colors hover:bg-muted/50"
                        >
                          <MerchantAvatar tx={tx} />
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-medium">{getDisplayName(tx)}</p>
                            <p className="text-muted-foreground tabular-nums">{when}</p>
                          </div>
                          <PlaidTxnAmount cents={tx.amount_cents} size="sm" tone="flow" className="shrink-0 font-medium" />
                        </Link>
                      </li>
                    );
                  })}
                </ul>
                {transactions.length > COMPACT_DEFAULT && (
                  <button
                    type="button"
                    onClick={() => setTxExpanded((v) => !v)}
                    className="w-full px-4 py-2 text-left text-xs text-primary hover:underline border-t"
                  >
                    {txExpanded ? "Show less ↑" : `Show ${transactions.length - COMPACT_DEFAULT} more ↓`}
                  </button>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <AppLayout>
      <DashboardContent />
    </AppLayout>
  );
}
