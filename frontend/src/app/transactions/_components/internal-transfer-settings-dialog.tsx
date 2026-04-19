"use client";

/**
 * Manage the family-wide list of counterparty names that should flag a
 * Plaid ``TRANSFER_IN`` / ``TRANSFER_OUT`` transaction as an internal
 * transfer (e.g. a spouse-to-spouse Zelle). Saving the list auto-rescans
 * the last 90 days so new names apply retroactively without a second
 * click; a separate "Re-scan all history" button covers back-fills.
 *
 * The classifier and the exclusion rules in reports live on the backend
 * (``web/plaid/internal_transfer.py`` and ``web/reports/repo.py``); this
 * dialog only edits the names list and triggers the rescan RPC.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, X } from "lucide-react";

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
import { Separator } from "@/components/ui/separator";
import { internalTransfersApi } from "@/lib/api";
import { notify } from "@/lib/notify";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function InternalTransferSettingsDialog({ open, onOpenChange }: Props) {
  const queryClient = useQueryClient();
  const [names, setNames] = useState<string[]>([]);
  const [draft, setDraft] = useState("");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["internal-transfer-settings"],
    queryFn: () => internalTransfersApi.get(),
    enabled: open,
    staleTime: 30_000,
  });

  // Seed the local list from the server snapshot on first open; do not
  // overwrite on refetch so the user's in-progress edits aren't lost.
  useEffect(() => {
    if (open && data && names.length === 0) {
      setNames(data.names);
    }
  }, [open, data, names.length]);

  // Reset local state when the dialog closes so the next open starts clean.
  useEffect(() => {
    if (!open) {
      setNames([]);
      setDraft("");
    }
  }, [open]);

  const saveMutation = useMutation({
    mutationFn: (next: string[]) => internalTransfersApi.update(next),
    onSuccess: async (res) => {
      setNames(res.names);
      await queryClient.invalidateQueries({ queryKey: ["internal-transfer-settings"] });
      // Exclusion rules reach into every report + transaction list, so bust
      // all consumer caches after saving the list (the backend already
      // auto-rescanned the last 90 days).
      await queryClient.invalidateQueries({ queryKey: ["reports"] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["budgets"] });
      notify.success("Internal-transfer names saved. Last 90 days rescanned.");
    },
    onError: (err) => {
      notify.error((err as Error)?.message || "Failed to save names.");
    },
  });

  const rescanAllMutation = useMutation({
    mutationFn: () => internalTransfersApi.rescan("all_time"),
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ["reports"] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["budgets"] });
      notify.success(
        res.rows_updated === 0
          ? "Re-scanned full history. Nothing changed."
          : `Re-scanned full history. ${res.rows_updated} transaction(s) updated.`,
      );
    },
    onError: (err) => {
      notify.error((err as Error)?.message || "Rescan failed.");
    },
  });

  const trimmedDraft = draft.trim();
  const canAddDraft = useMemo(() => {
    if (!trimmedDraft) return false;
    const key = trimmedDraft.toUpperCase();
    return !names.some((n) => n.toUpperCase() === key);
  }, [trimmedDraft, names]);

  const addDraft = () => {
    if (!canAddDraft) return;
    setNames((prev) => [...prev, trimmedDraft]);
    setDraft("");
  };

  const removeAt = (idx: number) => {
    setNames((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSave = () => {
    saveMutation.mutate(names);
  };

  const handleRescanAll = () => {
    rescanAllMutation.mutate();
  };

  const hasServerList = data?.names?.length ?? 0;
  const dirty =
    data !== undefined &&
    (names.length !== data.names.length ||
      names.some((n, i) => (data.names[i] ?? "") !== n));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Internal transfers</DialogTitle>
          <DialogDescription>
            Payments between family members (e.g. Zelle spouse-to-spouse)
            get double-counted if both sides land in the app. Add the
            counterparty names here — matching transfers are flagged and
            excluded from income/expense totals.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Example: the exact name your bank puts on a Zelle transfer, like
            {" "}
            <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
              ANASTASIIA STOLPOVSKAIA
            </code>
            . Matching is case-insensitive and tolerates bank boilerplate
            (&ldquo;Zelle payment from ...&rdquo;).
          </p>

          <div className="flex gap-2">
            <Input
              placeholder="Counterparty name"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addDraft();
                }
              }}
              disabled={isLoading || saveMutation.isPending}
            />
            <Button
              type="button"
              variant="outline"
              onClick={addDraft}
              disabled={!canAddDraft || saveMutation.isPending}
            >
              <Plus className="size-4" />
              Add
            </Button>
          </div>

          {isLoading && (
            <div className="flex items-center justify-center gap-2 rounded-md border border-border/60 py-6 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading names…
            </div>
          )}

          {isError && (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
              {(error as Error)?.message || "Failed to load names."}
              <Button
                variant="ghost"
                size="sm"
                className="mt-1 h-7 px-2"
                onClick={() => refetch()}
              >
                Retry
              </Button>
            </div>
          )}

          {!isLoading && !isError && (
            <ul className="max-h-52 overflow-y-auto rounded-md border border-border/60 divide-y divide-border/40">
              {names.length === 0 ? (
                <li className="px-3 py-6 text-center text-sm text-muted-foreground">
                  No names yet. Add a counterparty above.
                </li>
              ) : (
                names.map((name, idx) => (
                  <li
                    key={`${name}-${idx}`}
                    className="flex items-center justify-between gap-2 px-3 py-2"
                  >
                    <span className="truncate text-sm">{name}</span>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="size-7 p-0 text-muted-foreground hover:text-foreground"
                      aria-label={`Remove ${name}`}
                      onClick={() => removeAt(idx)}
                      disabled={saveMutation.isPending}
                    >
                      <X className="size-4" />
                    </Button>
                  </li>
                ))
              )}
            </ul>
          )}

          {hasServerList > 0 ? (
            <>
              <Separator />
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-xs text-muted-foreground">
                  Need to fix older months? Re-scan full history.
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={handleRescanAll}
                  disabled={rescanAllMutation.isPending || saveMutation.isPending}
                >
                  {rescanAllMutation.isPending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : null}
                  Re-scan all history
                </Button>
              </div>
            </>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={!dirty || saveMutation.isPending || isLoading}
          >
            {saveMutation.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : null}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
