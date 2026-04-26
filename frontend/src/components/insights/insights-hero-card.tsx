"use client";

import Link from "next/link";
import { Activity, ArrowUpRight } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { FinancialHealthScore } from "@/types/v2";
import { cn } from "@/lib/utils";

/**
 * Hero block at the top of the Insights page. Combines the score donut,
 * the headline label, the one-line advice from the backend, and a quick
 * link into the Reports → Health tab. Lives next to the per-card
 * ``InsightGroupCard`` rather than reusing it because:
 *
 *   - The score is rich structured data (number + ring + advice), not
 *     a generic ``summary`` string.
 *   - It's intentionally double-height vs other cards — the Insights
 *     page treats financial_health as the headline.
 *
 * The card hides itself when the score is unavailable; the rest of the
 * feed still renders.
 */
export function InsightsHeroCard({
  score,
  isLoading,
  isError,
}: {
  score: FinancialHealthScore | null | undefined;
  isLoading?: boolean;
  isError?: boolean;
}) {
  if (isError) return null;

  return (
    <Card className="hero-glow overflow-hidden border-border/80">
      <CardContent className="p-6">
        {isLoading ? (
          <div className="h-32 w-full animate-pulse rounded bg-muted" aria-hidden />
        ) : score ? (
          <HeroBody score={score} />
        ) : (
          <p className="text-muted-foreground text-sm">No health score yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function HeroBody({ score }: { score: FinancialHealthScore }) {
  const ringPct = Math.min(100, Math.max(0, score.score));
  // Circle is r=42 → circumference = 2πr ≈ 264. Tween dasharray for the fill.
  const dasharray = `${(ringPct / 100) * 264} 264`;
  return (
    <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:gap-7">
      <div
        className={cn(
          "relative size-24 shrink-0 motion-safe:animate-in",
          "motion-safe:fade-in motion-safe:zoom-in-95 motion-safe:duration-500",
        )}
        aria-hidden
      >
        <svg viewBox="0 0 100 100" className="size-full -rotate-90">
          <circle cx="50" cy="50" r="42" fill="none" className="stroke-muted" strokeWidth="11" />
          <circle
            cx="50"
            cy="50"
            r="42"
            fill="none"
            stroke={score.color}
            strokeWidth="11"
            strokeLinecap="round"
            strokeDasharray={dasharray}
            className="transition-all duration-700"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold tabular-nums leading-none">
            {score.score}
          </span>
          <span className="text-muted-foreground mt-0.5 text-[10px]">/ 100</span>
        </div>
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center gap-2">
          <Activity className="text-muted-foreground size-3.5" aria-hidden />
          <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
            Financial health
          </p>
        </div>
        <p className="text-xl font-semibold leading-tight" style={{ color: score.color }}>
          {score.label}
        </p>
        {score.advice && (
          <p className="text-muted-foreground max-w-prose text-sm leading-relaxed">
            {score.advice}
          </p>
        )}
      </div>
      <Button asChild variant="outline" size="sm" className="shrink-0 self-start sm:self-center">
        <Link href="/reports?tab=health">
          Open report
          <ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
      </Button>
    </div>
  );
}
