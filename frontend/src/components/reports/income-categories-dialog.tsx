"use client";

/**
 * Manage "what counts as income" — a family-wide toggle list sourced from
 * `/api/categories`. The dialog mutates the `is_income` flag on a category
 * via PATCH, which the backend uses across every income calculation
 * (Income tab, Cash Flow, Financial Health). Changes are optimistic; a
 * failure rolls back and surfaces an error.
 *
 * This is intentionally a flat list (not a tree) because income categories
 * are a small subset (~8 primary + ~20 detailed) and a tree would make the
 * toggle action harder to discover on mobile.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { categoriesApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Category } from "@/types/v2";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function IncomeCategoriesDialog({ open, onOpenChange }: Props) {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [rowError, setRowError] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
    enabled: open,
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: ({ id, is_income }: { id: number; is_income: boolean }) =>
      categoriesApi.update(id, { is_income }),
    onMutate: async ({ id, is_income }) => {
      await queryClient.cancelQueries({ queryKey: ["categories"] });
      const prev = queryClient.getQueryData<Category[]>(["categories"]);
      queryClient.setQueryData<Category[]>(["categories"], (old) =>
        old?.map((c) => (c.id === id ? { ...c, is_income } : c)) ?? old,
      );
      return { prev };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(["categories"], ctx.prev);
      setRowError((err as Error)?.message || "Failed to update category.");
    },
    onSuccess: () => {
      setRowError(null);
      // Income numbers live everywhere; blow the relevant caches so the UI
      // reflects the new definition on the next render.
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
  });

  const sorted = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    const base = q
      ? data.filter((c) => c.name.toLowerCase().includes(q))
      : data;
    // Income-first, then alpha, so it's obvious at a glance what's enabled.
    return [...base].sort((a, b) => {
      if (a.is_income !== b.is_income) return a.is_income ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }, [data, query]);

  const enabledCount = data?.filter((c) => c.is_income).length ?? 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Income categories</DialogTitle>
          <DialogDescription>
            Pick which categories count as family income. Used across Income
            reports, Cash Flow and Financial Health. Defaults come from Plaid;
            tweak anytime.
          </DialogDescription>
        </DialogHeader>

        <Input
          placeholder="Search categories…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />

        <p className="text-xs text-muted-foreground">
          {enabledCount} of {data?.length ?? 0} categories marked as income.
        </p>

        {rowError ? (
          <p className="text-destructive text-sm">{rowError}</p>
        ) : null}

        <div className="max-h-80 overflow-y-auto rounded-md border border-border/60">
          {isLoading && (
            <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground text-sm">
              <Loader2 className="size-4 animate-spin" />
              Loading categories…
            </div>
          )}
          {isError && (
            <p className="py-8 text-center text-sm text-destructive">
              {(error as Error)?.message || "Failed to load categories."}
            </p>
          )}
          {!isLoading && sorted.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No matches.
            </p>
          )}
          <ul className="divide-y divide-border/40">
            {sorted.map((cat) => (
              <li
                key={cat.id}
                className={cn(
                  "flex items-center justify-between gap-3 px-3 py-2.5",
                  cat.is_income ? "bg-emerald-500/5" : undefined,
                )}
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className="size-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: cat.color || "#94a3b8" }}
                  />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{cat.name}</p>
                    {cat.plaid_pfc_primary && (
                      <p className="truncate text-[11px] text-muted-foreground">
                        PFC {cat.plaid_pfc_primary}
                        {cat.plaid_pfc_detailed
                          ? ` · ${cat.plaid_pfc_detailed}`
                          : ""}
                      </p>
                    )}
                  </div>
                </div>
                <Switch
                  checked={cat.is_income}
                  disabled={mutation.isPending && mutation.variables?.id === cat.id}
                  onCheckedChange={(next) =>
                    mutation.mutate({ id: cat.id, is_income: next })
                  }
                  aria-label={`Toggle ${cat.name} as income`}
                />
              </li>
            ))}
          </ul>
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
