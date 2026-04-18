"use client";

/**
 * "Create merchant rule" quick-action exposed from the transaction detail dialog.
 *
 * Pulls the merchant identity straight from the transaction row — no typing —
 * so rules keyed on `display_title` (ACH / checks / bill pays without a Plaid
 * merchant) match what the user actually sees in the UI.
 *
 * Flow: open → preview match count → confirm → create rule + apply to existing
 * in two sequential requests.
 */
import { useCallback, useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Sparkles, Wand2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError, merchantRulesApi } from "@/lib/api";
import type {
  Category,
  MerchantRulePreviewResult,
  Transaction,
} from "@/types/v2";

/**
 * Extract the stable identity fields used to build a rule key for a given
 * transaction. Mirrors backend priority: entity_id > merchant_name > display_title.
 */
function merchantIdentity(tx: Transaction): {
  entityId: string | null;
  merchantName: string | null;
  label: string | null;
} {
  const entityId = (tx.merchant_entity_id ?? "").trim() || null;
  const merchantName = (tx.merchant_name ?? "").trim() || null;
  const label =
    merchantName ??
    (tx.display_title ?? "").trim() ??
    (tx.name ?? "").trim() ??
    null;
  return { entityId, merchantName, label: label?.trim() || null };
}

export function CreateRuleFromTransactionButton({
  transaction,
  category,
  disabled,
}: {
  transaction: Transaction;
  /** Current category selected in the detail dialog (not transaction.category_id). */
  category: Category | null;
  disabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<MerchantRulePreviewResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const identity = merchantIdentity(transaction);
  const canCreate = Boolean(identity.entityId || identity.label) && !!category;

  const loadPreview = useCallback(async () => {
    if (!category) return;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const data = await merchantRulesApi.preview({
        merchant_entity_id: identity.entityId,
        merchant_name: identity.merchantName,
        merchant_label: identity.label,
        category_id: category.id,
      });
      setPreview(data);
    } catch (e) {
      setPreview(null);
      const msg =
        e instanceof ApiError
          ? e.detail || e.message
          : e instanceof Error
            ? e.message
            : "Preview failed.";
      setPreviewError(msg);
    } finally {
      setPreviewLoading(false);
    }
  }, [category, identity.entityId, identity.label, identity.merchantName]);

  useEffect(() => {
    if (open) void loadPreview();
  }, [open, loadPreview]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!category) throw new Error("Pick a category first");
      const rule = await merchantRulesApi.create({
        merchant_entity_id: identity.entityId,
        merchant_name: identity.merchantName,
        merchant_label: identity.label,
        category_id: category.id,
      });
      if ((preview?.eligible_count ?? 0) > 0) {
        await merchantRulesApi.applyExisting(rule.id);
      }
      return rule;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["merchant-rules"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["transaction", transaction.id] });
      const eligible = preview?.eligible_count ?? 0;
      toast.success(
        eligible > 0
          ? `Rule saved. Recategorized ${eligible} existing transaction(s).`
          : "Rule saved for future imports.",
      );
      setOpen(false);
    },
    onError: (e) => {
      const msg =
        e instanceof ApiError
          ? e.detail || e.message
          : e instanceof Error
            ? e.message
            : "Could not save rule.";
      toast.error(msg);
    },
  });

  if (!canCreate) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="gap-1.5"
        disabled
        title={
          !category
            ? "Pick a category first"
            : "This transaction has no merchant or description to match on"
        }
      >
        <Wand2 className="size-4" />
        Always categorize like this
      </Button>
    );
  }

  const eligible = preview?.eligible_count ?? 0;
  const label = identity.label ?? "this merchant";

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="gap-1.5"
        disabled={disabled || !category}
        onClick={() => setOpen(true)}
        title={`Family-wide rule for "${label}"`}
      >
        <Wand2 className="size-4" />
        Always categorize like this
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="size-4 text-primary" />
              Create merchant rule
            </DialogTitle>
            <DialogDescription>
              Family-wide rule: applies across all members&rsquo; accounts.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 text-sm">
            <p>
              Always categorize <span className="font-medium">&ldquo;{label}&rdquo;</span> as{" "}
              <span className="font-medium">{category?.name}</span> on import.
            </p>
            {previewLoading ? (
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" />
                Checking existing transactions…
              </p>
            ) : previewError ? (
              <p className="text-xs text-destructive" role="alert">
                {previewError}
              </p>
            ) : preview ? (
              <p className="text-xs text-muted-foreground">
                {eligible > 0
                  ? `${eligible} existing transaction(s) will be recategorized.`
                  : "No existing transactions to update — rule will apply to future imports."}
              </p>
            ) : null}
          </div>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={saveMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              disabled={saveMutation.isPending || previewLoading || !!previewError}
              onClick={() => saveMutation.mutate()}
            >
              {saveMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Saving…
                </>
              ) : (
                "Save rule"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
