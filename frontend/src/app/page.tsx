"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { AppLayout } from "@/components/layout/app-layout";
import { CategoryDonutWidget } from "@/components/charts/category-donut-chart";
import { FinancialHealthCompactCard } from "@/components/reports/financial-health-hero-card";
import { PlaidAttentionPlate } from "@/components/layout/plaid-attention-banner";
import { TodaysActionsSection } from "@/components/dashboard/todays-actions";
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
  plaidApi,
  recurringApi,
  reportsApi,
  transactionsApi,
} from "@/lib/api";
import { TrendingDown, TrendingUp } from "lucide-react";
import { PlaidTxnAmount } from "@/components/ui/plaid-txn-amount";
import type { ForecastEntry, RecurringStream, Transaction } from "@/types/v2";
import { cn } from "@/lib/utils";
import { composeInsightsBadge, pickTeaser } from "@/lib/insights-teaser";
import { streamTitle } from "@/app/recurring/_components/recurring-helpers";
import { normalizeTransactionTitle } from "@/lib/transaction-display";

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

/** Render an ISO date as "May 20" — the dashboard's month context already
 *  makes the year obvious, so YYYY-MM-DD is wasted ink in list rows. */
function formatDayLabel(iso: string): string {
  try {
    return format(parseISO(iso), "MMM d");
  } catch {
    return iso;
  }
}

/** Plaid surfaces recurring frequencies as UPPERCASE ("MONTHLY", "WEEKLY").
 *  Title case reads more naturally in list rows. */
function formatFrequency(freq: string | null | undefined): string {
  if (!freq) return "Recurring";
  return freq.charAt(0).toUpperCase() + freq.slice(1).toLowerCase();
}

function getDisplayName(tx: Transaction): string {
  return normalizeTransactionTitle(tx);
}

/** Forecast entries come from the recurring endpoint without `display_title`,
 *  but they share the merchant_name + description fields. Route them through
 *  the same normalizer the Transactions page uses so list rows never show raw
 *  bank descriptors. */
