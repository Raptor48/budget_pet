"use client";

/**
 * Redesigned Net Worth tab.
 *
 * The previous version showed four flat KPI tiles + a basic line chart with
 * two duplicate "2026-04" labels and no context. This rewrite is built
 * around four ideas:
 *
 *   1. Hero — the headline number is the centerpiece. MoM and 6-mo deltas
 *      sit right under it so "−$4,062" actually answers "is this getting
 *      better or worse?".
 *   2. Composition bar — the math (Liquid + Portfolio − Debt = Net) gets a
 *      visual treatment so you don't have to read three tiles and add in
 *      your head.
 *   3. Stacked area history — assets stack up, debts stack down (negative).
 *      Net Worth line is overlaid. Replaces the old single-color line chart
 *      that didn't tell you which component was moving.
 *   4. Breakdown — every contributing account, two columns (Assets / Debts),
 *      with branding. Click-through to /accounts.
 *
 * Plus a smart-insight strip at the bottom (debt-payoff projection) when
 * the data supports it.
 */

import { useMemo } from "react";
import Link from "next/link";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowDownRight,
  ArrowUpRight,
  Banknote,
  CreditCard,
  Landmark,
  Sparkles,
  TrendingUp,
  Wallet,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AnimatedMoney } from "@/components/ui/animated-money";
import { formatMoney as formatUsd } from "@/components/accounts/helpers";
import { cn } from "@/lib/utils";
import type {
  NetWorthAccountRow,
  NetWorthSnapshot,
  NetWorthSummary,
} from "@/types/v2";

const ASSET_COLOR = "var(--color-emerald-500, #10b981)";
const DEBT_COLOR = "var(--color-rose-500, #f43f5e)";
const NET_COLOR = "var(--color-primary, #6366f1)";

// ---------------------------------------------------------------------------
// Top-level export
// ---------------------------------------------------------------------------

