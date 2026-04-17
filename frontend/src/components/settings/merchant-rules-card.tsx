"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { categoriesApi, merchantRulesApi } from "@/lib/api";
import { Loader2, Tag, Trash2 } from "lucide-react";

export function MerchantRulesCard() {
  const queryClient = useQueryClient();
  const [merchantName, setMerchantName] = useState("");
  const [categoryId, setCategoryId] = useState<string>("");

  const rulesQuery = useQuery({
    queryKey: ["merchant-rules"],
    queryFn: merchantRulesApi.list,
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
  });

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
      setMerchantName("");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => merchantRulesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["merchant-rules"] });
    },
  });

  const rules = rulesQuery.data ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Tag className="h-4 w-4" />
          Merchant category rules
        </CardTitle>
        <CardDescription>
          When you set a category for a merchant here, it applies on Plaid import, bulk enrich, and
          transaction updates.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="mr-merchant">Merchant name (normalized match)</Label>
            <Input
              id="mr-merchant"
              value={merchantName}
              onChange={(e) => setMerchantName(e.target.value)}
              placeholder="e.g. Whole Foods"
              maxLength={500}
            />
          </div>
          <div className="grid gap-2">
            <Label>Category</Label>
            <Select value={categoryId} onValueChange={setCategoryId}>
              <SelectTrigger>
                <SelectValue placeholder="Select category" />
              </SelectTrigger>
              <SelectContent>
                {(categoriesQuery.data ?? []).map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {createMutation.isError ? (
          <p className="text-destructive text-sm">
            {createMutation.error instanceof Error ? createMutation.error.message : "Could not save."}
          </p>
        ) : null}
        <Button
          type="button"
          size="sm"
          disabled={createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          {createMutation.isPending ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" />
              Saving…
            </>
          ) : (
            "Save rule"
          )}
        </Button>

        <div className="border-t border-border/60 pt-4">
          <p className="text-muted-foreground mb-2 text-sm font-medium">Saved rules</p>
          {rulesQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">Loading…</p>
          ) : rules.length === 0 ? (
            <p className="text-muted-foreground text-sm">No rules yet.</p>
          ) : (
            <ul className="space-y-2">
              {rules.map((r) => (
                <li
                  key={r.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-border/60 px-3 py-2 text-sm"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{r.merchant_key}</p>
                    <p className="text-muted-foreground text-xs">→ {r.category_name}</p>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="shrink-0 text-destructive hover:text-destructive"
                    disabled={deleteMutation.isPending}
                    onClick={() => deleteMutation.mutate(r.id)}
                    aria-label={`Delete rule ${r.merchant_key}`}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
