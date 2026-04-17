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

/** Expanded active slice: grows outward + faint outer ring. */
function ActiveShape(props: Record<string, unknown>) {
  const { cx, cy, innerRadius, outerRadius, startAngle, endAngle, fill } = props as {
    cx: number; cy: number; innerRadius: number; outerRadius: number;
    startAngle: number; endAngle: number; fill: string;
  };
  return (
    <g>
      <Sector
        cx={cx} cy={cy}
        innerRadius={innerRadius}
        outerRadius={outerRadius + 8}
        startAngle={startAngle}
        endAngle={endAngle}
        fill={fill}
      />
      <Sector
        cx={cx} cy={cy}
        innerRadius={outerRadius + 12}
        outerRadius={outerRadius + 15}
        startAngle={startAngle}
        endAngle={endAngle}
        fill={fill}
        opacity={0.35}
      />
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
  innerRadius = 72,
  outerRadius = 108,
  height = 260,
}: {
  data: CategorySpend[];
  hoveredIdx: number | null;
  lockedIdx: number | null;
  onHover: (i: number | null) => void;
  onLock: (i: number | null) => void;
  innerRadius?: number;
  outerRadius?: number;
  height?: number;
}) {
  const activeIdx = hoveredIdx ?? lockedIdx ?? undefined;
  const totalCents = data.reduce((s, r) => s + r.amount_cents, 0);
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
            animationDuration={700}
            {...({ activeIndex: activeIdx, activeShape: ActiveShape } as unknown as object)}
            onMouseEnter={(_, i) => onHover(i)}
            onMouseLeave={() => onHover(null)}
            onClick={(_, i) => onLock(lockedIdx === i ? null : i)}
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
  maxHeight = 280,
}: {
  data: CategorySpend[];
  hoveredIdx: number | null;
  lockedIdx: number | null;
  onHover: (i: number | null) => void;
  onLock: (i: number | null) => void;
  maxHeight?: number;
}) {
  const activeIdx = hoveredIdx ?? lockedIdx;
  return (
    <div className="flex flex-col justify-center gap-0.5 overflow-auto pr-1" style={{ maxHeight }}>
      {data.map((row, i) => {
        const isActive = activeIdx === i;
        const isDimmed = activeIdx != null && !isActive;
        return (
          <button
            key={`${row.category_name}-${i}`}
            type="button"
            className={cn(
              "flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left text-sm transition-colors",
              isActive && "bg-muted",
              !isActive && "hover:bg-muted/50",
              isDimmed && "opacity-40",
            )}
            onMouseEnter={() => onHover(i)}
            onMouseLeave={() => onHover(null)}
            onClick={() => onLock(lockedIdx === i ? null : i)}
          >
            <span
              className={cn(
                "size-2.5 shrink-0 rounded-full transition-transform",
                isActive && "scale-125",
              )}
              style={{ backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }}
            />
            <span className="min-w-0 flex-1 truncate font-medium">{row.category_name}</span>
            <span className="shrink-0 tabular-nums text-muted-foreground">
              {formatMoney(row.amount_cents)}
            </span>
            <span className="w-10 shrink-0 text-right tabular-nums text-muted-foreground text-xs">
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
export function CategoryDonutWidget({ data }: { data: CategorySpend[] }) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [lockedIdx, setLockedIdx] = useState<number | null>(null);

  if (data.length === 0) {
    return (
      <p className="text-muted-foreground text-sm py-6 text-center">No spending data this month.</p>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-[240px_1fr]">
      <CategoryDonutChart
        data={data}
        hoveredIdx={hoveredIdx}
        lockedIdx={lockedIdx}
        onHover={setHoveredIdx}
        onLock={setLockedIdx}
        innerRadius={60}
        outerRadius={96}
        height={240}
      />
      <CategoryLegend
        data={data}
        hoveredIdx={hoveredIdx}
        lockedIdx={lockedIdx}
        onHover={setHoveredIdx}
        onLock={setLockedIdx}
        maxHeight={240}
      />
    </div>
  );
}
