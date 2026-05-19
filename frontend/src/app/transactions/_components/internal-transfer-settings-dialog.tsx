"use client";

/**
 * Settings surface for two independent internal-transfer classifiers:
 *
 * 1. **Name list** — flags Plaid ``TRANSFER_IN`` / ``TRANSFER_OUT`` rows
 *    whose counterparty name matches one of the configured strings (e.g.
 *    a spouse-to-spouse Zelle). The user edits the list here.
 * 2. **Family-account pair matcher** — auto-flags matching cent amounts
 *    on ``TRANSFER_OUT`` / ``TRANSFER_IN`` across two different accounts
 *    that both have a known owner, within ±3 days. Always on; no
 *    configuration. Catches own-account transfers (Chase → PayPal) and
 *    cross-user pairs (Denis' PayPal → Anastasiia's Chase).
 *
 * Both stages run automatically during Plaid sync; Save re-applies them to
 * the last 90 days. The "Also re-scan full history" switch additionally
 * re-applies them to the entire transaction history. Manual user toggles
 * are never overwritten (``is_internal_transfer_manual`` guards them).
 *
 * Backend: ``web/plaid/internal_transfer.py`` (classifiers),
 * ``web/reports/repo.py`` (exclusion).
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Info, Loader2, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
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
  // Default OFF: most users only need the implicit 90-day rescan that Save
  // triggers server-side. Full-history rescan is the expensive opt-in path
  // for users retroactively changing how older months are classified.
  const [applyToAllHistory, setApplyToAllHistory] = useState(false);

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

  // Reset local state when the sheet closes so the next open starts clean.
  useEffect(() => {
    if (!open) {
      setNames([]);
      setDraft("");
      setApplyToAllHistory(false);
    }
  }, [open]);

  const rescanAllMutation = useMutation({
    mutationFn: () => internalTransfersApi.rescan("all_time"),
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ["reports"] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["budgets"] });
      const nameCount = res.name_rows_updated ?? 0;
      const pairCount = res.pair_rows_updated ?? 0;
      if (nameCount || pairCount) {
        notify.success(
          `Full history rescanned · ${nameCount} matched by name, ${pairCount} by pair.`,
        );
      } else if (res.rows_updated === 0) {
        notify.success("Full history rescanned. Nothing changed.");
      } else {
        notify.success(
          `Full history rescanned · ${res.rows_updated} transaction(s) updated.`,
        );
      }
    },
    onError: (err) => {
      notify.error((err as Error)?.message || "Rescan failed.");
    },
  });

  const saveMutation = useMutation({
    mutationFn: (next: string[]) => internalTransfersApi.update(next),
    onSuccess: async (res) => {
      setNames(res.names);
      await queryClient.invalidateQueries({ queryKey: ["internal-transfer-settings"] });
      // Exclusion rules reach into every report + transaction list, so bust
      // all consumer caches after saving the list (the backend already
      // auto-rescanned the last 90 days — both name-matcher and pair-matcher).
      await queryClient.invalidateQueries({ queryKey: ["reports"] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["budgets"] });
      if (applyToAllHistory) {
        // Chain the full-history rescan; toast comes from rescanAllMutation
        // so the user sees the breakdown rather than a generic "saved".
        rescanAllMutation.mutate();
      } else {
        notify.success("Saved · last 90 days rescanned.");
      }
    },
    onError: (err) => {
      notify.error((err as Error)?.message || "Failed to save names.");
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

  const dirty =
    data !== undefined &&
    (names.length !== data.names.length ||
      names.some((n, i) => (data.names[i] ?? "") !== n));

  const isSaving = saveMutation.isPending || rescanAllMutation.isPending;
  // Allow Save when there are unsaved name edits OR the user enabled the
  // full-history opt-in (so they can rescan without changing the list).
  const canSave = !isSaving && !isLoading && (dirty || applyToAllHistory);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Internal transfers</SheetTitle>
          <SheetDescription>
            Family transfers shouldn&rsquo;t count as income or expense — name
            matches and own-account pairs are excluded from totals.
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-4 overflow-hidden">
          <div className="flex gap-2">
            <Input
              placeholder="ANASTASIIA STOLPOVSKAIA"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addDraft();
                }
              }}
              disabled={isLoading || isSaving}
              aria-label="Counterparty name to add"
              className="font-mono text-sm"
            />
            <Button
              type="button"
              variant="outline"
              onClick={addDraft}
              disabled={!canAddDraft || isSaving}
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
            <div className="flex min-h-0 flex-1 flex-col gap-1.5">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Counterparty names · {names.length}
              </div>
              <ul className="flex-1 overflow-y-auto rounded-md border border-border/60 divide-y divide-border/40 bg-muted/20">
                {names.length === 0 ? (
                  <li className="px-3 py-8 text-center text-sm text-muted-foreground">
                    No names yet. Add a counterparty above.
                  </li>
                ) : (
                  names.map((name, idx) => (
                    <li
                      key={`${name}-${idx}`}
                      className="group flex items-center justify-between gap-2 px-3 py-2"
                    >
                      <span className="truncate font-mono text-sm">{name}</span>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="size-7 p-0 text-muted-foreground opacity-60 transition-opacity hover:text-destructive group-hover:opacity-100"
                        aria-label={`Remove ${name}`}
                        onClick={() => removeAt(idx)}
                        disabled={isSaving}
                      >
                        <X className="size-4" />
                      </Button>
                    </li>
                  ))
                )}
              </ul>
            </div>
          )}

          <div className="flex items-start gap-2 rounded-md border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
            <Check className="mt-0.5 size-3.5 shrink-0" />
            <span>
              Also auto-detects transfers between your linked accounts within
              ±3 days — no setup needed.
            </span>
          </div>

          <label
            htmlFor="apply-all-history"
            className="flex cursor-pointer items-start justify-between gap-3 rounded-md border border-border/60 px-3 py-2.5"
          >
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">Also re-scan full history</span>
              <span className="text-xs text-muted-foreground">
                Apply changes to all transactions, not just the last 90 days.
              </span>
            </div>
            <Switch
              id="apply-all-history"
              checked={applyToAllHistory}
              onCheckedChange={setApplyToAllHistory}
              disabled={isSaving}
            />
          </label>

          <details className="group rounded-md border border-border/60 px-3 py-2 text-xs">
            <summary className="flex cursor-pointer items-center gap-1.5 text-muted-foreground hover:text-foreground">
              <Info className="size-3.5" />
              How does this work?
            </summary>
            <div className="mt-2 space-y-2 leading-relaxed text-muted-foreground">
              <p>
                Payments between family members (e.g. Zelle spouse-to-spouse)
                get double-counted if both sides land in the app. Counterparty
                names here are matched against Plaid&rsquo;s{" "}
                <code className="rounded bg-muted px-1">TRANSFER_IN</code> /{" "}
                <code className="rounded bg-muted px-1">TRANSFER_OUT</code> rows
                and flagged as internal so they drop out of income/expense
                totals.
              </p>
              <p>
                Matching is case-insensitive and tolerates bank boilerplate
                like &ldquo;Zelle payment from ...&rdquo;. Use the exact name
                your bank shows — the placeholder above is a real example.
              </p>
              <p>
                Manually-flagged transactions are never overwritten.
              </p>
            </div>
          </details>
        </div>

        <SheetFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!canSave}>
            {isSaving ? <Loader2 className="size-4 animate-spin" /> : null}
            Save
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
