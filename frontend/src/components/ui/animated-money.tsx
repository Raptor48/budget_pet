"use client";

import { useCountUp, type UseCountUpOptions } from "@/hooks/use-count-up";
import { cn } from "@/lib/utils";

interface AnimatedMoneyProps extends UseCountUpOptions {
  cents: number;
  currency?: string;
  /** Round display to whole units (no decimal cents). Defaults to false. */
  whole?: boolean;
  className?: string;
  /** Explicit element tag; defaults to `<span>`. */
  as?: "span" | "p" | "div";
}

/**
 * Smoothly animates a monetary value (cents → formatted string). Uses
 * `tabular-nums` so the glyphs don't jiggle while numbers change.
 */
export function AnimatedMoney({
  cents,
  currency = "USD",
  whole = false,
  className,
  as: Tag = "span",
  durationMs,
  decimals,
  skipInitial,
}: AnimatedMoneyProps) {
  const safeCents = Number.isFinite(cents) ? cents : 0;
  const value = useCountUp(safeCents, {
    durationMs,
    decimals,
    skipInitial,
  });
  const asNumber = Number.isFinite(value) ? value : safeCents;
  const display = formatMoney(asNumber, currency, whole);
  return (
    <Tag
      className={cn("tabular-nums", className)}
      aria-label={formatMoney(safeCents, currency, whole)}
    >
      {display}
    </Tag>
  );
}

function formatMoney(cents: number, currency: string, whole: boolean): string {
  const code = (currency || "USD").trim().toUpperCase() || "USD";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      minimumFractionDigits: whole ? 0 : 2,
      maximumFractionDigits: whole ? 0 : 2,
    }).format(cents / 100);
  } catch {
    return `$${(cents / 100).toLocaleString("en-US", {
      minimumFractionDigits: whole ? 0 : 2,
    })} ${code}`;
  }
}
