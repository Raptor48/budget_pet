"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addMonths, format, subMonths } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { budgetsApi, categoriesApi, ApiError } from "@/lib/api";
import { confirm, notify } from "@/lib/notify";
import { cn, formatCurrency } from "@/lib/utils";
import type { BudgetProgress, Category } from "@/types/v2";
import {
  ChevronLeft,
  ChevronRight,
  CopyPlus,
  Loader2,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";

type BudgetRow = BudgetProgress & { budgetId: number };

function parseMonthYm(ym: string): Date {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, (m ?? 1) - 1, 1);
}

function progressTone(p: BudgetProgress): "green" | "yellow" | "red" {
  if (p.remaining_cents < 0 || p.percent_used > 80) return "red";
  if (p.percent_used >= 50) return "yellow";
  return "green";
}

function dollarsToCents(raw: string): number | null {
  const n = Number.parseFloat(raw.replace(/[^0-9.-]/g, ""));
  if (!Number.isFinite(n) || n <= 0) return null;
  return Math.round(n * 100);
}

export function BudgetsView() {
  const queryClient = useQueryClient();
  const [month, setMonth] = useState(() => format(new Date(), "yyyy-MM"));
  const [addOpen, setAddOpen] = useState(false);
  /**
   * Budget creation works in two steps so users can pick a primary bucket
   * (default) or opt-in to "More precise" subcategory budgeting.
   */
  const [createPrimaryId, setCreatePrimaryId] = useState<string>("");
  const [createDetailId, setCreateDetailId] = useState<string>("");
  const [createPrecise, setCreatePrecise] = useState(false);
  const [createMonth, setCreateMonth] = useState(() => format(new Date(), "yyyy-MM"));
  const [createAmount, setCreateAmount] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [editRow, setEditRow] = useState<BudgetRow | null>(null);
  const [editAmount, setEditAmount] = useState("");

  const progressQuery = useQuery({
    queryKey: ["budgets", "progress", month],
    queryFn: () => budgetsApi.getProgress(month),
  });

  const listQuery = useQuery({
    queryKey: ["budgets", "list", month],
    queryFn: () => budgetsApi.list(month),
  });

  // Previous-month budgets — used for the "Copy from {prev}" affordance and
  // to know how many categories the user could rehydrate with one click.
  const prevMonth = useMemo(
    () => format(subMonths(parseMonthYm(month), 1), "yyyy-MM"),
    [month],
  );
  const prevListQuery = useQuery({
    queryKey: ["budgets", "list", prevMonth],
    queryFn: () => budgetsApi.list(prevMonth),
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
  });

  const rows: BudgetRow[] = useMemo(() => {
    const progress = progressQuery.data ?? [];
    const budgets = listQuery.data ?? [];
    return progress
      .map((p) => {
        const b = budgets.find((x) => x.category_id === p.category_id && x.month === p.month);
        if (!b) return null;
        return { ...p, budgetId: b.id };
      })
      .filter((x): x is BudgetRow => x != null);
  }, [progressQuery.data, listQuery.data]);

  const categoriesWithBudgetIds = useMemo(() => new Set(rows.map((r) => r.category_id)), [rows]);

  const categoriesById = useMemo(() => {
    const map = new Map<number, Category>();
    for (const c of categoriesQuery.data ?? []) map.set(c.id, c);
    return map;
  }, [categoriesQuery.data]);

  const childrenByParent = useMemo(() => {
    const map = new Map<number, Category[]>();
    for (const c of categoriesQuery.data ?? []) {
      if (c.parent_id == null) continue;
      const arr = map.get(c.parent_id) ?? [];
      arr.push(c);
      map.set(c.parent_id, arr);
    }
    for (const arr of map.values()) arr.sort((a, b) => a.name.localeCompare(b.name));
    return map;
  }, [categoriesQuery.data]);

  /**
   * Group budget rows by their primary bucket so parent budgets are rendered
   * before their detailed siblings and children appear indented underneath.
   * Orphans (detailed categories whose parent has no data in `categories`) are
   * still rendered as standalone cards.
   */
  const groupedRows = useMemo(() => {
    const groups: Array<{ key: string; parent: BudgetRow | null; children: BudgetRow[] }> = [];
    const byParentId = new Map<number, { parent: BudgetRow | null; children: BudgetRow[] }>();

    for (const row of rows) {
      const cat = categoriesById.get(row.category_id);
      const parentId = cat?.parent_id ?? null;

      if (parentId == null) {
        const existing = byParentId.get(row.category_id);
        if (existing) {
          existing.parent = row;
        } else {
          byParentId.set(row.category_id, { parent: row, children: [] });
        }
      } else {
        const existing = byParentId.get(parentId);
        if (existing) {
          existing.children.push(row);
        } else {
          byParentId.set(parentId, { parent: null, children: [row] });
        }
      }
    }

    for (const [parentId, g] of byParentId.entries()) {
      groups.push({ key: `p:${parentId}`, parent: g.parent, children: g.children });
    }

    groups.sort((a, b) => {
      const na = a.parent?.category_name ?? a.children[0]?.category_name ?? "";
      const nb = b.parent?.category_name ?? b.children[0]?.category_name ?? "";
      return na.localeCompare(nb);
    });
    for (const g of groups) {
      g.children.sort((a, b) => a.category_name.localeCompare(b.category_name));
    }
    return groups;
  }, [rows, categoriesById]);

  const primaryOptions = useMemo(() => {
    const all = categoriesQuery.data ?? [];
    return all
      .filter((c) => c.parent_id == null)
      .filter((c) => !categoriesWithBudgetIds.has(c.id))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [categoriesQuery.data, categoriesWithBudgetIds]);

  const detailOptions = useMemo(() => {
    if (!createPrecise || !createPrimaryId) return [] as Category[];
    const parentId = Number(createPrimaryId);
    const kids = childrenByParent.get(parentId) ?? [];
    return kids.filter((c) => !categoriesWithBudgetIds.has(c.id));
  }, [createPrecise, createPrimaryId, childrenByParent, categoriesWithBudgetIds]);

  /**
   * Primary can be locked if it already has a child budget for this month
   * (server-side would 409 anyway — we prevent it client-side too).
   */
  const primaryHasChildBudgetForMonth = useMemo(() => {
    const set = new Set<number>();
    for (const r of rows) {
      if (r.month !== createMonth) continue;
      const cat = categoriesById.get(r.category_id);
      if (cat?.parent_id != null) set.add(cat.parent_id);
    }
    return set;
  }, [rows, createMonth, categoriesById]);

  const childHasParentBudgetForMonth = useMemo(() => {
    const set = new Set<number>();
    for (const r of rows) {
      if (r.month !== createMonth) continue;
      const cat = categoriesById.get(r.category_id);
      if (cat?.parent_id == null) set.add(r.category_id);
    }
    return set;
  }, [rows, createMonth, categoriesById]);

  const invalidateBudgets = () => {
    queryClient.invalidateQueries({ queryKey: ["budgets"] });
  };

  const createMutation = useMutation({
    mutationFn: () => {
      const primaryId = Number(createPrimaryId);
      const detailId = createPrecise && createDetailId ? Number(createDetailId) : NaN;
      const targetId = Number.isFinite(detailId) ? detailId : primaryId;
      const budget_cents = dollarsToCents(createAmount);
      if (!Number.isFinite(primaryId) || primaryId <= 0) {
        return Promise.reject(new Error("Choose a category."));
      }
      if (createPrecise && (!Number.isFinite(detailId) || detailId <= 0)) {
        return Promise.reject(new Error("Choose a subcategory or uncheck ‘More precise’."));
      }
      if (budget_cents == null) {
        return Promise.reject(new Error("Enter a positive amount."));
      }
      return budgetsApi.create({ category_id: targetId, month: createMonth, budget_cents });
    },
    onSuccess: () => {
      invalidateBudgets();
      setAddOpen(false);
      setCreateAmount("");
      setCreatePrimaryId("");
      setCreateDetailId("");
      setCreatePrecise(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editRow) return Promise.reject(new Error("Nothing to edit."));
      const budget_cents = dollarsToCents(editAmount);
      if (budget_cents == null) {
        return Promise.reject(new Error("Enter a positive amount."));
      }
      return budgetsApi.update(editRow.budgetId, { budget_cents });
    },
    onSuccess: () => {
      invalidateBudgets();
      setEditOpen(false);
      setEditRow(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (budgetId: number) => budgetsApi.delete(budgetId),
    onSuccess: () => invalidateBudgets(),
  });

  // Bulk-copy every budget from prevMonth into the current month. Idempotent:
  // categories already budgeted in the current month aren't touched, so the
  // user can hit it twice or after partial manual edits without breaking
  // anything.
  const copyFromPrevMutation = useMutation({
    mutationFn: () => budgetsApi.copy(prevMonth, month),
    onSuccess: (result) => {
      invalidateBudgets();
      const noun = result.copied === 1 ? "budget" : "budgets";
      if (result.copied > 0) {
        notify.success(`Copied ${result.copied} ${noun} from ${prevMonth}.`);
      } else {
        notify.info("Nothing to copy — every category already has a budget.");
      }
    },
    onError: (err) =>
      notify.error(err instanceof Error ? err.message : "Could not copy budgets."),
  });

  // How many of last month's categories haven't been budgeted yet this month —
  // drives the "Copy N from prev" affordance. Zero means there's nothing the
  // copy button could meaningfully do, so we hide it.
  const missingFromPrev = useMemo(() => {
    const prev = prevListQuery.data ?? [];
    const current = new Set((listQuery.data ?? []).map((b) => b.category_id));
    return prev.filter((b) => !current.has(b.category_id)).length;
  }, [prevListQuery.data, listQuery.data]);

  const bumpMonth = (delta: number) => {
    const base = parseMonthYm(month);
    const next = delta > 0 ? addMonths(base, delta) : subMonths(base, -delta);
    setMonth(format(next, "yyyy-MM"));
  };

  const openAdd = () => {
    setCreateMonth(month);
    setCreatePrimaryId("");
    setCreateDetailId("");
    setCreatePrecise(false);
    setCreateAmount("");
    createMutation.reset();
    setAddOpen(true);
  };

  const openEdit = (row: BudgetRow) => {
    setEditRow(row);
    setEditAmount((row.budget_cents / 100).toFixed(2));
    updateMutation.reset();
    setEditOpen(true);
  };

  const handleDelete = async (row: BudgetRow) => {
    const ok = await confirm({
      title: "Remove budget?",
      description: `Budget for “${row.category_name}” in ${row.month} will be removed.`,
      destructive: true,
      confirmLabel: "Remove",
    });
    if (!ok) return;
    deleteMutation.mutate(row.budgetId);
  };

  const listError =
    progressQuery.error instanceof ApiError
      ? progressQuery.error.message
      : progressQuery.error instanceof Error
        ? progressQuery.error.message
        : null;

  const loading = progressQuery.isLoading || listQuery.isLoading;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Budgets</h1>
          <p className="text-muted-foreground text-sm">Envelope progress by category and month.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="icon" onClick={() => bumpMonth(-1)} aria-label="Previous month">
            <ChevronLeft className="size-4" />
          </Button>
          <span className="min-w-[10rem] text-center text-sm font-medium tabular-nums">
            {format(parseMonthYm(month), "MMMM yyyy")}
          </span>
          <Button type="button" variant="outline" size="icon" onClick={() => bumpMonth(1)} aria-label="Next month">
            <ChevronRight className="size-4" />
          </Button>
          <Button type="button" onClick={openAdd} className="sm:ml-2">
            <Plus className="size-4" />
            Add Budget
          </Button>
        </div>
      </div>

      {/* Mid-month "fill the rest" affordance. Hidden when nothing's missing or
          when the page is empty — the empty-state Card has its own primary CTA. */}
      {!loading && rows.length > 0 && missingFromPrev > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-border/70 bg-muted/30 px-3 py-2 text-sm text-muted-foreground motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300">
          <span className="flex-1">
            {missingFromPrev} {missingFromPrev === 1 ? "category was" : "categories were"} budgeted
            in {format(parseMonthYm(prevMonth), "MMM yyyy")} but not this month.
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => copyFromPrevMutation.mutate()}
            disabled={copyFromPrevMutation.isPending}
            className="gap-1.5"
          >
            {copyFromPrevMutation.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <CopyPlus className="size-3.5" />
            )}
            Copy {missingFromPrev}
          </Button>
        </div>
      ) : null}

      {listError ? (
        <p className="text-destructive text-sm" role="alert">
          {listError}
        </p>
      ) : null}

      {createMutation.isError ? (
        <p className="text-destructive text-sm" role="alert">
          {createMutation.error instanceof Error ? createMutation.error.message : "Could not create budget."}
        </p>
      ) : null}

      {updateMutation.isError ? (
        <p className="text-destructive text-sm" role="alert">
          {updateMutation.error instanceof Error ? updateMutation.error.message : "Could not update budget."}
        </p>
      ) : null}

      {deleteMutation.isError ? (
        <p className="text-destructive text-sm" role="alert">
          {deleteMutation.error instanceof ApiError
            ? deleteMutation.error.message
            : "Could not delete budget."}
        </p>
      ) : null}

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : rows.length === 0 ? (
        <Card className="motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300">
          <CardHeader>
            <CardTitle>No budgets yet</CardTitle>
            <CardDescription>
              Add a budget for this month to track spending
              {missingFromPrev > 0
                ? ` — or copy ${missingFromPrev} ${
                    missingFromPrev === 1 ? "budget" : "budgets"
                  } you set last month in one click.`
                : "."}
            </CardDescription>
          </CardHeader>
          {missingFromPrev > 0 ? (
            <CardFooter className="gap-2 border-t pt-4">
              <Button
                type="button"
                onClick={() => copyFromPrevMutation.mutate()}
                disabled={copyFromPrevMutation.isPending}
                className="gap-2"
              >
                {copyFromPrevMutation.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <CopyPlus className="size-4" />
                )}
                Copy {missingFromPrev} {missingFromPrev === 1 ? "budget" : "budgets"} from{" "}
                {format(parseMonthYm(prevMonth), "MMM yyyy")}
              </Button>
              <Button type="button" variant="outline" onClick={openAdd}>
                <Plus className="size-4" />
                Add manually
              </Button>
            </CardFooter>
          ) : null}
        </Card>
      ) : (
        (() => {
          // Split groups into two visual flows so the page reads as a tight
          // grid of standalone budgets up top and per-parent expanded
          // sections below — instead of one full-width parent per row.
          const standaloneGroups = groupedRows.filter(
            (g) => g.parent != null && g.children.length === 0,
          );
          const expandedGroups = groupedRows.filter(
            (g) => g.children.length > 0 || g.parent == null,
          );
          return (
            <div className="space-y-6">
              {standaloneGroups.length > 0 ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {standaloneGroups.map((group) => (
                    <BudgetCard
                      key={group.key}
                      row={group.parent!}
                      variant="parent"
                      onEdit={openEdit}
                      onDelete={handleDelete}
                      deleting={deleteMutation.isPending}
                    />
                  ))}
                </div>
              ) : null}

              {expandedGroups.map((group) => {
                const parent = group.parent;
                const hasKids = group.children.length > 0;
                return (
                  <section key={group.key} className="space-y-3">
                    {parent ? (
                      <BudgetCard
                        row={parent}
                        variant="parent"
                        subtitle={
                          hasKids
                            ? `Rolls up ${group.children.length} ${
                                group.children.length === 1 ? "subcategory" : "subcategories"
                              }`
                            : undefined
                        }
                        onEdit={openEdit}
                        onDelete={handleDelete}
                        deleting={deleteMutation.isPending}
                      />
                    ) : hasKids ? (
                      <header className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        <span
                          className="size-2.5 shrink-0 rounded-full border"
                          style={{ backgroundColor: group.children[0]?.category_color }}
                        />
                        <span>
                          {categoriesById.get(group.children[0]?.category_id)
                            ? categoriesById
                                .get(group.children[0]!.category_id)
                                ?.parent_id != null
                              ? (categoriesById.get(
                                  categoriesById.get(group.children[0]!.category_id)!
                                    .parent_id!,
                                )?.name ?? "Other")
                              : "Other"
                            : "Other"}
                        </span>
                        <span className="text-muted-foreground/60">· subcategory budgets</span>
                      </header>
                    ) : null}

                    {hasKids ? (
                      <div className="grid gap-3 pl-4 border-l-2 border-muted sm:grid-cols-2">
                        {group.children.map((child) => (
                          <BudgetCard
                            key={child.budgetId}
                            row={child}
                            variant="child"
                            onEdit={openEdit}
                            onDelete={handleDelete}
                            deleting={deleteMutation.isPending}
                          />
                        ))}
                      </div>
                    ) : null}
                  </section>
                );
              })}
            </div>
          );
        })()
      )}

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add budget</DialogTitle>
            <DialogDescription>Set a monthly envelope for a category.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="budget-category">Primary category</Label>
              {primaryOptions.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  Every primary bucket already has a budget for the selected month.
                </p>
              ) : (
                <Select
                  value={createPrimaryId}
                  onValueChange={(v) => {
                    setCreatePrimaryId(v);
                    setCreateDetailId("");
                  }}
                >
                  <SelectTrigger id="budget-category" className="w-full">
                    <SelectValue placeholder="Select primary bucket" />
                  </SelectTrigger>
                  <SelectContent>
                    {primaryOptions.map((c) => {
                      const blockedByChild = primaryHasChildBudgetForMonth.has(c.id);
                      return (
                        <SelectItem key={c.id} value={String(c.id)} disabled={blockedByChild}>
                          {c.name}
                          {blockedByChild ? " — has subcategory budgets" : ""}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              )}
            </div>

            <div className="flex items-start gap-2">
              <input
                id="budget-precise"
                type="checkbox"
                className="mt-1 size-4 rounded border-border"
                checked={createPrecise}
                onChange={(e) => {
                  setCreatePrecise(e.target.checked);
                  if (!e.target.checked) setCreateDetailId("");
                }}
                disabled={
                  !createPrimaryId || childHasParentBudgetForMonth.has(Number(createPrimaryId))
                }
              />
              <div className="space-y-0.5">
                <Label htmlFor="budget-precise" className="cursor-pointer">
                  More precise — budget a subcategory
                </Label>
                <p className="text-xs text-muted-foreground">
                  Budget a specific Plaid subcategory (e.g. “Rent” inside Rent & Utilities) instead
                  of the full primary bucket. You can’t mix parent and subcategory budgets for the
                  same month.
                </p>
              </div>
            </div>

            {createPrecise && createPrimaryId ? (
              <div className="grid gap-2">
                <Label htmlFor="budget-detail">Subcategory</Label>
                {detailOptions.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    No unbudgeted subcategories under this primary bucket.
                  </p>
                ) : (
                  <Select value={createDetailId} onValueChange={setCreateDetailId}>
                    <SelectTrigger id="budget-detail" className="w-full">
                      <SelectValue placeholder="Select subcategory" />
                    </SelectTrigger>
                    <SelectContent>
                      {detailOptions.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>
                          {c.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            ) : null}

            <div className="grid gap-2">
              <Label htmlFor="budget-month">Month</Label>
              <Input
                id="budget-month"
                type="month"
                value={createMonth}
                onChange={(e) => setCreateMonth(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="budget-amount">Amount (USD)</Label>
              <Input
                id="budget-amount"
                inputMode="decimal"
                placeholder="e.g. 450.00"
                value={createAmount}
                onChange={(e) => setCreateAmount(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAddOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={
                createMutation.isPending ||
                !createPrimaryId ||
                (createPrecise && !createDetailId) ||
                primaryOptions.length === 0
              }
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editOpen}
        onOpenChange={(o) => {
          setEditOpen(o);
          if (!o) setEditRow(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit budget</DialogTitle>
            <DialogDescription>
              {editRow ? `${editRow.category_name} · ${editRow.month}` : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2 py-2">
            <Label htmlFor="edit-budget-amount">Amount (USD)</Label>
            <Input
              id="edit-budget-amount"
              inputMode="decimal"
              value={editAmount}
              onChange={(e) => setEditAmount(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/**
 * Compact budget card. ~100px tall — half the height of the previous version.
 *
 * Layout, top to bottom:
 *   row 1   color dot · name · PARENT badge · percent · edit · delete
 *   row 2   amounts inline (budget · spent · saved-last-month dopamine)
 *   row 3   slim progress bar (h-1.5)
 *   row 4   status (Remaining $X / Over by $X)
 *
 * Edit/Delete are subtle ghost icon-buttons in the top-right of the row;
 * they reveal a colored hover state without dominating the card the way
 * the previous big "Edit" / "Delete" buttons in a footer did.
 */
function BudgetCard({
  row,
  variant,
  subtitle,
  onEdit,
  onDelete,
  deleting,
}: {
  row: BudgetRow;
  variant: "parent" | "child";
  subtitle?: string;
  onEdit: (row: BudgetRow) => void;
  onDelete: (row: BudgetRow) => void;
  deleting: boolean;
}) {
  const tone = progressTone(row);
  const barValue = Math.min(Math.max(row.percent_used, 0), 100);
  const indicatorClass =
    tone === "red"
      ? "[&>div]:bg-destructive"
      : tone === "yellow"
        ? "[&>div]:bg-amber-500"
        : "[&>div]:bg-emerald-600";
  const percentClass =
    tone === "red"
      ? "text-destructive"
      : tone === "yellow"
        ? "text-amber-600 dark:text-amber-500"
        : "text-emerald-600 dark:text-emerald-400";
  const prevDiff = row.previous_month_diff_cents;
  return (
    <Card
      className={cn(
        "group overflow-hidden transition-shadow motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300 hover:shadow-md",
        variant === "parent" && "border-primary/25",
      )}
    >
      <div className="space-y-1.5 px-4 py-3">
        {/* Row 1: title + percent + actions */}
        <div className="flex items-center gap-2">
          <span
            className="size-2.5 shrink-0 rounded-full border"
            style={{ backgroundColor: row.category_color }}
            aria-hidden
          />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold">
            {row.category_name}
          </span>
          {variant === "parent" ? (
            <Badge
              variant="secondary"
              className="shrink-0 px-1.5 py-0 text-[9px] uppercase tracking-wide"
            >
              Parent
            </Badge>
          ) : null}
          <span className={cn("shrink-0 text-xs font-semibold tabular-nums", percentClass)}>
            {row.percent_used.toFixed(0)}%
          </span>
          {/* Action icons. Subtle by default, slightly emphasized on card hover. */}
          <div className="flex shrink-0 items-center gap-0.5 opacity-70 transition-opacity group-hover:opacity-100">
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="size-7"
              onClick={() => onEdit(row)}
              aria-label={`Edit budget for ${row.category_name}`}
            >
              <Pencil className="size-3.5" />
            </Button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="size-7 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              onClick={() => onDelete(row)}
              disabled={deleting}
              aria-label={`Delete budget for ${row.category_name}`}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        </div>

        {/* Row 2: amounts + dopamine inline */}
        <p className="text-xs leading-snug text-muted-foreground tabular-nums">
          <span className="font-medium text-foreground">{formatCurrency(row.budget_cents)}</span>
          <span> · spent </span>
          <span className="font-medium text-foreground">{formatCurrency(row.actual_cents)}</span>
          {prevDiff != null && prevDiff > 0 ? (
            <span className="ml-2 inline-flex items-center gap-0.5 text-emerald-600 dark:text-emerald-400">
              <Sparkles className="size-3" aria-hidden />
              Saved {formatCurrency(prevDiff)} last month
            </span>
          ) : prevDiff != null && prevDiff < 0 ? (
            <span className="ml-2">over {formatCurrency(-prevDiff)} last month</span>
          ) : null}
        </p>

        {/* Row 3: slim progress bar */}
        <Progress value={barValue} className={cn("h-1.5", indicatorClass)} />

        {/* Row 4: remaining / over status. Subtitle (rare, only on parent
            standalone) tucks alongside as muted afterthought. */}
        <div className="flex items-center justify-between gap-2 text-xs leading-snug">
          {row.remaining_cents < 0 ? (
            <span className="font-medium text-destructive">
              Over by {formatCurrency(-row.remaining_cents)}
            </span>
          ) : (
            <span className="text-muted-foreground">
              {formatCurrency(row.remaining_cents)} remaining
            </span>
          )}
          {subtitle ? (
            <span className="truncate text-[10px] text-muted-foreground/70">{subtitle}</span>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
