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

  const toneClass =
    tone === "good"
      ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
      : tone === "warn"
        ? "border-orange-500/60 bg-orange-500/15 text-orange-800 dark:text-orange-200"
        : "border-border bg-muted text-muted-foreground";

  const prefix = tone === "good" ? "Saved" : tone === "warn" ? "Heads up" : "Change";
  const verb = up ? "up" : "down";

  return (
    <Badge
      variant="outline"
      className={cn("gap-1 whitespace-nowrap", toneClass, className)}
      title={`Last charge ${verb} ${Math.abs(pct).toFixed(1)}% vs average`}
    >
      <Icon className="size-3" aria-hidden />
      {compact ? (
        <span>
          {up ? "+" : "−"}
          {Math.abs(rounded)}%
        </span>
      ) : (
        <span>
          {prefix} {up ? "+" : "−"}
          {Math.abs(rounded)}%
        </span>
      )}
    </Badge>
  );
}
