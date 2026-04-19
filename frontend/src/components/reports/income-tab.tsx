"use client";

/**
 * Income tab — family income for the selected month, split per person, with
 * each person's total broken down by the category that produced it.
 *
 * "Income" is defined by the family-wide `is_income` flag on categories and
 * computed by `/api/reports/income`. This component is intentionally
 * presentation-only: the underlying predicate is authoritative on the
 * backend and shared with Cash Flow / Financial Health.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Loader2,
  Settings2,
  TrendingUp,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MonthYearPicker } from "@/components/ui/month-year-picker";
import { reportsApi, transactionsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { IncomeByUser, IncomeSource, Transaction } from "@/types/v2";

import { IncomeCategoriesDialog } from "./income-categories-dialog";
import { IncomeMathHelp } from "./reports-math-help";

interface Props {
  month: string;
  onMonthChange: (month: string) => void;
}

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

function initial(name: string): string {
  const trimmed = name.trim();
  return trimmed ? trimmed[0]!.toUpperCase() : "?";
}

function transactionLabel(tx: Transaction): string {
  return (
    tx.display_title ||
    tx.merchant_name ||
    tx.name ||
    "Untitled"
  );
}

function formatShortDate(iso: string): string {
  // Parse as local noon to avoid TZ-driven off-by-one on the client.
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function IncomeTab({ month, onMonthChange }: Props) {
  const [dialogOpen, setDialogOpen] = useState(false);

  const incomeQuery = useQuery({
    queryKey: ["reports", "income", month],
    queryFn: () => reportsApi.getIncome(month),
  });

  const data = incomeQuery.data;

  return (
    <Card className="border-border/80 shadow-sm">
      <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="size-5 text-emerald-600" aria-hidden />
            Income by person
            <IncomeMathHelp />
          </CardTitle>
          <CardDescription>
            Uses your family-wide income-category settings. Toggle which
            categories count via “Manage income categories”.
          </CardDescription>
        </div>
        <div className="flex items-end gap-3">
          <Button
            variant="outline"
            size="sm"
            className="gap-1"
            onClick={() => setDialogOpen(true)}
          >
            <Settings2 className="size-4" aria-hidden />
            Manage income categories
          </Button>
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Month</span>
            <MonthYearPicker value={month} onChange={onMonthChange} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {incomeQuery.isLoading && (
          <p className="text-muted-foreground text-sm">Loading income…</p>
        )}
        {incomeQuery.isError && (
          <p className="text-destructive text-sm">
            {(incomeQuery.error as Error)?.message || "Failed to load income."}
          </p>
        )}
        {data && (
          <>
            <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 px-5 py-4">
              <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
                Family income
              </p>
              <p className="text-3xl font-semibold tabular-nums text-emerald-700 dark:text-emerald-400">
                {formatMoney(data.total_cents)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {data.users.length} contributor{data.users.length === 1 ? "" : "s"} in {data.month}
              </p>
            </div>

            {data.users.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <div className="flex size-12 items-center justify-center rounded-full bg-muted">
                  <TrendingUp className="size-6 text-muted-foreground" aria-hidden />
                </div>
                <p className="font-medium">No income recorded this month</p>
                <p className="text-muted-foreground max-w-sm text-sm">
                  If something is missing, check that its category is marked as income.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-1 gap-1"
                  onClick={() => setDialogOpen(true)}
                >
                  <Settings2 className="size-4" aria-hidden />
                  Manage income categories
                </Button>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {data.users.map((user) => (
                  <PersonCard
                    key={user.user_id ?? `unassigned-${user.username}`}
                    user={user}
                    total={data.total_cents}
                    month={data.month}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </CardContent>

      <IncomeCategoriesDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </Card>
  );
}

const COLLAPSED_SOURCES = 3;

function PersonCard({
  user,
  total,
  month,
}: {
  user: IncomeByUser;
  total: number;
  month: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const share = total > 0 ? (user.amount_cents / total) * 100 : 0;
  const sources = showAll ? user.sources : user.sources.slice(0, COLLAPSED_SOURCES);
  const hidden = user.sources.length - COLLAPSED_SOURCES;

  return (
    <div className="rounded-xl border border-border/70 bg-card px-4 py-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
              user.user_id == null
                ? "bg-muted text-muted-foreground"
                : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
            )}
            aria-hidden
          >
            {initial(user.username)}
          </div>
          <div className="min-w-0">
            <p className="truncate font-medium">{user.username}</p>
            <p className="text-xs text-muted-foreground">
              {share.toFixed(1)}% of family income
            </p>
          </div>
        </div>
        <p className="shrink-0 text-lg font-semibold tabular-nums text-emerald-700 dark:text-emerald-400">
          {formatMoney(user.amount_cents)}
        </p>
      </div>

      {user.sources.length > 0 && (
        <ul className="mt-4 divide-y divide-border/40 rounded-lg border border-border/40">
          {sources.map((src) => (
            <IncomeSourceRow
              key={`${src.category_id ?? "none"}-${src.category_name}`}
              source={src}
              userId={user.user_id}
              month={month}
            />
          ))}
        </ul>
      )}

      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          {showAll ? (
            <>
              <ChevronUp className="size-3.5" aria-hidden />
              Show less
            </>
          ) : (
            <>
              <ChevronDown className="size-3.5" aria-hidden />
              Show {hidden} more
            </>
          )}
        </button>
      )}
    </div>
  );
}

/**
 * A single income source (one category inside a person's card). Clicking the
 * row reveals the underlying transactions fetched via `transactionsApi.list`.
 *
 * Drilldown is intentionally disabled for unassigned-owner rows (user_id ==
 * null) and for rows with an unknown category_id (shouldn't normally happen,
 * but harmless to guard) — the transactions endpoint can't target "no owner"
 * cleanly, and a category-less filter would leak non-income rows.
 */
