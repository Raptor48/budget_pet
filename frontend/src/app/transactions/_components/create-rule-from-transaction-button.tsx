"use client";

/**
 * "Always categorize like this" — smart rule creation from a transaction row.
 *
 * The dialog now offers three scopes instead of one, auto-selecting the
 * most useful default based on the merchant's transaction diversity:
 *
 *   1. **Just this transaction** — sets ``category_id`` on the row only,
 *      no rule. Always available.
 *   2. **Narrow with description** — creates a rule keyed by merchant +
 *      a substring (auto-suggested from the row's ``name``). Shown only
 *      when the merchant has >1 distinct description in history; that's
 *      the case where a generic rule would be too broad. Pre-selected
 *      when shown.
 *   3. **All transactions of this merchant** — the original, generic rule.
 *      Pre-selected when narrow doesn't apply.
 *
 * Two preview calls fire in parallel after the dialog opens — one per
 * applicable rule shape — so the user sees both match counts before
 * committing. Substring is editable; preview re-runs (debounced) on edit.
 */
import { useCallback, useEffect, useRef, useState } from "react";
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
import { Input } from "@/components/ui/input";
import { ApiError, merchantRulesApi, transactionsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Category,
  MerchantRulePreviewResult,
  Transaction,
} from "@/types/v2";

type RuleScope = "row" | "narrow" | "all";

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

/**
 * Heuristic: pick the most distinctive substring from this row's
 * description that the user might want to filter on.
 *
 * Approach:
 *   1. Take the raw transaction name (statement line).
 *   2. Strip the merchant_name (already implied by the rule).
 *   3. Drop pure-numeric tokens longer than 6 chars (Plaid reference IDs
 *      like ``24800561672`` — they vary per transaction).
 *   4. Drop very short tokens (< 3 chars) and obvious noise words.
 *   5. Return the longest remaining word, lower-cased. Empty string if
 *      nothing useful survives.
 *
 * Examples:
 *   ``Zelle payment to ALLA 24800561672`` → ``alla``
 *   ``VENMO PAYMENT TO JOHN 9876543210``  → ``john``
 *   ``ACH TRANSFER REF# 8329472``         → "" (nothing distinctive)
 */
const _NOISE_WORDS = new Set<string>([
  "to",
  "from",
  "the",
  "ach",
  "ref",
  "for",
  "and",
  "via",
  "payment",
  "transfer",
  "deposit",
  "withdrawal",
  "purchase",
  "debit",
  "credit",
  "online",
  "mobile",
  "web",
]);

