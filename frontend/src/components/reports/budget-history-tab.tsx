"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { AlertCircle, ArrowUpRight, ChevronDown, HelpCircle, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BudgetHistoryRow } from "@/types/v2";

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function formatMonthLabel(yyyymm: string): string {
  // 'YYYY-MM' → 'MMM' (e.g. "Apr"). Constructed mid-month so DST never shifts.
  const [y, m] = yyyymm.split("-").map(Number);
  if (!y || !m) return yyyymm;
  return new Date(y, m - 1, 15).toLocaleDateString("en-US", { month: "short" });
}

function formatYearTag(yyyymm: string): string {
  return yyyymm.slice(2, 4);
}

/**
 * Map ratio (actual / budget) → cell color class. Mirrors the budget tone
 * tri-color scale used in Settings → Budgets:
 *   ≤ 0.50   → lightest emerald
 *   ≤ 0.80   → mid emerald
 *   ≤ 1.00   → deeper emerald (close call but still under)
 *   ≤ 1.25   → amber (slightly over)
 *   > 1.25   → rose (significantly over)
 *   null     → neutral muted (no budget that month)
 */
function ratioColorClass(ratio: number | null): string {
  if (ratio == null) return "bg-muted/30";
  if (ratio <= 0.5) return "bg-emerald-500/20";
  if (ratio <= 0.8) return "bg-emerald-500/40";
  if (ratio <= 1.0) return "bg-emerald-500/60";
  if (ratio <= 1.25) return "bg-amber-500/60";
  return "bg-rose-500/60";
}

function ratioLabel(ratio: number | null): string {
  if (ratio == null) return "No budget set";
  return `${Math.round(ratio * 100)}% used`;
}

type Best = {
  category_id: number;
  name: string;
  color: string;
  hitRate: number; // 0..1
  monthsWithBudget: number;
};

function pickBestAndWorst(rows: BudgetHistoryRow[]): {
  best: Best[];
  worst: Best[];
} {
  // Need at least 2 months of data for a hit-rate to be meaningful.
  const enriched = rows
    .map<Best>((r) => ({
      category_id: r.category_id,
      name: r.category_name,
      color: r.category_color,
      hitRate: r.months_with_budget > 0 ? r.months_under_or_at / r.months_with_budget : 0,
      monthsWithBudget: r.months_with_budget,
    }))
    .filter((b) => b.monthsWithBudget >= 2);
  const best = [...enriched]
    .sort((a, b) => b.hitRate - a.hitRate || b.monthsWithBudget - a.monthsWithBudget)
    .slice(0, 3);
  const worst = [...enriched]
    .sort((a, b) => a.hitRate - b.hitRate || b.monthsWithBudget - a.monthsWithBudget)
    .slice(0, 3);
  return { best, worst };
}

function HeatmapCell({
  monthIso,
  ratio,
  budgetCents,
  actualCents,
  delayMs,
}: {
  monthIso: string;
  ratio: number | null;
  budgetCents: number;
  actualCents: number;
  delayMs: number;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          tabIndex={0}
          aria-label={`${monthIso} — ${ratioLabel(ratio)}`}
          className={cn(
            "size-6 sm:size-7 rounded border border-border/40 outline-none transition-all duration-200",
            "motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95 motion-safe:duration-300",
            "hover:scale-110 focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:scale-110",
            ratioColorClass(ratio),
          )}
          style={{ animationDelay: `${delayMs}ms` }}
        />
      </TooltipTrigger>
      <TooltipContent
        side="top"
        sideOffset={6}
        className="border border-border/80 bg-popover px-3 py-2 text-popover-foreground shadow-md"
      >
        <p className="text-sm font-semibold leading-none">{monthIso}</p>
        {ratio == null ? (
          <p className="mt-1.5 text-xs text-muted-foreground">No budget set</p>
        ) : (
          <p className="mt-1.5 text-xs text-muted-foreground tabular-nums leading-snug">
            <span className="font-medium text-foreground">{formatMoney(actualCents)}</span>
            {" / "}
            {formatMoney(budgetCents)}
            <span className="ml-1 font-medium text-foreground">· {Math.round(ratio * 100)}%</span>
          </p>
        )}
      </TooltipContent>
    </Tooltip>
  );
}

