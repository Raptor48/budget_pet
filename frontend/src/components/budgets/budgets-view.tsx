"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addMonths, format, subMonths } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
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
import { confirm } from "@/lib/notify";
import { cn, formatCurrency } from "@/lib/utils";
import type { BudgetProgress } from "@/types/v2";
import { ChevronLeft, ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";

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
  const [createCategoryId, setCreateCategoryId] = useState<string>("");
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

  const createCategoriesOptions = useMemo(() => {
    const all = categoriesQuery.data ?? [];
    return all.filter((c) => !categoriesWithBudgetIds.has(c.id));
  }, [categoriesQuery.data, categoriesWithBudgetIds]);

  const invalidateBudgets = () => {
    queryClient.invalidateQueries({ queryKey: ["budgets"] });
  };

  const createMutation = useMutation({
    mutationFn: () => {
      const category_id = Number(createCategoryId);
      const budget_cents = dollarsToCents(createAmount);
      if (!Number.isFinite(category_id) || category_id <= 0) {
        return Promise.reject(new Error("Choose a category."));
      }
      if (budget_cents == null) {
        return Promise.reject(new Error("Enter a positive amount."));
      }
      return budgetsApi.create({ category_id, month: createMonth, budget_cents });
    },
    onSuccess: () => {
      invalidateBudgets();
      setAddOpen(false);
      setCreateAmount("");
      setCreateCategoryId("");
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

  const bumpMonth = (delta: number) => {
    const base = parseMonthYm(month);
    const next = delta > 0 ? addMonths(base, delta) : subMonths(base, -delta);
    setMonth(format(next, "yyyy-MM"));
  };

  const openAdd = () => {
    setCreateMonth(month);
    setCreateCategoryId("");
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
        <Card>
          <CardHeader>
            <CardTitle>No budgets</CardTitle>
            <CardDescription>Add a budget for this month to track spending.</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((p) => {
            const tone = progressTone(p);
            const barValue = Math.min(Math.max(p.percent_used, 0), 100);
            const indicatorClass =
              tone === "red"
                ? "[&>div]:bg-destructive"
                : tone === "yellow"
                  ? "[&>div]:bg-amber-500"
                  : "[&>div]:bg-emerald-600";

            return (
              <Card key={p.budgetId} className="overflow-hidden">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="size-3 shrink-0 rounded-full border"
                        style={{ backgroundColor: p.category_color }}
                        title="Category color"
                      />
                      <CardTitle className="text-base leading-snug">{p.category_name}</CardTitle>
                    </div>
                    <Badge variant="outline" className="tabular-nums">
                      {p.percent_used.toFixed(0)}% used
                    </Badge>
                  </div>
                  <CardDescription className="tabular-nums">
                    Budget {formatCurrency(p.budget_cents)} · Spent {formatCurrency(p.actual_cents)}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Progress value={barValue} className={cn("h-2", indicatorClass)} />
                  {p.remaining_cents < 0 ? (
                    <p className="text-destructive text-sm font-medium">
                      Over by {formatCurrency(-p.remaining_cents)}
                    </p>
                  ) : (
                    <p className="text-muted-foreground text-sm">
                      Remaining {formatCurrency(p.remaining_cents)}
                    </p>
                  )}
                </CardContent>
                <CardFooter className="flex justify-end gap-2 border-t pt-4">
                  <Button type="button" size="sm" variant="outline" onClick={() => openEdit(p)}>
                    <Pencil className="size-3.5" />
                    Edit
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    onClick={() => handleDelete(p)}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 className="size-3.5" />
                    Delete
                  </Button>
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add budget</DialogTitle>
            <DialogDescription>Set a monthly envelope for a category.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="budget-category">Category</Label>
              {createCategoriesOptions.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  Every category already has a budget for the selected month.
                </p>
              ) : (
                <Select value={createCategoryId} onValueChange={setCreateCategoryId}>
                  <SelectTrigger id="budget-category" className="w-full">
                    <SelectValue placeholder="Select category" />
                  </SelectTrigger>
                  <SelectContent>
                    {createCategoriesOptions.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
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
                !createCategoryId ||
                createCategoriesOptions.length === 0
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