export function NetWorthTab({
  summary,
  history,
  isLoading,
  isError,
}: {
  summary: NetWorthSummary | undefined;
  history: NetWorthSnapshot[] | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  if (isError) {
    return (
      <Card className="border-destructive/40">
        <CardContent className="py-8 text-center text-sm text-destructive">
          Could not load net worth.
        </CardContent>
      </Card>
    );
  }

  if (isLoading || !summary) {
    return <NetWorthSkeleton />;
  }

  return (
    // ``reports-tab-stagger`` (defined in globals.css) applies a 80 ms
    // staggered fade-in/slide-up to each direct child. Lives here on
    // the inner div, not on the parent <TabsContent>, because the
    // selector targets direct children — and TabsContent's only direct
    // child is this div.
    <div className="reports-tab-stagger space-y-6">
      <NetWorthHero summary={summary} />
      <CompositionCard summary={summary} />
      <HistoryCard summary={summary} history={history ?? []} />
      <BreakdownCard accounts={summary.accounts} />
      {summary.debt_payoff_months != null && (
        <SmartInsightsStrip summary={summary} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hero
// ---------------------------------------------------------------------------

function NetWorthHero({ summary }: { summary: NetWorthSummary }) {
  const negative = summary.net_worth_cents < 0;
  return (
    <Card className="hero-glow overflow-hidden border-border/80">
      <CardContent className="space-y-5 p-6 sm:p-8">
        <div className="flex flex-col gap-1">
          <p className="text-muted-foreground text-xs font-medium uppercase tracking-wider">
            Net worth
          </p>
          <AnimatedMoney
            cents={summary.net_worth_cents}
            as="p"
            className={cn(
              "text-4xl font-semibold tracking-tight tabular-nums sm:text-5xl",
              negative ? "text-rose-500" : "text-emerald-500",
            )}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <DeltaPill
            label="vs last month"
            cents={summary.mom_delta_cents}
            comparedTo={summary.mom_compared_to}
          />
          <DeltaPill
            label="vs 6 months ago"
            cents={summary.six_month_delta_cents}
            comparedTo={summary.six_month_compared_to}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function DeltaPill({
  label,
  cents,
  comparedTo,
}: {
  label: string;
  cents: number | null;
  comparedTo: string | null;
}) {
  if (cents == null) {
    return (
      <span className="text-muted-foreground inline-flex items-center gap-1 rounded-full border border-border/60 bg-muted/30 px-2.5 py-1 text-xs">
        — {label}
      </span>
    );
  }
  const positive = cents >= 0;
  const Icon = positive ? ArrowUpRight : ArrowDownRight;
  const tone = positive
    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300"
    : "border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-300";
  const sign = positive ? "+" : "−";
  const niceDate = comparedTo ? formatShortDate(comparedTo) : null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium tabular-nums",
        tone,
      )}
      title={niceDate ? `Compared to snapshot on ${niceDate}` : undefined}
    >
      <Icon className="size-3.5" aria-hidden />
      {sign}
      {formatUsd(Math.abs(cents))}
      <span className="text-muted-foreground/80 font-normal">{label}</span>
    </span>
  );
}

function formatShortDate(iso: string): string {
  try {
    return new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Composition bar — visual math
// ---------------------------------------------------------------------------

function CompositionCard({ summary }: { summary: NetWorthSummary }) {
  const assets = summary.liquid_cents + summary.investment_cents;
  const debts = summary.debt_cents;
  const total = Math.max(assets, debts, 1); // avoid /0; bar is normalised to the bigger side
  const liquidPct = (summary.liquid_cents / total) * 100;
  const portfolioPct = (summary.investment_cents / total) * 100;
  const debtPct = (debts / total) * 100;

  const segments = [
    {
      key: "liquid",
      label: "Cash & Savings",
      cents: summary.liquid_cents,
      color: "bg-emerald-500",
      textColor: "text-emerald-600 dark:text-emerald-300",
      icon: Wallet,
      pct: liquidPct,
    },
    {
      key: "investment",
      label: "Portfolio",
      cents: summary.investment_cents,
      color: "bg-sky-500",
      textColor: "text-sky-600 dark:text-sky-300",
      icon: TrendingUp,
      pct: portfolioPct,
    },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Composition</CardTitle>
        <CardDescription>How today&rsquo;s balance sheet adds up.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-6 lg:grid-cols-2">
          <CompositionSide label="Assets" total={assets} tone="asset">
            {segments.map(({ key, ...rest }) => (
              <CompositionSegment key={key} {...rest} />
            ))}
            {assets === 0 && (
              <p className="text-muted-foreground text-xs">No assets tracked yet.</p>
            )}
          </CompositionSide>

          <CompositionSide label="Debts" total={debts} tone="debt">
            <CompositionSegment
              label="Loans & Credit"
              cents={debts}
              color="bg-rose-500"
              textColor="text-rose-600 dark:text-rose-300"
              icon={CreditCard}
              pct={debtPct}
            />
            {debts === 0 && (
              <p className="text-muted-foreground text-xs">No debts tracked.</p>
            )}
          </CompositionSide>
        </div>

        {/* Math equation strip */}
        <div className="flex flex-wrap items-baseline gap-2 border-t border-border/60 pt-4 text-sm">
          <span className="text-emerald-600 dark:text-emerald-300 font-semibold tabular-nums">
            {formatUsd(assets)}
          </span>
          <span className="text-muted-foreground">assets</span>
          <span className="text-muted-foreground">−</span>
          <span className="text-rose-600 dark:text-rose-300 font-semibold tabular-nums">
            {formatUsd(debts)}
          </span>
          <span className="text-muted-foreground">debts</span>
          <span className="text-muted-foreground">=</span>
          <span
            className={cn(
              "font-semibold tabular-nums",
              summary.net_worth_cents < 0
                ? "text-rose-600 dark:text-rose-300"
                : "text-emerald-600 dark:text-emerald-300",
            )}
          >
            {formatUsd(summary.net_worth_cents)}
          </span>
          <span className="text-muted-foreground">net worth</span>
        </div>
      </CardContent>
    </Card>
  );
}

function CompositionSide({
  label,
  total,
  tone,
  children,
}: {
  label: string;
  total: number;
  tone: "asset" | "debt";
  children: React.ReactNode;
}) {
  const colorRing = tone === "asset"
    ? "border-emerald-500/30 bg-emerald-500/[0.04]"
    : "border-rose-500/30 bg-rose-500/[0.04]";
  return (
    <div className={cn("rounded-xl border p-4", colorRing)}>
      <div className="mb-3 flex items-baseline justify-between">
        <p className="text-muted-foreground text-[11px] font-semibold uppercase tracking-wider">
          {label}
        </p>
        <p
          className={cn(
            "text-base font-semibold tabular-nums",
            tone === "asset"
              ? "text-emerald-600 dark:text-emerald-300"
              : "text-rose-600 dark:text-rose-300",
          )}
        >
          {formatUsd(total)}
        </p>
      </div>
      <div className="space-y-2.5">{children}</div>
    </div>
  );
}

function CompositionSegment({
  label,
  cents,
  color,
  textColor,
  icon: Icon,
  pct,
}: {
  label: string;
  cents: number;
  color: string;
  textColor: string;
  icon: React.ComponentType<{ className?: string }>;
  pct: number;
}) {
  const safePct = Math.min(100, Math.max(0, pct));
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground inline-flex items-center gap-1.5">
          <Icon className={cn("size-3.5", textColor)} />
          {label}
        </span>
        <span className="tabular-nums font-medium">{formatUsd(cents)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted/60">
        <div
          className={cn(
            "h-full rounded-full motion-safe:transition-[width] motion-safe:duration-700 motion-safe:ease-out",
            color,
          )}
          style={{ width: `${safePct}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// History card — stacked area + net line
// ---------------------------------------------------------------------------

function HistoryCard({
  summary,
  history,
}: {
  summary: NetWorthSummary;
  history: NetWorthSnapshot[];
}) {
  const sorted = useMemo(
    () =>
      [...history].sort((a, b) =>
        String(a.snapshot_date).localeCompare(String(b.snapshot_date)),
      ),
    [history],
  );

  const chartData = useMemo(
    () =>
      sorted.map((s) => ({
        // For x-axis labels: use the month + day, full year on first/last only.
        date: s.snapshot_date,
        // Stack assets up, debts as negative so they stack DOWN visually.
        liquid: s.liquid_cents / 100,
        portfolio: s.investment_cents / 100,
        debt: -s.debt_cents / 100,
        net: s.net_worth_cents / 100,
      })),
    [sorted],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">12-month trend</CardTitle>
        <CardDescription>
          Assets stack up, debts stack down. The line is your overall net worth.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {chartData.length === 0 ? (
          <EmptyHistory />
        ) : (
          <div className="h-[280px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={chartData}
                margin={{ top: 12, right: 16, left: 0, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="nw-asset-liquid" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={ASSET_COLOR} stopOpacity={0.55} />
                    <stop offset="100%" stopColor={ASSET_COLOR} stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="nw-asset-portfolio" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="#0ea5e9" stopOpacity={0.55} />
                    <stop offset="100%" stopColor="#0ea5e9" stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="nw-debt" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={DEBT_COLOR} stopOpacity={0.05} />
                    <stop offset="100%" stopColor={DEBT_COLOR} stopOpacity={0.55} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  vertical={false}
                  stroke="currentColor"
                  strokeOpacity={0.07}
                />
                <XAxis
                  dataKey="date"
                  tickFormatter={(iso: string) => formatHistoryDate(iso)}
                  fontSize={11}
                  stroke="currentColor"
                  strokeOpacity={0.4}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={28}
                />
                <YAxis
                  tickFormatter={(v: number) => formatAxisDollars(v)}
                  fontSize={11}
                  stroke="currentColor"
                  strokeOpacity={0.4}
                  tickLine={false}
                  axisLine={false}
                  width={56}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: 10,
                    border: "1px solid hsl(var(--border))",
                    fontSize: 12,
                    background: "hsl(var(--popover))",
                  }}
                  labelFormatter={(label: string) => formatHistoryDate(label, true)}
                  formatter={tooltipFormatter}
                />
                <Area
                  type="monotone"
                  dataKey="portfolio"
                  stackId="assets"
                  fill="url(#nw-asset-portfolio)"
                  stroke="#0ea5e9"
                  strokeWidth={1}
                  name="Portfolio"
                  isAnimationActive
                  animationDuration={650}
                />
                <Area
                  type="monotone"
                  dataKey="liquid"
                  stackId="assets"
                  fill="url(#nw-asset-liquid)"
                  stroke={ASSET_COLOR}
                  strokeWidth={1}
                  name="Cash & Savings"
                  isAnimationActive
                  animationDuration={650}
                />
                <Area
                  type="monotone"
                  dataKey="debt"
                  stackId="debts"
                  fill="url(#nw-debt)"
                  stroke={DEBT_COLOR}
                  strokeWidth={1}
                  name="Debt"
                  isAnimationActive
                  animationDuration={650}
                />
                <Line
                  type="monotone"
                  dataKey="net"
                  stroke={NET_COLOR}
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: NET_COLOR, stroke: "hsl(var(--background))", strokeWidth: 1.5 }}
                  activeDot={{ r: 5 }}
                  name="Net worth"
                  isAnimationActive
                  animationDuration={900}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
        {chartData.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <LegendDot color={ASSET_COLOR} label="Cash & Savings" />
            <LegendDot color="#0ea5e9" label="Portfolio" />
            <LegendDot color={DEBT_COLOR} label="Debt" />
            <LegendDot color={NET_COLOR} label="Net worth" filled />
            <span className="ml-auto text-[11px]">
              {sorted.length} snapshot{sorted.length === 1 ? "" : "s"} over{" "}
              {summary.six_month_compared_to ? "the past year" : "history"}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function LegendDot({
  color,
  label,
  filled,
}: {
  color: string;
  label: string;
  filled?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={cn(
          "size-2.5 rounded-full",
          filled ? "" : "opacity-70",
        )}
        style={{ background: color }}
      />
      {label}
    </span>
  );
}

function EmptyHistory() {
  return (
    <div className="flex flex-col items-center gap-2 py-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-muted">
        <Landmark className="size-6 text-muted-foreground" />
      </div>
      <p className="font-medium">No history yet</p>
      <p className="text-muted-foreground max-w-xs text-sm">
        Run a Plaid sync — we capture a net-worth snapshot every time.
      </p>
    </div>
  );
}

function formatHistoryDate(iso: string, full = false): string {
  try {
    const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: full ? "numeric" : undefined,
      year: full ? "numeric" : "2-digit",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

function formatAxisDollars(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(0)}k`;
  return `$${v.toFixed(0)}`;
}

function tooltipFormatter(value: number, name: string): [string, string] {
  // Recharts passes Area `debt` as a negative number (we stack down). Show
  // the absolute amount in the tooltip — readers expect "Debt: $4,084", not
  // "Debt: −$4,084" inside a tooltip cell.
  const display = name === "Debt" ? Math.abs(value) : value;
  return [
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(display),
    name,
  ];
}

// ---------------------------------------------------------------------------
// Account breakdown
// ---------------------------------------------------------------------------

function BreakdownCard({ accounts }: { accounts: NetWorthAccountRow[] }) {
  const assets = accounts.filter((a) => a.role === "asset");
  const debts = accounts.filter((a) => a.role === "debt");
  const assetTotal = assets.reduce((s, a) => s + a.balance_cents, 0);
  const debtTotal = debts.reduce((s, a) => s + a.balance_cents, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Where it&rsquo;s coming from</CardTitle>
        <CardDescription>
          Every active account, ordered by balance. Click through to manage on the Accounts page.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-2">
        <BreakdownColumn title="Assets" total={assetTotal} rows={assets} tone="asset" />
        <BreakdownColumn title="Debts" total={debtTotal} rows={debts} tone="debt" />
      </CardContent>
    </Card>
  );
}

function BreakdownColumn({
  title,
  total,
  rows,
  tone,
}: {
  title: string;
  total: number;
  rows: NetWorthAccountRow[];
  tone: "asset" | "debt";
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h4 className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
          {title}
        </h4>
        <p
          className={cn(
            "text-sm font-semibold tabular-nums",
            tone === "asset"
              ? "text-emerald-600 dark:text-emerald-300"
              : "text-rose-600 dark:text-rose-300",
          )}
        >
          {formatUsd(total)}
        </p>
      </div>
      {rows.length === 0 ? (
        <p className="text-muted-foreground rounded-lg border border-dashed border-border/60 px-3 py-4 text-center text-xs">
          No {tone === "asset" ? "assets" : "debts"} tracked.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((row, i) => (
            <li
              key={row.id}
              className="motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-400 motion-safe:[animation-fill-mode:both]"
              style={{ animationDelay: `${i * 50}ms` }}
            >
              <BreakdownRow row={row} share={total > 0 ? row.balance_cents / total : 0} tone={tone} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BreakdownRow({
  row,
  share,
  tone,
}: {
  row: NetWorthAccountRow;
  share: number;
  tone: "asset" | "debt";
}) {
  const pct = Math.round(share * 100);
  const barColor = tone === "asset" ? "bg-emerald-500" : "bg-rose-500";
  return (
    <Link
      href="/accounts"
      className="group flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-muted/40"
    >
      <AccountAvatar row={row} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className="truncate text-sm font-medium">{row.name}</p>
          <p className="shrink-0 text-sm font-semibold tabular-nums">
            {formatUsd(row.balance_cents)}
          </p>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted/60">
            <div
              className={cn(
                "h-full motion-safe:transition-[width] motion-safe:duration-700 motion-safe:ease-out",
                barColor,
              )}
              style={{ width: `${Math.max(pct, 2)}%` }}
            />
          </div>
          <span className="text-muted-foreground shrink-0 w-10 text-right text-[10px] tabular-nums">
            {pct}%
          </span>
        </div>
      </div>
    </Link>
  );
}

function AccountAvatar({ row }: { row: NetWorthAccountRow }) {
  // Per CLAUDE.md / docs/data-model.md: ``institution_logo`` is stored as
  // **bare** base64 PNG bytes (no data: URL prefix). Other components
  // (account-tile, flip-card) use ``<img>`` with the prefix prepended;
  // we follow the same convention here. ``next/image`` would treat the
  // bare base64 string as an unreachable URL and render the broken-image
  // placeholder — that was the "?" icons users saw on the Net Worth tab.
  if (row.institution_logo) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- base64 data URL stored in DB
      <img
        src={`data:image/png;base64,${row.institution_logo}`}
        alt=""
        width={36}
        height={36}
        className="size-9 shrink-0 rounded-lg bg-white object-contain p-0.5"
      />
    );
  }
  // Fallback when there's no institution branding (Cash wallet, manual
  // accounts, items missing logos). Use a meaningful icon per role
  // instead of two-letter initials — "TO" for "TOTAL CHECKING" reads as
  // garbage. ``role`` is the best signal we have at this point.
  const isCash = row.is_cash_wallet;
  const Icon = isCash ? Banknote : row.role === "debt" ? CreditCard : Landmark;
  return (
    <div
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-lg",
        isCash
          ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
          : row.role === "debt"
            ? "bg-rose-500/10 text-rose-600 dark:text-rose-300"
            : "bg-muted text-muted-foreground",
      )}
      aria-label={row.name}
    >
      <Icon className="size-4" aria-hidden />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Smart insights strip — debt payoff projection
// ---------------------------------------------------------------------------

function SmartInsightsStrip({ summary }: { summary: NetWorthSummary }) {
  const months = summary.debt_payoff_months;
  if (months == null) return null;
  const years = months >= 12 ? Math.floor(months / 12) : 0;
  const remMonths = months - years * 12;
  const niceMonths = years > 0
    ? `${years}y ${remMonths}m`
    : `${months} month${months === 1 ? "" : "s"}`;

  return (
    <Card className="border-primary/20 bg-primary/[0.04]">
      <CardContent className="flex flex-wrap items-center gap-4 p-5">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/15 text-primary">
          <Sparkles className="size-5" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">
            Projected debt payoff:{" "}
            <span className="text-primary tabular-nums">{niceMonths}</span>
          </p>
          <p className="text-muted-foreground text-xs">
            At your current trajectory ({formatUsd(summary.debt_cents)} of debt
            shrinking by your recent monthly net change). Estimate, not a
            schedule — actual payoff depends on consistent contributions.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Skeleton (loading)
// ---------------------------------------------------------------------------

function NetWorthSkeleton() {
  return (
    <div className="space-y-6 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300">
      <Card>
        <CardContent className="space-y-4 p-6">
          <div className="h-3 w-24 rounded bg-muted" />
          <div className="h-12 w-48 rounded bg-muted" />
          <div className="flex gap-2">
            <div className="h-7 w-32 rounded-full bg-muted" />
            <div className="h-7 w-32 rounded-full bg-muted" />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-3 p-6">
          <div className="h-4 w-32 rounded bg-muted" />
          <div className="h-24 w-full rounded bg-muted/60" />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-6">
          <div className="h-[260px] w-full rounded bg-muted/60" />
        </CardContent>
      </Card>
    </div>
  );
}