function BestWorstList({
  title,
  rows,
  variant,
  empty,
}: {
  title: string;
  rows: Best[];
  variant: "best" | "worst";
  empty: string;
}) {
  const Icon = variant === "best" ? Sparkles : AlertCircle;
  const iconClass =
    variant === "best"
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-rose-600 dark:text-rose-400";
  return (
    <Card className="border-border/80">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold">
          <Icon className={cn("size-4", iconClass)} aria-hidden />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-muted-foreground text-sm">{empty}</p>
        ) : (
          <ul className="space-y-2">
            {rows.map((r, i) => (
              <li
                key={r.category_id}
                className="flex items-center justify-between gap-2 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className="size-2.5 shrink-0 rounded-full border"
                    style={{ backgroundColor: r.color }}
                  />
                  <span className="truncate text-sm font-medium">{r.name}</span>
                </div>
                <div className="flex shrink-0 items-baseline gap-1 text-xs text-muted-foreground tabular-nums">
                  <span className="font-semibold text-foreground">
                    {Math.round(r.hitRate * 100)}%
                  </span>
                  <span>
                    · {r.monthsWithBudget} {r.monthsWithBudget === 1 ? "month" : "months"}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function BudgetHistoryTab({
  data,
  isLoading,
  isError,
}: {
  data: BudgetHistoryRow[] | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  const [showAll, setShowAll] = useState(false);

  const monthHeaders = useMemo(() => {
    if (!data?.[0]) return [];
    return data[0].months.map((m) => m.month);
  }, [data]);

  const { best, worst } = useMemo(
    () => pickBestAndWorst(data ?? []),
    [data],
  );

  // Sort categories alphabetically. Default-collapse to 8 rows so the page
  // doesn't explode on power users with 30 budgeted categories.
  const sortedRows = useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) => a.category_name.localeCompare(b.category_name));
  }, [data]);
  const visibleRows = showAll ? sortedRows : sortedRows.slice(0, 8);

  return (
    // ``reports-tab-stagger`` (defined in globals.css) cascades a fade-
    // in across direct children so the card-stack assembles top-down,
    // matching Net Worth / Cash Flow / Income / Expenses.
    <div className="reports-tab-stagger space-y-6">
      <Card className="hero-glow border-border/80 shadow-sm overflow-hidden">
        <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-4">
          <div>
            <CardTitle>Budget history</CardTitle>
            <CardDescription>
              How you held the line over the last 12 months. Green = under, amber = a
              little over, rose = blew it.
            </CardDescription>
          </div>
          <Button asChild variant="outline" size="sm" className="gap-1.5">
            <Link href="/settings/budgets">
              Edit budgets
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          </Button>
        </CardHeader>
        <CardContent className="space-y-6">
          {isLoading ? (
            <p className="text-muted-foreground text-sm">Loading history…</p>
          ) : isError ? (
            <p className="text-destructive text-sm">Could not load budget history.</p>
          ) : !data || data.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border/70 bg-muted/30 px-6 py-10 text-center">
              <p className="text-foreground font-medium">No budget history yet</p>
              <p className="text-muted-foreground text-sm mt-1">
                Set a budget for any category and come back next month — this page lights up
                with one cell per month per category.
              </p>
              <Button asChild className="mt-4 gap-1.5">
                <Link href="/settings/budgets">
                  Set up budgets
                  <ArrowUpRight className="size-3.5" aria-hidden />
                </Link>
              </Button>
            </div>
          ) : (
            <TooltipProvider delayDuration={150}>
              <div className="overflow-x-auto -mx-1 px-1">
                <table className="w-full text-sm border-separate border-spacing-y-1">
                  <thead>
                    <tr>
                      <th className="text-left text-xs font-medium uppercase tracking-wide text-muted-foreground pb-2 pr-3">
                        Category
                      </th>
                      {monthHeaders.map((m) => {
                        const monthShort = formatMonthLabel(m);
                        const isJanuary = m.endsWith("-01");
                        return (
                          <th
                            key={m}
                            className="text-center text-[10px] font-medium uppercase tracking-wide text-muted-foreground pb-2"
                          >
                            <span className="block leading-none">{monthShort}</span>
                            {isJanuary ? (
                              <span className="block leading-none text-muted-foreground/60 mt-0.5">
                                ’{formatYearTag(m)}
                              </span>
                            ) : null}
                          </th>
                        );
                      })}
                      <th className="text-right text-xs font-medium uppercase tracking-wide text-muted-foreground pb-2 pl-3">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span
                              tabIndex={0}
                              className="inline-flex cursor-help items-center gap-1 outline-none focus-visible:ring-2 focus-visible:ring-ring/40 rounded"
                            >
                              Hit rate
                              <HelpCircle className="size-3 opacity-60" aria-hidden />
                            </span>
                          </TooltipTrigger>
                          <TooltipContent
                            side="top"
                            sideOffset={6}
                            className="max-w-[260px] border border-border/80 bg-popover px-3 py-2 text-popover-foreground shadow-md"
                          >
                            <p className="text-sm font-semibold leading-none">Hit rate</p>
                            <p className="mt-1.5 text-xs text-muted-foreground leading-snug">
                              Months you stayed at or under budget, divided by months
                              with a budget set. <span className="font-medium text-foreground">100%</span> means
                              you nailed every month; <span className="font-medium text-foreground">0%</span> means
                              you went over every time.
                            </p>
                          </TooltipContent>
                        </Tooltip>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row, rowIdx) => {
                      const hitRate =
                        row.months_with_budget > 0
                          ? row.months_under_or_at / row.months_with_budget
                          : null;
                      return (
                        <tr
                          key={row.category_id}
                          className="motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-left-1 motion-safe:duration-300"
                          style={{ animationDelay: `${Math.min(rowIdx, 12) * 30}ms` }}
                        >
                          <td className="py-1 pr-3">
                            <div className="flex min-w-0 items-center gap-2">
                              <span
                                className="size-2.5 shrink-0 rounded-full border"
                                style={{ backgroundColor: row.category_color }}
                              />
                              <span className="truncate font-medium">{row.category_name}</span>
                            </div>
                          </td>
                          {row.months.map((cell, colIdx) => (
                            <td key={cell.month} className="py-1 px-0.5 text-center">
                              <HeatmapCell
                                monthIso={cell.month}
                                ratio={cell.ratio}
                                budgetCents={cell.budget_cents}
                                actualCents={cell.actual_cents}
                                delayMs={Math.min(rowIdx, 12) * 30 + Math.min(colIdx, 12) * 12}
                              />
                            </td>
                          ))}
                          <td className="py-1 pl-3 text-right tabular-nums text-muted-foreground">
                            {hitRate == null ? (
                              "—"
                            ) : (
                              <>
                                <span className="font-semibold text-foreground">
                                  {Math.round(hitRate * 100)}%
                                </span>
                                <span className="ml-1 text-xs">
                                  ({row.months_under_or_at}/{row.months_with_budget})
                                </span>
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {sortedRows.length > 8 ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="mx-auto block text-muted-foreground hover:text-foreground"
                  onClick={() => setShowAll((v) => !v)}
                >
                  <ChevronDown
                    className={cn("inline size-3.5 mr-1 transition-transform", showAll && "rotate-180")}
                    aria-hidden
                  />
                  {showAll ? "Show top 8" : `Show all ${sortedRows.length} categories`}
                </Button>
              ) : null}

              {/* Inline color legend */}
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground border-t border-border/40 pt-4">
                <span className="font-medium uppercase tracking-wide">Legend:</span>
                <span className="flex items-center gap-1.5">
                  <span className="size-3 rounded bg-emerald-500/20 border border-border/40" />
                  &lt; 50%
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-3 rounded bg-emerald-500/40 border border-border/40" />
                  50–80%
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-3 rounded bg-emerald-500/60 border border-border/40" />
                  80–100%
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-3 rounded bg-amber-500/60 border border-border/40" />
                  100–125%
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-3 rounded bg-rose-500/60 border border-border/40" />
                  Over 125%
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-3 rounded bg-muted/30 border border-border/40" />
                  No budget
                </span>
              </div>
            </TooltipProvider>
          )}
        </CardContent>
      </Card>

      {data && data.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2">
          <BestWorstList
            title="Most consistent"
            rows={best}
            variant="best"
            empty="Need at least 2 months with a budget to rank consistency."
          />
          <BestWorstList
            title="Most overspent"
            rows={worst}
            variant="worst"
            empty="Nothing to flag yet — set budgets and check back next month."
          />
        </div>
      ) : null}
    </div>
  );
}
