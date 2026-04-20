"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import type { CashFlowMonth } from "@/types/v2";

// ---------------------------------------------------------------------------
// Helpers (local to this chart so we don't import back from the page)
// ---------------------------------------------------------------------------

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

function shortMonthLabel(ym: string): string {
  const d = new Date(`${ym}-01T12:00:00`);
  if (Number.isNaN(d.getTime())) return ym;
  return d.toLocaleString("en-US", { month: "short" });
}

function longMonthLabel(ym: string): string {
  const d = new Date(`${ym}-01T12:00:00`);
  if (Number.isNaN(d.getTime())) return ym;
  return d.toLocaleString("en-US", { month: "long", year: "numeric" });
}

function sortCashFlowMonths(rows: CashFlowMonth[]): CashFlowMonth[] {
  return [...rows].sort((a, b) => a.month.localeCompare(b.month));
}

// ---------------------------------------------------------------------------
// Tooltip pop — absolutely positioned above the hovered column
// ---------------------------------------------------------------------------

function ColumnTooltip({ row }: { row: CashFlowMonth }) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-40 -translate-x-1/2 rounded-xl border border-border/70 bg-popover/95 px-3 py-2 shadow-xl backdrop-blur-md",
        "animate-in fade-in zoom-in-95 duration-150",
      )}
      role="tooltip"
    >
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {longMonthLabel(row.month)}
      </p>
      <div className="space-y-0.5 text-xs">
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <span className="size-2 rounded-full bg-emerald-500" />
            Income
          </span>
          <span className="font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
            {formatMoney(row.income_cents)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <span className="size-2 rounded-full bg-rose-500" />
            Expenses
          </span>
          <span className="font-semibold tabular-nums text-rose-600 dark:text-rose-400">
            {formatMoney(row.expenses_cents)}
          </span>
        </div>
        <div className="mt-1 flex items-center justify-between gap-2 border-t border-border/60 pt-1">
          <span className="text-muted-foreground">Net</span>
          <span
            className={cn(
              "font-semibold tabular-nums",
              row.net_cents >= 0
                ? "text-sky-600 dark:text-sky-400"
                : "text-amber-600 dark:text-amber-400",
            )}
          >
            {formatMoney(row.net_cents)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chart
// ---------------------------------------------------------------------------

/**
 * Grouped bar chart: income + expenses per month over N months. Hover lifts
 * the active column, dims siblings, and floats a styled tooltip above it.
 * Clicking a column propagates the selected month upward so the surrounding
 * tabs can jump to it.
 */
export function CashFlowHistoryChart({
  months,
  activeMonth,
  onSelectMonth,
}: {
  months: CashFlowMonth[];
  activeMonth?: string;
  onSelectMonth?: (month: string) => void;
}) {
  const sorted = useMemo(() => sortCashFlowMonths(months), [months]);
  const maxVal = useMemo(() => {
    let m = 1;
    for (const row of sorted) {
      m = Math.max(m, row.income_cents, row.expenses_cents);
    }
    return m;
  }, [sorted]);

  const [hoveredMonth, setHoveredMonth] = useState<string | null>(null);
  // Entrance animation: start with height 0, flip to real values after mount
  // so the CSS transition has something to interpolate.
  const [mounted, setMounted] = useState(false);
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      const id = window.requestAnimationFrame(() => setMounted(true));
      return () => window.cancelAnimationFrame(id);
    }
  }, []);

  if (!sorted.length) {
    return (
      <p className="text-muted-foreground py-6 text-center text-sm">
        No data for this range.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div
        className="relative flex h-60 items-stretch justify-between gap-1 border-b border-border/60 pt-6 sm:gap-2"
        onMouseLeave={() => setHoveredMonth(null)}
      >
        {sorted.map((row) => {
          const hIn = maxVal > 0 ? (row.income_cents / maxVal) * 100 : 0;
          const hEx = maxVal > 0 ? (row.expenses_cents / maxVal) * 100 : 0;
          const isHovered = hoveredMonth === row.month;
          const isActive = activeMonth === row.month;
          const dimmed = hoveredMonth !== null && !isHovered;

          return (
            <button
              type="button"
              key={row.month}
              onMouseEnter={() => setHoveredMonth(row.month)}
              onFocus={() => setHoveredMonth(row.month)}
              onBlur={() => setHoveredMonth(null)}
              onClick={() => onSelectMonth?.(row.month)}
              className={cn(
                "group relative flex h-full min-w-0 flex-1 cursor-pointer flex-col items-center gap-1 rounded-md px-0.5 transition-all duration-200",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60",
                isHovered && "-translate-y-0.5 scale-[1.04]",
                dimmed && "opacity-50",
                isActive && !isHovered && "ring-1 ring-primary/40",
              )}
              aria-label={`${longMonthLabel(row.month)}: income ${formatMoney(
                row.income_cents,
              )}, expenses ${formatMoney(row.expenses_cents)}`}
            >
              {/* Soft glow behind active column */}
              <span
                className={cn(
                  "pointer-events-none absolute inset-x-1 bottom-0 top-2 rounded-lg transition-opacity duration-200",
                  "bg-gradient-to-t from-primary/20 via-primary/5 to-transparent",
                  isHovered || isActive ? "opacity-100" : "opacity-0",
                )}
                aria-hidden
              />

              {isHovered && <ColumnTooltip row={row} />}

              <div className="mx-auto flex h-full w-full max-w-[2.5rem] min-h-0 flex-1 items-end justify-center gap-0.5">
                <div
                  className={cn(
                    "w-[42%] max-w-3 rounded-t-md bg-emerald-500/90 shadow-sm transition-[height,transform,filter] duration-[600ms] ease-out",
                    isHovered && "brightness-110 drop-shadow-[0_0_8px_rgba(16,185,129,0.45)]",
                  )}
                  style={{
                    height: mounted ? `${Math.max(hIn, 1)}%` : "0%",
                  }}
                />
                <div
                  className={cn(
                    "w-[42%] max-w-3 rounded-t-md bg-rose-500/90 shadow-sm transition-[height,transform,filter] duration-[600ms] ease-out",
                    isHovered && "brightness-110 drop-shadow-[0_0_8px_rgba(244,63,94,0.45)]",
                  )}
                  style={{
                    height: mounted ? `${Math.max(hEx, 1)}%` : "0%",
                  }}
                />
              </div>
              <span
                className={cn(
                  "w-full shrink-0 truncate text-center text-[10px] text-muted-foreground transition-colors sm:text-xs",
                  (isHovered || isActive) && "text-foreground font-semibold",
                )}
              >
                {shortMonthLabel(row.month)}
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <div className="flex flex-wrap items-center gap-5">
          <span className="inline-flex items-center gap-2">
            <span className="size-2.5 rounded-sm bg-emerald-500" /> Income
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="size-2.5 rounded-sm bg-rose-500" /> Expenses
          </span>
        </div>
        {onSelectMonth && (
          <span className="text-[11px] text-muted-foreground">
            Click a column to jump to that month
          </span>
        )}
      </div>
    </div>
  );
}