function getForecastName(entry: ForecastEntry): string {
  return normalizeTransactionTitle({
    merchant_name: entry.merchant_name,
    name: entry.description,
    description: entry.description,
  });
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

/** Deterministic 8-color gradient picker — same algorithm the Transactions
 *  modal uses, ported here so all three dashboard list tiles render the same
 *  merchant with the same color across reloads. */
// Mirrors the muted palette in recurring-helpers.tsx: 500 → 700 with /70-/75
// alpha so the avatar reads as a tinted background block rather than a
// saturated chip. Keep these three copies in sync (dashboard / transactions
// list / transactions mobile-card) until someone factors a shared module.
const MERCHANT_GRADIENTS = [
  "from-rose-500/70 to-pink-700/75",
  "from-orange-500/70 to-amber-700/75",
  "from-yellow-500/70 to-lime-700/75",
  "from-emerald-500/70 to-teal-700/75",
  "from-cyan-500/70 to-sky-700/75",
  "from-blue-500/70 to-indigo-700/75",
  "from-violet-500/70 to-fuchsia-700/75",
  "from-fuchsia-500/70 to-rose-700/75",
] as const;

function pickGradient(seed: string): string {
  let hash = 0;
  const s = seed.toLowerCase().replace(/[^a-z0-9]/g, "") || "?";
  for (let i = 0; i < s.length; i++) {
    hash = (hash * 31 + s.charCodeAt(i)) | 0;
  }
  return MERCHANT_GRADIENTS[Math.abs(hash) % MERCHANT_GRADIENTS.length];
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

/**
 * Tiny "↑/↓ $X vs Mar" line under the KPI headline number.
 *
 * Sign convention: positive `cents` means "this month is bigger than last
 * month" — the caller decides whether that's good (cash flow improved) or
 * bad (net worth dropped). `goodWhenPositive` flips the color so the same
 * helper works for income-flavored and balance-flavored numbers.
 *
 * Hidden when `cents == null` (e.g. no prior data yet) so we don't render
 * a "+0 vs prev" line that's worse than nothing.
 */
function DeltaLine({
  cents,
  monthShort,
  goodWhenPositive,
}: {
  cents: number | null;
  monthShort: string;
  goodWhenPositive: boolean;
}) {
  if (cents == null) return null;
  const isPositive = cents > 0;
  const isNegative = cents < 0;
  const Icon = isNegative ? TrendingDown : TrendingUp;
  const isGood =
    (isPositive && goodWhenPositive) || (isNegative && !goodWhenPositive);
  const isBad =
    (isPositive && !goodWhenPositive) || (isNegative && goodWhenPositive);
  const tone = isGood
    ? "text-emerald-600 dark:text-emerald-400"
    : isBad
      ? "text-rose-600 dark:text-rose-400"
      : "text-muted-foreground";
  const sign = cents >= 0 ? "+" : "−";
  const abs = Math.abs(cents);
  return (
    <p
      className={cn(
        "flex items-center gap-1.5 text-sm font-semibold leading-none",
        tone,
      )}
    >
      {cents !== 0 ? <Icon className="size-3.5" aria-hidden /> : null}
      <span className="tabular-nums">
        {sign}
        {new Intl.NumberFormat("en-US", {
          style: "currency",
          currency: "USD",
          minimumFractionDigits: 0,
          maximumFractionDigits: 0,
        }).format(abs / 100)}
      </span>
      <span className="text-muted-foreground/80 text-xs font-normal">vs {monthShort}</span>
    </p>
  );
}

/** Avatar for a dashboard list row. Plaid logo wins when present; otherwise
 *  falls back to a deterministic gradient circle with the merchant initials.
 *  `seed` lets the caller stabilize the gradient color across reloads (e.g.
 *  `merchant_entity_id` for transactions, `stream_id` for recurring rows).
 *  Defaults to `name` so callers without a stable key still get a consistent
 *  color per merchant. */
function MerchantAvatar({
  name,
  logoUrl,
  seed,
  size = 32,
}: {
  name: string;
  logoUrl?: string | null;
  seed?: string;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const logo = logoUrl?.trim();
  if (logo && !failed) {
    return (
      <Image
        src={logo}
        alt=""
        width={size}
        height={size}
        className="shrink-0 rounded-full object-cover shadow-sm ring-1 ring-border/60"
        style={{ width: size, height: size }}
        onError={() => setFailed(true)}
        unoptimized
      />
    );
  }
  const gradient = pickGradient(seed || name);
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-xs font-semibold text-white shadow-sm ring-1 ring-border/60",
        gradient,
      )}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <span className="leading-none drop-shadow-sm">{getInitials(name)}</span>
    </div>
  );
}


