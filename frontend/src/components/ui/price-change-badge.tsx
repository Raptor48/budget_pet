"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { TrendingDown, TrendingUp } from "lucide-react";

/**
 * Renders a color-coded pill for `RecurringStream.price_change_pct`.
 *
 * Price change sign semantics (see `web/recurring/repo.py::upsert_streams`):
 *   positive pct → last charge is HIGHER than the long-term average;
 *   negative pct → last charge is LOWER.
 *
 * The *user-perceived* goodness depends on the stream's direction:
 *   - outflow (bills, subscriptions): lower is GOOD (green), higher is a WARNING (orange).
 *   - inflow  (salary, refunds):      higher is GOOD (green), lower is a WARNING (amber).
 */
export type PriceChangeTone = "good" | "warn" | "neutral";

export function classifyPriceChange(
  pct: number | null | undefined,
  direction: "inflow" | "outflow" | string,
): PriceChangeTone {
  if (pct == null || !Number.isFinite(pct) || pct === 0) return "neutral";
  const isOutflow = direction === "outflow";
  if (pct > 0) return isOutflow ? "warn" : "good";
  return isOutflow ? "good" : "warn";
}

export function PriceChangeBadge({
  pct,
  direction,
  className,
  compact = false,
}: {
  pct: number | null | undefined;
  direction: "inflow" | "outflow" | string;
  className?: string;
  /** Compact removes the verbose prefix and shortens the icon padding. */
  compact?: boolean;
}) {
  if (pct == null || !Number.isFinite(pct)) return null;
  const rounded = Math.round(pct);
  const tone = classifyPriceChange(pct, direction);
  const up = pct > 0;
  const Icon = up ? TrendingUp : TrendingDown;

  // Muted chip frame (neutral border + bg) keeps the chip from competing
  // with other colored elements in the row. The tone goes into the icon
  // and percentage text only — that's enough signal to read direction at
  // a glance, without painting a third saturated chip into the line.
  const accentClass =
    tone === "good"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "warn"
        ? "text-orange-600 dark:text-orange-400"
        : "text-muted-foreground";

  const prefix = tone === "good" ? "Saved" : tone === "warn" ? "Heads up" : "Change";
  const verb = up ? "up" : "down";

  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1 whitespace-nowrap border-border/60 bg-muted/40 text-muted-foreground",
        className,
      )}
      title={`Last charge ${verb} ${Math.abs(pct).toFixed(1)}% vs average`}
    >
      <Icon className={cn("size-3", accentClass)} aria-hidden />
      {compact ? (
        <span className={cn("tabular-nums font-medium", accentClass)}>
          {up ? "+" : "−"}
          {Math.abs(rounded)}%
        </span>
      ) : (
        <span>
          <span className="text-muted-foreground">{prefix} </span>
          <span className={cn("tabular-nums font-medium", accentClass)}>
            {up ? "+" : "−"}
            {Math.abs(rounded)}%
          </span>
        </span>
      )}
    </Badge>
  );
}
