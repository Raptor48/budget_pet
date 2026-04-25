"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
 * Hero-sized health-score card. Used on the Dashboard as the headline KPI; the
 * Reports tab no longer hosts a dedicated tab for financial health — this is
 * its single canonical home.
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