function DashboardContent() {
  const month = currentMonthIso();
  // Previous month YYYY-MM, used for the MoM-delta context lines on the
  // Cash Flow + Net Worth KPI cards.
  const prevMonth = (() => {
    const [y, m] = month.split("-").map(Number);
    if (!y || !m) return month;
    const py = m === 1 ? y - 1 : y;
    const pm = m === 1 ? 12 : m - 1;
    return `${py.toString().padStart(4, "0")}-${pm.toString().padStart(2, "0")}`;
  })();

  const [forecastExpanded, setForecastExpanded] = useState(false);
  const [priceChangesExpanded, setPriceChangesExpanded] = useState(false);
  const [txExpanded, setTxExpanded] = useState(false);
  const [budgetExpanded, setBudgetExpanded] = useState(false);

  const netWorthQuery = useQuery({
    queryKey: ["reports", "net-worth"],
    queryFn: () => reportsApi.getNetWorth(),
    staleTime: 60_000,
  });

  // Last 2 net-worth snapshots → for the "vs last month" delta. Cheap, the
  // reports tab already pulls 12 of these; the cache layer dedupes.
  const netWorthHistoryQuery = useQuery({
    queryKey: ["reports", "net-worth-history", 2],
    queryFn: () => reportsApi.getNetWorthHistory(2),
    staleTime: 60_000,
  });

  const cashFlowQuery = useQuery({
    queryKey: ["reports", "cash-flow", month],
    queryFn: () => reportsApi.getCashFlow(month),
    staleTime: 60_000,
  });

  // Previous-month cash flow → MoM delta. Same endpoint, prior month key.
  const cashFlowPrevQuery = useQuery({
    queryKey: ["reports", "cash-flow", prevMonth],
    queryFn: () => reportsApi.getCashFlow(prevMonth),
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

  // Spending breakdown — always current month on the Dashboard. Reports has
  // a month picker for the rest; the Dashboard's contract is "right now".
  const byCategoryQuery = useQuery({
    queryKey: ["reports", "by-category", month, "primary"],
    queryFn: () => reportsApi.getByCategory(month, { rollup: "primary" }),
    staleTime: 60_000,
  });

  const insightsQuery = useQuery({
    queryKey: ["insights", "feed"],
    queryFn: () => insightsApi.getFeed(),
    staleTime: 120_000,
  });

  // Plaid items power the "last synced" timestamp + the Sync now button.
  // Same query the sidebar uses for the Settings dot — react-query dedupes.
  const plaidItemsQuery = useQuery({
    queryKey: ["plaid-items"],
    queryFn: plaidApi.listItems,
    staleTime: 60_000,
  });

  const netWorth = netWorthQuery.data;
  const cashFlow = cashFlowQuery.data;
  const cashFlowPrev = cashFlowPrevQuery.data;
  const health = healthQuery.data;
  // Still needed for TodaysActionsSection (item_login_required surfacing);
  // the sync button + last-synced timestamp moved to AppLayout.
  const plaidItems = plaidItemsQuery.data ?? [];

  // MoM deltas — surfaced only when we have a prior data point to compare
  // against; otherwise the line is hidden so we don't render "+0 vs Mar"
  // when there literally is no Mar.
  const cashFlowNetDelta =
    cashFlow != null && cashFlowPrev != null
      ? cashFlow.net_cents - cashFlowPrev.net_cents
      : null;
  const netWorthHistory = netWorthHistoryQuery.data ?? [];
  const netWorthDelta =
    netWorth != null && netWorthHistory.length >= 2
      ? netWorth.net_worth_cents -
        netWorthHistory[netWorthHistory.length - 2].net_worth_cents
      : null;

  const prevMonthShort = (() => {
    const [y, m] = prevMonth.split("-").map(Number);
    if (!y || !m) return prevMonth;
    return new Date(y, m - 1, 15).toLocaleDateString("en-US", { month: "short" });
  })();
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

  // Pretty current-month label for the inline header — "April 2026" beats
  // the raw "2026-04" YYYY-MM token.
  const currentMonthLabel = (() => {
    const [y, m] = month.split("-").map(Number);
    if (!y || !m) return month;
    return new Date(y, m - 1, 15).toLocaleDateString("en-US", {
      month: "long",
      year: "numeric",
    });
  })();

  return (
    <div className="flex flex-col gap-6">
      {/* Slim breadcrumb-style header. The global top bar (AppLayout)
          carries Last-synced + Sync now, so this just anchors the page
          context. The sidebar already says we're on the Dashboard, so the
          H1+subtitle stack from before was wasted vertical. */}
      <div className="flex flex-wrap items-center gap-3 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Overview · <span className="text-foreground">{currentMonthLabel}</span>
        </p>
      </div>

      {/* Inline plate replaces the global full-width banner from before.
          Auto-hides when nothing's wrong, so it doesn't add noise. */}
      <PlaidAttentionPlate />

      {/* Row 1 — 4 KPI cards in a single line: Net Worth · Cash Flow · Health · Insights.
          Each card aims for the same visual weight (~150px tall): a headline number,
          one secondary line of context, and at most one accent. */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="gap-3">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-base font-bold text-foreground">Net worth</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-2">
            {netWorthQuery.isLoading ? (
              <SectionSkeleton className="h-16 w-full" />
            ) : netWorthQuery.isError ? (
              <p className="text-destructive text-sm">Could not load net worth.</p>
            ) : netWorth ? (
              <>
                <p
                  className={cn(
                    "text-2xl font-bold tabular-nums",
                    netWorth.net_worth_cents < 0 && "text-rose-600 dark:text-rose-400",
                  )}
                >
                  {formatUsd(netWorth.net_worth_cents)}
                </p>
                <div className="mt-auto space-y-1.5">
                  <DeltaLine
                    cents={netWorthDelta}
                    monthShort={prevMonthShort}
                    goodWhenPositive
                  />
                  <p className="text-muted-foreground text-[11px] leading-snug">
                    Liquid <span className="tabular-nums font-medium text-foreground/90">{formatUsd(netWorth.liquid_cents)}</span>
                    {netWorth.investment_cents > 0 ? (
                      <>
                        {" · "}Invest{" "}
                        <span className="tabular-nums font-medium text-foreground/90">
                          {formatUsd(netWorth.investment_cents)}
                        </span>
                      </>
                    ) : null}
                    {" · "}Debt{" "}
                    <span className="tabular-nums font-medium text-foreground/90">{formatUsd(netWorth.debt_cents)}</span>
                  </p>
                </div>
              </>
            ) : null}
          </CardContent>
        </Card>

        <Card className="gap-3">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-base font-bold text-foreground">Cash flow this month</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-2">
            {cashFlowQuery.isLoading ? (
              <SectionSkeleton className="h-16 w-full" />
            ) : cashFlowQuery.isError ? (
              <p className="text-destructive text-sm">Could not load cash flow.</p>
            ) : cashFlow ? (
              <>
                <p
                  className={cn(
                    "text-2xl font-bold tabular-nums",
                    cashFlow.net_cents >= 0
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-rose-600 dark:text-rose-400",
                  )}
                >
                  {formatUsd(cashFlow.net_cents)}
                </p>
                <div className="mt-auto space-y-1.5">
                  <DeltaLine
                    cents={cashFlowNetDelta}
                    monthShort={prevMonthShort}
                    goodWhenPositive
                  />
                  <p className="text-muted-foreground text-[11px] leading-snug">
                    Income{" "}
                    <span className="tabular-nums font-medium text-emerald-600 dark:text-emerald-400">
                      {formatUsd(cashFlow.income_cents)}
                    </span>
                    {" · "}Expenses{" "}
                    <span className="tabular-nums font-medium text-rose-600 dark:text-rose-400">
                      {formatUsd(cashFlow.expenses_cents)}
                    </span>
                  </p>
                </div>
              </>
            ) : null}
          </CardContent>
        </Card>

        <FinancialHealthCompactCard
          score={health}
          isLoading={healthQuery.isLoading}
          isError={healthQuery.isError}
        />

        {/* Insights card. Single CTA contract: when the most-severe card has
            an action URL we jump the user to that filtered view directly;
            when there's no actionable target, the whole card links to the
            full insights feed. Two visible CTAs were noisy and competed. */}
        {(() => {
          const hasAction = Boolean(
            insightsTeaser?.action_url && insightsTeaser.action_label,
          );
          const cardHref = hasAction
            ? insightsTeaser!.action_url!
            : "/insights";
          const ctaLabel = hasAction
            ? insightsTeaser!.action_label!
            : "View all insights";
          return (
            <Link href={cardHref} className="group block outline-none">
              <Card className="h-full gap-3 transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:shadow-lg">
                <CardHeader className="pb-3 border-b">
                  <CardTitle className="flex items-center justify-between gap-2 text-base font-bold text-foreground">
                    Insights
                    <Badge
                      variant={
                        insightsTeaser?.severity === "warn" ? "destructive" : "secondary"
                      }
                      className="font-normal"
                    >
                      {composeInsightsBadge(insights)}
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col gap-2">
                  <p className="line-clamp-3 text-sm leading-snug text-foreground">
                    {insightsTeaser?.summary ?? "Trends, health, and spending stories."}
                  </p>
                  <p className="mt-auto text-primary text-xs font-medium transition-transform group-hover:underline group-hover:translate-x-0.5">
                    {ctaLabel} →
                  </p>
                </CardContent>
              </Card>
            </Link>
          );
        })()}
      </div>

      {/* Today's actions — aggregates already-loaded signals (plaid attention,
          budgets over their cap, bills due in 7d, warn-severity insights)
          into a scannable action grid. Auto-hides when the household is in
          the clear, so it never adds noise on a quiet day. */}
      <TodaysActionsSection
        plaidItems={plaidItems}
        budgets={budgetRows}
        forecast={forecastSorted}
        insightCards={insights?.cards ?? []}
      />

      {/* Row 2 — Spending pie (2/3) + Budget compact (1/3) */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2 gap-3">
          <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-4 space-y-0 pb-3 border-b">
            <div>
              <CardTitle className="flex items-center gap-2 text-base font-bold text-foreground">
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

        <Card className="gap-3">
          <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 pb-3 border-b">
            <div>
              <CardTitle className="text-base font-bold text-foreground">Budget envelopes</CardTitle>
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
        <Card className="gap-3">
          <CardHeader className="pb-3 border-b">
            <Link href="/recurring" className="outline-none focus-visible:ring-2 focus-visible:ring-ring rounded">
              <CardTitle className="text-base font-bold text-foreground hover:underline">Cash flow forecast</CardTitle>
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
                  {visibleForecast.map((entry) => {
                    const name = getForecastName(entry);
                    return (
                      <li key={`${entry.stream_id}-${entry.date}-${entry.description}`}>
                        <Link
                          href={`/recurring?stream=${entry.stream_id}`}
                          className="flex items-center gap-2 px-4 py-1.5 text-xs transition-colors hover:bg-muted/50"
                        >
                          <MerchantAvatar name={name} seed={`stream-${entry.stream_id}`} />
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-medium">{name}</p>
                            <p className="text-muted-foreground">{formatDayLabel(entry.date)}</p>
                          </div>
                          <PlaidTxnAmount cents={entry.amount_cents} size="sm" tone="flow" className="shrink-0 font-medium" />
                        </Link>
                      </li>
                    );
                  })}
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
        <Card className="gap-3">
          <CardHeader className="pb-3 border-b">
            <Link href="/recurring" className="outline-none focus-visible:ring-2 focus-visible:ring-ring rounded">
              <CardTitle className="text-base font-bold text-foreground hover:underline">Price change alerts</CardTitle>
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
                  {visiblePriceChanges.map((stream: RecurringStream) => {
                    const pct = stream.price_change_pct ?? "0";
                    const name = streamTitle(stream);
                    return (
                      <li key={stream.id}>
                        <Link
                          href={`/recurring?stream=${stream.id}`}
                          className="flex items-center gap-2 px-4 py-1.5 text-xs transition-colors hover:bg-muted/50"
                        >
                          <MerchantAvatar name={name} seed={`stream-${stream.id}`} />
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-medium">{name}</p>
                            <p className="text-muted-foreground">{formatFrequency(stream.frequency)}</p>
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
        <Card className="gap-3">
          <CardHeader className="pb-3 border-b">
            <Link href="/transactions" className="outline-none focus-visible:ring-2 focus-visible:ring-ring rounded">
              <CardTitle className="text-base font-bold text-foreground hover:underline">Recent transactions</CardTitle>
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
                          <MerchantAvatar
                            name={getDisplayName(tx)}
                            logoUrl={tx.logo_url}
                            seed={tx.merchant_entity_id ?? undefined}
                          />
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-medium">{getDisplayName(tx)}</p>
                            <p className="text-muted-foreground">{formatDayLabel(when)}</p>
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
