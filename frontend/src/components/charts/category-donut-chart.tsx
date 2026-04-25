"use client";

/**
 * Shared interactive donut chart for spending by category.
 * Used in: Dashboard (page.tsx) and Reports (reports/page.tsx).
 */

import { useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Sector, Tooltip } from "recharts";
import { cn } from "@/lib/utils";
import type { CategorySpend } from "@/types/v2";

export const CATEGORY_COLORS = [
  "#6366f1", "#22c55e", "#f59e0b", "#ec4899",
  "#06b6d4", "#a855f7", "#14b8a6", "#f97316",
  "#ef4444", "#84cc16", "#0ea5e9", "#e879f9",
];

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

/**
 * Expanded active slice: grows outward, sports a soft drop-shadow in the
 * slice color, and gains a pulsating outer ring rendered with SVG
 * `<animate>` — no JS animation frames involved. Falls back to a static
 * ring for `prefers-reduced-motion` users via the global guard in
 * `globals.css`.
 */
function ActiveShape(props: Record<string, unknown>) {
  const { cx, cy, innerRadius, outerRadius, startAngle, endAngle, fill } = props as {
    cx: number; cy: number; innerRadius: number; outerRadius: number;
    startAngle: number; endAngle: number; fill: string;
  };
  return (
    <g>
      {/* Main slice, slightly enlarged with a colored glow */}
      <Sector
        cx={cx}
        cy={cy}
        innerRadius={innerRadius}
        outerRadius={outerRadius + 8}
        startAngle={startAngle}
        endAngle={endAngle}
        fill={fill}
        style={{
          filter: `drop-shadow(0 0 6px ${fill})`,
        }}
      />
      {/* Outer pulsating ring */}
      <Sector
        cx={cx}
        cy={cy}
        innerRadius={outerRadius + 12}
        outerRadius={outerRadius + 15}
        startAngle={startAngle}
        endAngle={endAngle}
        fill={fill}
      >
        <animate
          attributeName="opacity"
          values="0.35;0.85;0.35"
          dur="1.6s"
          repeatCount="indefinite"
        />
      </Sector>
    </g>
  );
}

