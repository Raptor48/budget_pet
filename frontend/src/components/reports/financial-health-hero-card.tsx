"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { FinancialHealthScore } from "@/types/v2";

function formatRatioPercent(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function HealthMetric({
  label,
  value,
  highlight,
  delayMs = 0,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  delayMs?: number;
}) {
  return (
    <div
      className={`rounded-lg border px-4 py-3 transition-colors motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300 ${
        highlight ? "border-destructive/40 bg-destructive/5" : "border-border/60 bg-muted/20"
      }`}
      style={{ animationDelay: `${delayMs}ms` }}
    >
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className={`mt-1 font-semibold tabular-nums ${highlight ? "text-destructive" : ""}`}>
        {value}
      </p>
    </div>
  );
}

/**
 * Compact KPI-row variant. Designed to sit alongside Net Worth, Cash Flow,
 * and Insights in a single 4-column row on desktop without dwarfing them.
 *
 * Layout: a small score donut on the left, big number + status label
 * stacked next to it, and a single-line truncated advice underneath.
 * Drops the 5-metric tile grid that the hero variant ships — overview
 * surface, not details. The actionable bits the metrics drove (high
 * utilization, low savings rate) re-surface as Insights cards through
 * the existing feed.
 */
export function FinancialHealthCompactCard({
  score,
  isLoading,
  isError,
}: {
  score: FinancialHealthScore | null | undefined;
  isLoading?: boolean;
  isError?: boolean;
}) {
  return (
    <Card className="overflow-hidden gap-3">
      <CardHeader className="pb-3 border-b">
        <CardTitle className="text-base font-bold text-foreground">
          Financial health
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col pb-4">
        {isLoading ? (
          <div className="h-16 w-full animate-pulse rounded bg-muted" aria-hidden />
        ) : isError ? (
          <p className="text-destructive text-sm">Could not load health score.</p>
        ) : score ? (
          <FinancialHealthCompactBody score={score} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function FinancialHealthCompactBody({ score }: { score: FinancialHealthScore }) {
  const ringPct = Math.min(100, Math.max(0, score.score));
  const dasharray = `${(ringPct / 100) * 264} 264`;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <div
          className="relative size-14 shrink-0 motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95 motion-safe:duration-500"
          aria-hidden
        >
          <svg viewBox="0 0 100 100" className="size-full -rotate-90">
            <circle cx="50" cy="50" r="42" fill="none" className="stroke-muted" strokeWidth="12" />
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke={score.color}
              strokeWidth="12"
              strokeLinecap="round"
              strokeDasharray={dasharray}
              className="transition-all duration-700"
            />
          </svg>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-1.5 leading-none">
            <span className="text-2xl font-bold tabular-nums">{score.score}</span>
            <span className="text-xs text-muted-foreground">/ 100</span>
          </div>
          <p
            className={cn("mt-1 text-sm font-semibold leading-tight")}
            style={{ color: score.color }}
          >
            {score.label}
          </p>
        </div>
      </div>
      {score.advice ? (
        <p className="text-muted-foreground text-xs leading-snug line-clamp-2">
          {score.advice}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Hero-sized health-score card. Used on standalone Health pages or when this
 * is the headline KPI of the screen. The Dashboard now opts for the compact
 * variant above to keep the at-a-glance row balanced.
 *
 * Animations match the Cash Flow Reports tab: cards fade-in + slide-up, donut
 * dasharray tweens between scores, and metric tiles stagger in.
 */
export function FinancialHealthHeroCard({
  score,
  isLoading,
  isError,
}: {
  score: FinancialHealthScore | null | undefined;
  isLoading?: boolean;
  isError?: boolean;
}) {
  return (
    <Card className="hero-glow overflow-hidden border-border/80 shadow-sm">
      <CardHeader>
        <CardTitle>Financial health</CardTitle>
        <CardDescription>
          Holistic score from debt, utilization, savings, and safety buffer.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-8">
        {isLoading ? (
          <p className="text-muted-foreground text-sm">Loading health score…</p>
        ) : isError ? (
          <p className="text-destructive text-sm">Could not load financial health.</p>
        ) : score ? (
          <FinancialHealthHeroBody score={score} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function FinancialHealthHeroBody({ score }: { score: FinancialHealthScore }) {
  const ringPct = Math.min(100, Math.max(0, score.score));
  return (
    <div className="space-y-8">
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-center sm:gap-10">
        <div className="relative size-36 motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95 motion-safe:duration-500">
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
              className="transition-all duration-700"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-3xl font-bold tabular-nums">{score.score}</span>
            <span className="text-xs text-muted-foreground">/ 100</span>
          </div>
        </div>
        <div className="text-center sm:text-left space-y-1 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-500">
          <p className="text-lg font-semibold" style={{ color: score.color }}>
            {score.label}
          </p>
          <p className="text-muted-foreground text-sm max-w-md leading-relaxed">{score.advice}</p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <HealthMetric label="Debt-to-income" value={formatRatioPercent(score.debt_to_income)} delayMs={0} />
        <HealthMetric
          label="Credit utilization"
          value={formatRatioPercent(score.credit_utilization)}
          delayMs={50}
        />
        <HealthMetric label="Savings rate" value={formatRatioPercent(score.savings_rate)} delayMs={100} />
        <HealthMetric
          label="Emergency fund"
          value={
            score.emergency_fund_months != null
              ? `${score.emergency_fund_months.toFixed(1)} mo`
              : "—"
          }
          delayMs={150}
        />
        <HealthMetric
          label="Overdue accounts"
          value={score.has_overdue ? "Yes — action needed" : "None"}
          highlight={score.has_overdue}
          delayMs={200}
        />
      </div>
    </div>
  );
}
