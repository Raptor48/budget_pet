"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { categoriesApi, merchantRulesApi, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { MerchantRule, MerchantRulePreviewResult } from "@/types/v2";
import { Loader2, Sparkles, Tag, Trash2, Wand2 } from "lucide-react";

const PREVIEW_DEBOUNCE_MS = 320;
const MIN_MERCHANT_LEN = 2;

export function MerchantRulesSection() {
  const queryClient = useQueryClient();
  const [merchantName, setMerchantName] = useState("");
  const [categoryId, setCategoryId] = useState<string>("");
  const [preview, setPreview] = useState<MerchantRulePreviewResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [applyDialogRule, setApplyDialogRule] = useState<MerchantRule | null>(null);
  const [applyPreview, setApplyPreview] = useState<MerchantRulePreviewResult | null>(null);
  const [applyPreviewError, setApplyPreviewError] = useState<string | null>(null);

  const rulesQuery = useQuery({
    queryKey: ["merchant-rules"],
    queryFn: merchantRulesApi.list,
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
  });

  const runDraftPreview = useCallback(async () => {
    const name = merchantName.trim();
    const cid = Number(categoryId);
    if (name.length < MIN_MERCHANT_LEN || !Number.isFinite(cid) || cid <= 0) {
      setPreview(null);
      setPreviewError(null);
      setPreviewLoading(false);
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const data = await merchantRulesApi.preview({
        merchant_name: name,
        category_id: cid,
      });
      setPreview(data);
    } catch (e) {
      setPreview(null);
      const msg =
        e instanceof ApiError ? e.detail || e.message : e instanceof Error ? e.message : "Preview failed.";
      setPreviewError(msg);
    } finally {
      setPreviewLoading(false);
    }
  }, [merchantName, categoryId]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void runDraftPreview();
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [merchantName, categoryId, runDraftPreview]);

  const createMutation = useMutation({
    mutationFn: () => {
      const cid = Number(categoryId);
      if (!merchantName.trim()) {
        return Promise.reject(new Error("Enter a merchant name."));
      }
      if (!Number.isFinite(cid) || cid <= 0) {
        return Promise.reject(new Error("Choose a category."));
      }
      return merchantRulesApi.create({
        merchant_name: merchantName.trim(),
        category_id: cid,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["merchant-rules"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      setMerchantName("");
      setPreview(null);
      setPreviewError(null);
      toast.success("Rule saved.");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => merchantRulesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["merchant-rules"] });
      toast.success("Rule removed.");
    },
  });

  const applyMutation = useMutation({
    mutationFn: (ruleId: number) => merchantRulesApi.applyExisting(ruleId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      toast.success(`Updated ${data.updated_count} transaction(s).`);
      setApplyDialogRule(null);
      setApplyPreview(null);
      setApplyPreviewError(null);
    },
    onError: (e) => {
      const msg =
        e instanceof ApiError ? e.detail || e.message : e instanceof Error ? e.message : "Apply failed.";
      toast.error(msg);
    },
  });

  const openApplyDialog = async (rule: MerchantRule) => {
    setApplyDialogRule(rule);
    setApplyPreview(null);
    setApplyPreviewError(null);
    try {
      const data = await merchantRulesApi.preview({ rule_id: rule.id });
      setApplyPreview(data);
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.detail || e.message : e instanceof Error ? e.message : "Preview failed.";
      setApplyPreviewError(msg);
    }
  };

  const rules = rulesQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];

  const categoryColor = (id: number) => categories.find((c) => c.id === id)?.color;

  return (
    <>
      <Card className="animate-in fade-in slide-in-from-bottom-2 duration-300">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Tag className="size-5 text-primary" />
            Merchant category rules
          </CardTitle>
          <CardDescription className="space-y-1 text-pretty">
            <span>
              Family-wide rules: applied on Plaid import for matching merchants. Only{" "}
              <strong>Plaid</strong> transactions can be recategorized in bulk; rows with{" "}
              <strong>custom</strong> categories or <strong>splits</strong> are skipped.
            </span>
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="mr-merchant">Merchant name</Label>
              <Input
                id="mr-merchant"
                value={merchantName}
                onChange={(e) => setMerchantName(e.target.value)}
                placeholder="e.g. Whole Foods"
                maxLength={500}
                className="transition-shadow duration-200 focus-visible:ring-2"
              />
              {previewLoading ? (
                <p className="text-muted-foreground flex items-center gap-2 text-xs">
                  <Loader2 className="size-3.5 animate-spin" />
                  Checking your transactions…
                </p>
              ) : null}
              {previewError ? (
                <p className="text-destructive text-sm" role="alert">
                  {previewError}
                </p>
              ) : null}
              {!previewLoading && !previewError && preview && merchantName.trim().length >= MIN_MERCHANT_LEN ? (
                <div
                  className="text-muted-foreground animate-in fade-in zoom-in-95 space-y-1 text-xs duration-200"
                  role="status"
                >
                  <p className="font-medium text-foreground">
                    {preview.eligible_count > 0
                      ? `${preview.eligible_count} transaction(s) would be updated with this rule.`
                      : "No matching Plaid transactions for this name (exact normalized match)."}
                  </p>
                  {preview.sample_merchant_names.length > 0 ? (
                    <p>
                      <span className="text-muted-foreground">Examples in your data: </span>
                      {preview.sample_merchant_names.join(", ")}
                    </p>
                  ) : null}
                  {(preview.skipped_splits_count > 0 ||
                    preview.skipped_custom_category_count > 0 ||
                    preview.skipped_has_entity_id_count > 0) && (
                    <p className="text-muted-foreground/90">
                      Skipped: {preview.skipped_splits_count} with splits,{" "}
                      {preview.skipped_custom_category_count} with custom category,{" "}
                      {preview.skipped_has_entity_id_count} with Plaid merchant ID (name-only rules do not
                      apply).
                    </p>
                  )}
                </div>
              ) : null}
            </div>
            <div className="grid gap-2">
              <Label>Category</Label>
              <Select value={categoryId} onValueChange={setCategoryId}>
                <SelectTrigger className="transition-shadow duration-200">
                  <SelectValue placeholder="Select category" />
                </SelectTrigger>
                <SelectContent>
                  {categories.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {createMutation.isError ? (
            <p className="text-destructive text-sm" role="alert">
              {createMutation.error instanceof Error ? createMutation.error.message : "Could not save."}
            </p>
          ) : null}

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate()}
              className="transition-transform duration-150 active:scale-[0.98]"
            >
              {createMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Saving…
                </>
              ) : (
                <>
                  <Sparkles className="mr-2 size-4" />
                  Save rule
                </>
              )}
            </Button>
          </div>

          <div className="border-border/60 space-y-3 border-t pt-4">
            <p className="text-muted-foreground text-sm font-medium">Saved rules</p>
            {rulesQuery.isLoading ? (
              <p className="text-muted-foreground text-sm">Loading…</p>
            ) : rules.length === 0 ? (
              <p className="text-muted-foreground text-sm">No rules yet.</p>
            ) : (
              <ul className="space-y-2">
                {rules.map((r, i) => (
                  <li
                    key={r.id}
                    className={cn(
                      "animate-in fade-in slide-in-from-left-2 flex flex-col gap-2 rounded-lg border border-border/60 bg-card/50 p-3 duration-200 sm:flex-row sm:items-center sm:justify-between",
                    )}
                    style={{ animationDelay: `${Math.min(i, 8) * 45}ms` }}
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <span
                        className="size-3 shrink-0 rounded-full border border-border/60 shadow-sm"
                        style={{ backgroundColor: categoryColor(r.category_id) ?? "var(--muted)" }}
                        aria-hidden
                      />
                      <div className="min-w-0">
                        <p className="truncate font-medium">{r.display_label}</p>
                        <p className="text-muted-foreground text-xs">→ {r.category_name}</p>
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        className="gap-1"
                        onClick={() => void openApplyDialog(r)}
                      >
                        <Wand2 className="size-3.5" />
                        Apply to existing
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive"
                        disabled={deleteMutation.isPending}
                        onClick={() => deleteMutation.mutate(r.id)}
                        aria-label={`Delete rule ${r.display_label}`}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>

      <Dialog open={!!applyDialogRule} onOpenChange={(o) => !o && setApplyDialogRule(null)}>
        <DialogContent className="animate-in zoom-in-95 duration-200">
          <DialogHeader>
            <DialogTitle>Apply rule to existing transactions</DialogTitle>
            <DialogDescription>
              Only <code className="text-xs">category_id</code> on matching Plaid rows is updated.
              Splits and custom categories are never changed.
            </DialogDescription>
          </DialogHeader>
          {applyDialogRule ? (
            <div className="space-y-2 text-sm">
              <p>
                <span className="font-medium">{applyDialogRule.display_label}</span>
                <span className="text-muted-foreground"> → {applyDialogRule.category_name}</span>
              </p>
              {applyPreviewError ? (
                <p className="text-destructive" role="alert">
                  {applyPreviewError}
                </p>
              ) : applyPreview ? (
                <ul className="text-muted-foreground list-inside list-disc space-y-1 text-xs">
                  <li>{applyPreview.eligible_count} row(s) will be updated (if you confirm).</li>
                  <li>Skipped: {applyPreview.skipped_splits_count} with splits.</li>
                  <li>Skipped: {applyPreview.skipped_custom_category_count} with custom category.</li>
                  <li>Skipped (name rules): {applyPreview.skipped_has_entity_id_count} with merchant entity id.</li>
                </ul>
              ) : (
                <p className="text-muted-foreground flex items-center gap-2 text-xs">
                  <Loader2 className="size-3.5 animate-spin" />
                  Loading preview…
                </p>
              )}
            </div>
          ) : null}
          <DialogFooter className="gap-2 sm:gap-0">
            <Button type="button" variant="outline" onClick={() => setApplyDialogRule(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={
                !applyDialogRule ||
                applyMutation.isPending ||
                !!applyPreviewError ||
                !applyPreview ||
                applyPreview.eligible_count === 0
              }
              onClick={() => applyDialogRule && applyMutation.mutate(applyDialogRule.id)}
            >
              {applyMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Applying…
                </>
              ) : (
                "Confirm apply"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
