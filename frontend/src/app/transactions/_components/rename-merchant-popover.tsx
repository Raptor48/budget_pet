"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Tag } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { merchantAliasesApi } from "@/lib/api";
import { notify, onMutationError } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { Transaction } from "@/types/v2";

type Props = {
  /** The transaction whose merchant we'll rename. We need
   * ``merchant_entity_id`` + ``merchant_name`` to derive the
   * family-global key, plus ``display_title`` as a fallback for
   * ACH / check rows that have neither. */
  tx: Transaction;
  /** Optional explicit className for the trigger affordance. */
  className?: string;
};

/**
 * Single-source affordance for the merchant-alias feature in the
 * transaction details modal. Opens a small popover with:
 *
 *   - text input prefilled with the current alias (or the transaction's
 *     displayed title as a starting suggestion);
 *   - Save / Reset buttons;
 *   - one-line note explaining what the alias affects (Reports, Top
 *     merchants, Recurring, etc.).
 *
 * On save / reset we invalidate every query whose response could include
 * an aliased label so the rename appears immediately without a page
 * refresh.
 */
export function RenameMerchantPopover({ tx, className }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");

  const eid = (tx.merchant_entity_id ?? "").trim();
  const name = (tx.merchant_name ?? "").trim();
  const fallback = (tx.display_title ?? "").trim();
  // The alias system needs *something* to key on — eid, name, or
  // display_title. Hide the affordance when nothing is available
  // (extremely rare; happens for fully manual rows with empty merchant).
  const canAlias = Boolean(eid || name || fallback);

  const currentAlias = (tx.merchant_alias ?? "").trim();
  const isAliased = currentAlias.length > 0;

  // Reset the draft whenever we open or the underlying tx changes —
  // otherwise the popover would remember stale typing across rows.
  useEffect(() => {
    if (open) {
      setDraft(currentAlias || fallback || name);
    }
  }, [open, currentAlias, fallback, name]);

  const invalidate = () => {
    // Surfaces that bake the alias into their responses:
    qc.invalidateQueries({ queryKey: ["transactions"] });
    qc.invalidateQueries({ queryKey: ["transaction"] });
    qc.invalidateQueries({ queryKey: ["recurring"] });
    qc.invalidateQueries({ queryKey: ["reports"] });
    qc.invalidateQueries({ queryKey: ["insights"] });
  };

  const upsertMutation = useMutation({
    mutationFn: () =>
      merchantAliasesApi.upsert({
        display_name: draft.trim(),
        merchant_entity_id: eid || null,
        merchant_name: name || null,
        merchant_label: name ? null : fallback || null,
      }),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      notify.success(`Renamed to “${draft.trim()}”`);
    },
    onError: onMutationError("Could not save merchant alias."),
  });

  const deleteMutation = useMutation({
    mutationFn: () =>
      merchantAliasesApi.delete({
        merchant_entity_id: eid || null,
        merchant_name: name || null,
        merchant_label: name ? null : fallback || null,
      }),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      notify.success("Merchant alias removed");
    },
    onError: onMutationError("Could not remove alias."),
  });

  if (!canAlias) return null;

  const trimmed = draft.trim();
  const saveDisabled =
    upsertMutation.isPending ||
    deleteMutation.isPending ||
    trimmed.length === 0 ||
    trimmed === currentAlias;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "text-muted-foreground hover:text-foreground inline-flex items-center gap-1 rounded-sm px-1 py-0.5 text-[11px] uppercase tracking-wide transition-colors",
            isAliased && "text-foreground/80",
            className,
          )}
          aria-label={isAliased ? "Edit merchant alias" : "Rename merchant"}
        >
          {isAliased ? <Tag className="size-3" /> : <Pencil className="size-3" />}
          <span>{isAliased ? `Aliased as “${currentAlias}”` : "Rename merchant"}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 space-y-3">
        <div className="space-y-1">
          <Label htmlFor="merchant-alias-input" className="text-sm">
            Show this merchant as
          </Label>
          <Input
            id="merchant-alias-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={200}
            placeholder="e.g. Rent"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && !saveDisabled) {
                e.preventDefault();
                upsertMutation.mutate();
              }
            }}
          />
          <p className="text-muted-foreground text-[11px] leading-snug">
            Display rename only — applies everywhere this merchant appears (Top
            merchants, Recurring, Insights). Categorization, math, and Plaid
            sync are untouched.
          </p>
        </div>
        <div className="flex justify-between gap-2">
          {isAliased ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={deleteMutation.isPending || upsertMutation.isPending}
              onClick={() => deleteMutation.mutate()}
              className="text-destructive hover:text-destructive"
            >
              Remove alias
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setOpen(false)}
              disabled={upsertMutation.isPending || deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={saveDisabled}
              onClick={() => upsertMutation.mutate()}
            >
              Save
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