// ---------------------------------------------------------------------------
// Donut chart (chart only — no legend)
// ---------------------------------------------------------------------------
export function CategoryDonutChart({
  data,
  hoveredIdx,
  lockedIdx,
  onHover,
  onLock,
  onSliceClick,
  totalCents: totalCentsOverride,
  innerRadius = 72,
  outerRadius = 108,
  height = 260,
}: {
  data: CategorySpend[];
  hoveredIdx: number | null;
  lockedIdx: number | null;
  onHover: (i: number | null) => void;
  onLock: (i: number | null) => void;
  /**
   * Optional drilldown callback for Reports' Focus-mode. When defined, clicking
   * a slice dispatches here instead of toggling lock. The caller is expected to
   * change the query (rollup/parent_category_id) in response.
   */
  onSliceClick?: (row: CategorySpend, index: number) => void;
  /**
   * Optional override for the center-overlay "Total". Pass this when `data` has
   * been visually trimmed (e.g. tail merged into an "Other" bucket) but you want
   * the centerpiece to reflect the full, un-trimmed month total — keeping the
   * Dashboard donut consistent with Reports → Cash Flow expenses.
   */
  totalCents?: number;
  innerRadius?: number;
  outerRadius?: number;
  height?: number;
}) {
  const activeIdx = hoveredIdx ?? lockedIdx ?? undefined;
  const totalCents =
    totalCentsOverride ?? data.reduce((s, r) => s + r.amount_cents, 0);
  const displayRow = activeIdx != null ? data[activeIdx] : null;
  const pieData = data.map((r) => ({ name: r.category_name, value: r.amount_cents }));

  return (
    <div className="relative w-full">
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={pieData}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={innerRadius}
            outerRadius={outerRadius}
            paddingAngle={2}
            animationBegin={0}
            animationDuration={800}
            animationEasing="ease-out"
            {...({ activeIndex: activeIdx, activeShape: ActiveShape } as unknown as object)}
            onMouseEnter={(_, i) => onHover(i)}
            onMouseLeave={() => onHover(null)}
            onClick={(_, i) => {
              if (onSliceClick && data[i]) {
                onSliceClick(data[i], i);
              } else {
                onLock(lockedIdx === i ? null : i);
              }
            }}
            style={{ cursor: "pointer", outline: "none" }}
          >
            {pieData.map((_, i) => (
              <Cell
                key={i}
                fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]}
                opacity={activeIdx != null && activeIdx !== i ? 0.45 : 1}
                style={{ transition: "opacity 150ms" }}
              />
            ))}
          </Pie>
          <Tooltip
            formatter={(value: number, name: string) => [formatMoney(value), name]}
            contentStyle={{
              borderRadius: 10,
              border: "1px solid hsl(var(--border))",
              fontSize: 13,
            }}
            itemStyle={{ padding: "2px 0" }}
          />
        </PieChart>
      </ResponsiveContainer>

      {/* Center overlay */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div className="text-center px-2">
          {displayRow ? (
            <>
              <p className="text-lg font-bold tabular-nums leading-tight">
                {formatMoney(displayRow.amount_cents)}
              </p>
              <p className="text-[11px] text-muted-foreground leading-snug mt-0.5 max-w-[7rem] break-words">
                {displayRow.category_name}
              </p>
              <p className="text-xs text-muted-foreground tabular-nums">
                {displayRow.percent.toFixed(1)}%
              </p>
            </>
          ) : (
            <>
              <p className="text-xl font-bold tabular-nums">{formatMoney(totalCents)}</p>
              <p className="text-xs text-muted-foreground">Total</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interactive legend
// ---------------------------------------------------------------------------
export function CategoryLegend({
  data,
  hoveredIdx,
  lockedIdx,
  onHover,
  onLock,
  onSliceClick,
  maxHeight = 280,
}: {
  data: CategorySpend[];
  hoveredIdx: number | null;
  lockedIdx: number | null;
  onHover: (i: number | null) => void;
  onLock: (i: number | null) => void;
  /** If provided, a click on a row triggers drilldown instead of locking. */
  onSliceClick?: (row: CategorySpend, index: number) => void;
  maxHeight?: number;
}) {
  const activeIdx = hoveredIdx ?? lockedIdx;
  return (
    <div className="flex flex-col justify-start gap-0.5 overflow-auto pr-1" style={{ maxHeight }}>
      {data.map((row, i) => {
        const isActive = activeIdx === i;
        const isDimmed = activeIdx != null && !isActive;
        const hasChildren = (row.children_count ?? 0) > 0;
        const canDrill = Boolean(onSliceClick) && hasChildren;
        return (
          <button
            key={`${row.category_name}-${i}`}
            type="button"
            className={cn(
              "flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm transition-colors",
              isActive && "bg-muted",
              !isActive && "hover:bg-muted/50",
              isDimmed && "opacity-40",
            )}
            onMouseEnter={() => onHover(i)}
            onMouseLeave={() => onHover(null)}
            onClick={() => {
              if (onSliceClick) {
                onSliceClick(row, i);
              } else {
                onLock(lockedIdx === i ? null : i);
              }
            }}
            title={canDrill ? `Open ${row.category_name} (${row.children_count} subcategories)` : undefined}
          >
            <span
              className={cn(
                "size-2.5 shrink-0 rounded-full transition-transform",
                isActive && "scale-125",
              )}
              style={{ backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}
            />
            {/* Cap the category name's growth so it doesn't push the amounts
                all the way to the right edge of the card. Names that overflow
                still truncate gracefully. */}
            <span className="min-w-0 max-w-[10rem] flex-1 truncate font-medium">
              {row.category_name}
            </span>
            {canDrill ? (
              <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                {row.children_count}×
              </span>
            ) : null}
            <span className="shrink-0 tabular-nums text-muted-foreground">
              {formatMoney(row.amount_cents)}
            </span>
            <span className="w-12 shrink-0 text-right tabular-nums text-muted-foreground text-xs">
              {row.percent.toFixed(1)}%
            </span>
          </button>
        );
      })}
      {lockedIdx != null && (
        <button
          type="button"
          onClick={() => onLock(null)}
          className="mt-2 text-xs text-primary hover:underline text-left px-3"
        >
          Clear selection ×
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Self-contained widget (manages own hover/lock state) — for Dashboard
// ---------------------------------------------------------------------------

/**
 * Collapse the long tail of categories into a single synthetic "Other" row so
 * the dashboard donut stays readable while still summing to the full month
 * total (the centerpiece number must match Reports → Cash Flow expenses).
 *
 * Contract:
 *   - Input rows already come from the backend sorted by amount desc.
 *   - We keep the first `maxSlices - 1` rows untouched.
 *   - Everything else is folded into one `category_id: null` row labeled "Other".
 *   - Percent for the "Other" row is recomputed against the full total so the
 *     legend shares add up to ~100% even after the fold.
 *   - The total returned is the un-folded sum of the input — that's what the
 *     chart displays in its center overlay.
 */
function collapseTailIntoOther(
  data: CategorySpend[],
  maxSlices: number,
): { displayData: CategorySpend[]; totalCents: number } {
  const totalCents = data.reduce((s, r) => s + r.amount_cents, 0);

  if (data.length <= maxSlices) {
    return { displayData: data, totalCents };
  }

  const head = data.slice(0, maxSlices - 1);
  const tail = data.slice(maxSlices - 1);
  const tailAmount = tail.reduce((s, r) => s + r.amount_cents, 0);
  const tailPercent =
    totalCents > 0 ? (tailAmount / totalCents) * 100 : 0;

  const otherRow: CategorySpend = {
    category_id: null,
    category_name: `Other (${tail.length})`,
    amount_cents: tailAmount,
    percent: tailPercent,
    bucket_key: "other",
    parent_category_id: null,
    children_count: 0,
  };

  return { displayData: [...head, otherRow], totalCents };
}

export function CategoryDonutWidget({
  data,
  maxSlices = 12,
}: {
  data: CategorySpend[];
  /** Visual cap on slices; the (maxSlices-1)+1 rows shown roll the rest into "Other". */
  maxSlices?: number;
}) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [lockedIdx, setLockedIdx] = useState<number | null>(null);

  if (data.length === 0) {
    return (
      <p className="text-muted-foreground text-sm py-6 text-center">No spending data this month.</p>
    );
  }

  const { displayData, totalCents } = collapseTailIntoOther(data, maxSlices);

  return (
    <div className="grid gap-4 sm:grid-cols-[240px_1fr]">
      <CategoryDonutChart
        data={displayData}
        totalCents={totalCents}
        hoveredIdx={hoveredIdx}
        lockedIdx={lockedIdx}
        onHover={setHoveredIdx}
        onLock={setLockedIdx}
        innerRadius={60}
        outerRadius={96}
        height={240}
      />
      <CategoryLegend
        data={displayData}
        hoveredIdx={hoveredIdx}
        lockedIdx={lockedIdx}
        onHover={setHoveredIdx}
        onLock={setLockedIdx}
        maxHeight={240}
      />
    </div>
  );
}