function IncomeSourceRow({
  source,
  userId,
  month,
}: {
  source: IncomeSource;
  userId: number | null;
  month: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const drillable = userId != null && source.category_id != null;

  const txQuery = useQuery({
    queryKey: [
      "reports",
      "income",
      "transactions",
      month,
      userId,
      source.category_id,
    ],
    queryFn: () =>
      transactionsApi.list({
        month,
        user_id: userId ?? undefined,
        category_id: source.category_id ?? undefined,
        limit: 200,
      }),
    enabled: drillable && expanded,
    staleTime: 30_000,
  });

  return (
    <li className="text-sm">
      <button
        type="button"
        onClick={() => drillable && setExpanded((v) => !v)}
        disabled={!drillable}
        className={cn(
          "flex w-full items-center justify-between gap-2 px-3 py-2 text-left",
          drillable ? "cursor-pointer hover:bg-muted/40" : "cursor-default",
        )}
        aria-expanded={drillable ? expanded : undefined}
      >
        <span className="inline-flex min-w-0 items-center gap-2">
          {drillable ? (
            <ChevronRight
              className={cn(
                "size-3.5 shrink-0 text-muted-foreground transition-transform",
                expanded ? "rotate-90" : undefined,
              )}
              aria-hidden
            />
          ) : (
            <span className="size-3.5 shrink-0" aria-hidden />
          )}
          <span
            className="size-2 shrink-0 rounded-full"
            style={{ backgroundColor: source.color || "#64748b" }}
          />
          <span className="truncate">{source.category_name}</span>
          <span className="shrink-0 text-[11px] text-muted-foreground">
            ×{source.transaction_count}
          </span>
        </span>
        <span className="shrink-0 tabular-nums text-muted-foreground">
          {formatMoney(source.amount_cents)}
        </span>
      </button>

      {expanded && drillable && (
        <div className="border-t border-border/40 bg-muted/10 px-3 py-2">
          {txQuery.isLoading && (
            <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              Loading transactions…
            </div>
          )}
          {txQuery.isError && (
            <p className="py-2 text-xs text-destructive">
              {(txQuery.error as Error)?.message || "Failed to load transactions."}
            </p>
          )}
          {txQuery.data && txQuery.data.length === 0 && (
            <p className="py-2 text-xs text-muted-foreground">
              No transactions found.
            </p>
          )}
          {txQuery.data && txQuery.data.length > 0 && (
            <ul className="space-y-1">
              {txQuery.data.map((tx) => (
                <li
                  key={tx.id}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {formatShortDate(tx.authorized_date || tx.date)}
                    </span>
                    <span className="truncate">{transactionLabel(tx)}</span>
                    {tx.is_pending && (
                      <span className="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400">
                        pending
                      </span>
                    )}
                    {tx.is_private && (
                      <span className="shrink-0 rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-medium text-violet-700 dark:text-violet-400">
                        private
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 tabular-nums text-emerald-700 dark:text-emerald-400">
                    {formatMoney(Math.abs(tx.amount_cents))}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}
