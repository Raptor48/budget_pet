"use client";

/**
 * "What counts as an expense?" explainer dialog.
 *
 * Unlike the Income dialog, there is NO per-category `is_expense` flag on
 * the backend (see docs/reports-math.md §3: rule 5/6). A transaction is an
 * expense when the classifier couldn't place it in `income`,
 * `internal_transfer` or `uncategorized` — which is the default for the
 * vast majority of rows on a non-income category. As a result, the only
 * levers the user actually has to move a row OUT of the "expenses" bucket
 * are:
 *
 *   1. Mark the category itself as income (via the Income tab → "Manage
 *      income categories" dialog), which reclassifies every row in that
 *      category as income.
 *   2. Pin a specific row to `internal_transfer` / `income` via its
 *      PATCH knob (`transaction_class` / `manual_class_override`) from the
 *      transaction context menu.
 *
 * This dialog makes that relationship transparent and shows the
 * month's per-category expense distribution as a read-only reference.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, TrendingDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { reportsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  month: string;
}

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

export function ExpenseCategoriesDialog({ open, onOpenChange, month }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["reports", "by-category", month, "primary"],
    queryFn: () => reportsApi.getByCategory(month, { rollup: "primary" }),
    enabled: open,
    staleTime: 30_000,
  });

  const rows = useMemo(() => {
    if (!data) return [];
    // Sort biggest-first so the user sees the categories that move the
    // needle at the top of the list.
    return [...data].sort((a, b) => b.amount_cents - a.amount_cents);
  }, [data]);

  const total = useMemo(
    () => rows.reduce((sum, r) => sum + r.amount_cents, 0),
    [rows],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <TrendingDown className="size-5 text-rose-600" aria-hidden />
            What counts as an expense?
          </DialogTitle>
          <DialogDescription>
            Anything the classifier did not tag as income, an internal
            transfer, or uncategorized. Refunds stay in their original
            category — they just reduce it.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 text-sm">
          <p className="text-muted-foreground">
            You can&apos;t toggle a category as &quot;not an expense&quot;
            directly. Instead:
          </p>
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
            <li>
              Mark a category as <strong>income</strong> in the Income tab
              to reclassify every row in it.
            </li>
            <li>
              Or pin a single row to <strong>Internal transfer</strong>{" "}
              from its context menu (e.g. a credit-card payment the
              auto-classifier missed).
            </li>
          </ul>
        </div>

        <div className="rounded-lg border border-border/60">
          <div className="flex items-center justify-between border-b border-border/60 bg-muted/40 px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <span>Category</span>
            <span>{month}</span>
          </div>
          {isLoading && (
            <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground text-sm">
              <Loader2 className="size-4 animate-spin" />
              Loading category breakdown…
            </div>
          )}
          {isError && (
            <p className="py-8 text-center text-sm text-destructive">
              {(error as Error)?.message ||
                "Failed to load category breakdown."}
            </p>
          )}
          {!isLoading && rows.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No expenses in this month.
            </p>
          )}
          {rows.length > 0 && (
            <ul className="max-h-80 divide-y divide-border/40 overflow-y-auto">
              {rows.map((row) => {
                const share = total > 0 ? (row.amount_cents / total) * 100 : 0;
                const negative = row.amount_cents < 0;
                return (
                  <li
                    key={row.bucket_key ?? row.category_name}
                    className="flex items-center justify-between gap-3 px-3 py-2"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className="size-2.5 shrink-0 rounded-full"
                        style={{ backgroundColor: row.color || "#64748b" }}
                      />
                      <span className="truncate text-sm font-medium">
                        {row.category_name}
                      </span>
                      {(row.children_count ?? 0) > 0 && (
                        <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                          {row.children_count}×
                        </span>
                      )}
                    </span>
                    <span className="flex shrink-0 items-center gap-3 text-sm">
                      <span
                        className={cn(
                          "tabular-nums",
                          negative
                            ? "text-emerald-700 dark:text-emerald-400"
                            : "text-muted-foreground",
                        )}
                      >
                        {formatMoney(row.amount_cents)}
                      </span>
                      <span className="w-10 text-right tabular-nums text-xs text-muted-foreground">
                        {share.toFixed(1)}%
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