function suggestNarrowSubstring(tx: Transaction): string {
  const raw = (tx.name ?? tx.display_title ?? "").trim();
  if (!raw) return "";
  const merchantTokens = (tx.merchant_name ?? "")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  const tokens = raw
    .split(/[\s,;:#.\-_/]+/)
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean)
    // Drop merchant tokens (already implied by the merchant_key match).
    .filter((t) => !merchantTokens.includes(t))
    // Drop pure-numeric reference IDs.
    .filter((t) => !(/^\d+$/.test(t) && t.length > 6))
    // Drop tiny tokens and known filler words.
    .filter((t) => t.length >= 3 && !_NOISE_WORDS.has(t));
  if (tokens.length === 0) return "";
  // Prefer the longest distinctive token; ties broken by appearance order.
  tokens.sort((a, b) => b.length - a.length);
  return tokens[0];
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
  const [scope, setScope] = useState<RuleScope>("all");
  const [narrowText, setNarrowText] = useState<string>("");
  const [genericPreview, setGenericPreview] = useState<MerchantRulePreviewResult | null>(null);
  const [narrowPreview, setNarrowPreview] = useState<MerchantRulePreviewResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  // Two distinct loading flags so the UI can surface progress per-row
  // instead of one ambiguous "loading" state. ``narrowLoading`` flips
  // both during the initial parallel preview AND during every debounced
  // re-run when the user types — giving immediate visual feedback that
  // a recompute is in flight.
  const [genericLoading, setGenericLoading] = useState(false);
  const [narrowLoading, setNarrowLoading] = useState(false);
  // Debounce ref for narrow-preview re-runs while user types.
  const narrowDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Monotonically incremented per dialog-open. Each in-flight request
  // captures the current value; when its response lands the handler
  // checks the token still matches before applying state, dropping
  // stale results. Closes the race that previously let an old
  // dialog-open's preview overwrite the current one's data (the
  // "first time the count showed 0" symptom).
  const requestTokenRef = useRef(0);

  const identity = merchantIdentity(transaction);
  const canCreate = Boolean(identity.entityId || identity.label) && !!category;

  /** Fetch both previews; auto-pick scope based on diversity. */
  const loadPreview = useCallback(async () => {
    if (!category) return;
    const myToken = ++requestTokenRef.current;
    setPreviewError(null);
    setGenericLoading(true);
    try {
      const generic = await merchantRulesApi.preview({
        merchant_entity_id: identity.entityId,
        merchant_name: identity.merchantName,
        merchant_label: identity.label,
        category_id: category.id,
      });
      // Stale-response guard: dialog was closed / reopened before this
      // resolved; whatever we'd write is meaningless and would only
      // pollute the next open's state.
      if (myToken !== requestTokenRef.current) return;
      setGenericPreview(generic);
      setGenericLoading(false);

      // Decide whether to even compute the narrow preview. We surface
      // the narrow option only when the merchant has multiple distinct
      // descriptions — otherwise the filter is just noise.
      const distinct = generic.distinct_description_count ?? 0;
      const suggestion = suggestNarrowSubstring(transaction);
      if (distinct > 1 && suggestion) {
        setNarrowText(suggestion);
        setScope("narrow");
        setNarrowLoading(true);
        const narrow = await merchantRulesApi.preview({
          merchant_entity_id: identity.entityId,
          merchant_name: identity.merchantName,
          merchant_label: identity.label,
          category_id: category.id,
          description_contains: suggestion,
        });
        if (myToken !== requestTokenRef.current) return;
        setNarrowPreview(narrow);
        setNarrowLoading(false);
      } else {
        setNarrowPreview(null);
        setNarrowText("");
        setScope("all");
      }
    } catch (e) {
      if (myToken !== requestTokenRef.current) return;
      setGenericPreview(null);
      setNarrowPreview(null);
      setGenericLoading(false);
      setNarrowLoading(false);
      const msg =
        e instanceof ApiError
          ? e.detail || e.message
          : e instanceof Error
            ? e.message
            : "Preview failed.";
      setPreviewError(msg);
    }
    // ``identity`` is derived from ``transaction``; safe to depend on the parts.
  }, [
    category,
    identity.entityId,
    identity.label,
    identity.merchantName,
    transaction,
  ]);

  useEffect(() => {
    if (open) {
      // Hard reset of all preview state so a previous open's leftovers
      // never bleed into this one. Without this, a user who closed the
      // dialog mid-load and reopened would briefly see stale numbers
      // (or "0 matches" when the previous request resolved post-close).
      setGenericPreview(null);
      setNarrowPreview(null);
      setNarrowText("");
      setScope("all");
      setPreviewError(null);
      void loadPreview();
    }
    return () => {
      // Bumping the token here invalidates any in-flight requests from
      // this open; they'll see the mismatch and drop their writes.
      requestTokenRef.current += 1;
      if (narrowDebounceRef.current) clearTimeout(narrowDebounceRef.current);
    };
  }, [open, loadPreview]);

  /** Re-run the narrow preview when the user edits the substring. Debounced. */
  useEffect(() => {
    if (!open) return;
    if (!category) return;
    if (scope !== "narrow") return;
    const text = narrowText.trim();
    if (!text) {
      setNarrowPreview(null);
      setNarrowLoading(false);
      return;
    }
    if (narrowDebounceRef.current) clearTimeout(narrowDebounceRef.current);
    // Optimistic loading flag — starts the spinner the moment the user
    // types, even before the 250ms debounce fires. Without this the UI
    // sat silent for the entire debounce window.
    setNarrowLoading(true);
    const myToken = requestTokenRef.current;
    narrowDebounceRef.current = setTimeout(async () => {
      try {
        const data = await merchantRulesApi.preview({
          merchant_entity_id: identity.entityId,
          merchant_name: identity.merchantName,
          merchant_label: identity.label,
          category_id: category.id,
          description_contains: text,
        });
        if (myToken !== requestTokenRef.current) return;
        setNarrowPreview(data);
        setNarrowLoading(false);
      } catch {
        // Errors here are non-fatal — the user can still save; the
        // displayed "X matches" just won't update for a bad query.
        if (myToken !== requestTokenRef.current) return;
        setNarrowLoading(false);
      }
    }, 250);
    return () => {
      if (narrowDebounceRef.current) clearTimeout(narrowDebounceRef.current);
    };
  }, [
    narrowText,
    scope,
    open,
    category,
    identity.entityId,
    identity.label,
    identity.merchantName,
  ]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!category) throw new Error("Pick a category first");

      // Scope #1: row-only — patch the transaction's category, no rule.
      if (scope === "row") {
        await transactionsApi.update(transaction.id, { category_id: category.id });
        return { kind: "row" as const };
      }

      // Scope #2/#3: rule. Narrow includes a substring filter; "all" doesn't.
      const filter =
        scope === "narrow" ? narrowText.trim() || null : null;
      const rule = await merchantRulesApi.create({
        merchant_entity_id: identity.entityId,
        merchant_name: identity.merchantName,
        merchant_label: identity.label,
        category_id: category.id,
        description_contains: filter,
      });
      const eligible = (scope === "narrow" ? narrowPreview : genericPreview)?.eligible_count ?? 0;
      if (eligible > 0) {
        await merchantRulesApi.applyExisting(rule.id);
      }
      return { kind: "rule" as const, eligible, scope };
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["merchant-rules"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["transaction", transaction.id] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      queryClient.invalidateQueries({ queryKey: ["insights"] });

      if (result.kind === "row") {
        toast.success("Category updated for this transaction.");
      } else if (result.eligible > 0) {
        toast.success(
          `Rule saved. Recategorized ${result.eligible} existing transaction(s).`,
        );
      } else {
        toast.success("Rule saved for future imports.");
      }
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

  const label = identity.label ?? "this merchant";
  const showNarrowOption = (genericPreview?.distinct_description_count ?? 0) > 1;

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
              Apply category to…
            </DialogTitle>
            <DialogDescription>
              Set <span className="font-medium">{category?.name}</span> on this row, or
              create a family-wide rule.
            </DialogDescription>
          </DialogHeader>

          {genericLoading && !genericPreview ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              Checking existing transactions…
            </div>
          ) : previewError ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive" role="alert">
              {previewError}
            </div>
          ) : (
            <div className="space-y-2">
              <ScopeOption
                value="row"
                current={scope}
                onSelect={setScope}
                title="Just this transaction"
                subtitle="Sets the category on this row only. No rule created."
              />
              {showNarrowOption && (
                <ScopeOption
                  value="narrow"
                  current={scope}
                  onSelect={setScope}
                  title={
                    <span>
                      Only <span className="font-semibold">{label}</span> with{" "}
                      <span className="font-mono text-xs">&ldquo;{narrowText || "…"}&rdquo;</span>{" "}
                      in description
                    </span>
                  }
                  subtitle={
                    <CountSubtitle
                      loading={narrowLoading}
                      count={narrowPreview?.eligible_count}
                    />
                  }
                  recommended
                >
                  <Input
                    type="text"
                    value={narrowText}
                    onChange={(e) => setNarrowText(e.target.value)}
                    placeholder="e.g. ALLA"
                    className="mt-2 h-8 text-xs"
                    onClick={(e) => e.stopPropagation()}
                    onFocus={() => setScope("narrow")}
                  />
                </ScopeOption>
              )}
              <ScopeOption
                value="all"
                current={scope}
                onSelect={setScope}
                title={
                  <span>
                    All <span className="font-semibold">{label}</span> transactions
                  </span>
                }
                subtitle={
                  <CountSubtitle
                    loading={genericLoading}
                    count={genericPreview?.eligible_count}
                  />
                }
              />
            </div>
          )}

          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={saveMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              disabled={
                saveMutation.isPending ||
                genericLoading ||
                narrowLoading ||
                !!previewError ||
                (scope === "narrow" && !narrowText.trim())
              }
              onClick={() => saveMutation.mutate()}
            >
              {saveMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Saving…
                </>
              ) : (
                "Save"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ---------------------------------------------------------------------------
// Radio-style scope option
// ---------------------------------------------------------------------------

function ScopeOption({
  value,
  current,
  onSelect,
  title,
  subtitle,
  children,
  recommended,
}: {
  value: RuleScope;
  current: RuleScope;
  onSelect: (v: RuleScope) => void;
  title: React.ReactNode;
  subtitle: React.ReactNode;
  children?: React.ReactNode;
  recommended?: boolean;
}) {
  const active = current === value;
  return (
    <button
      type="button"
      onClick={() => onSelect(value)}
      className={cn(
        "group flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors",
        active
          ? "border-primary/50 bg-primary/5"
          : "border-border/60 hover:bg-muted/40",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
          active ? "border-primary" : "border-border",
        )}
        aria-hidden
      >
        {active && <span className="size-1.5 rounded-full bg-primary" />}
      </span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-1.5 text-sm">
          {title}
          {recommended && active && (
            <span className="rounded-full bg-primary/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">
              Suggested
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
        {children}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Subtitle that distinguishes "still computing" from "no results"
// ---------------------------------------------------------------------------

/**
 * Renders the per-option match-count line. The earlier version showed a
 * silent "Computing…" string with no visible activity, which made users
 * think the count was final ("0 found") rather than in-flight. This
 * variant pairs the label with a spinner and a subtle background pulse
 * so the loading state is unmistakable.
 *
 * Loading wins over count: if a re-compute is in flight (user typed a
 * new substring), we keep showing the spinner instead of the stale
 * count — otherwise the UI would briefly display the previous result
 * as if it matched the new query.
 */
function CountSubtitle({
  loading,
  count,
}: {
  loading: boolean;
  count: number | null | undefined;
}) {
  if (loading) {
    return (
      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
        <Loader2 className="size-3 animate-spin" aria-hidden />
        <span className="motion-safe:animate-pulse">Computing…</span>
      </span>
    );
  }
  if (count == null) {
    // Hasn't been computed yet (e.g. narrow option visible but the
    // generic preview still in flight). Fall back to a neutral hint.
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <span>
      <span className="font-medium tabular-nums">{count}</span>{" "}
      existing transaction{count === 1 ? "" : "s"} match
    </span>
  );
}
