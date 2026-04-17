"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";

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
import { accountsApi, transactionsApi } from "@/lib/api";
import type { Category, ManualCashTransactionCreate } from "@/types/v2";

const NONE = "__none__";

function parseAmountToCents(raw: string, flow: "expense" | "income"): number | null {
  const normalized = raw.trim().replace(",", ".");
  if (!normalized) return null;
  const n = Number(normalized);
  if (!Number.isFinite(n) || n <= 0) return null;
  const cents = Math.round(n * 100);
  if (cents <= 0) return null;
  return flow === "expense" ? cents : -cents;
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categories: Category[];
};

export function AddCashTransactionDialog({ open, onOpenChange, categories }: Props) {
  const queryClient = useQueryClient();
  const [date, setDate] = useState(() => format(new Date(), "yyyy-MM-dd"));
  const [flow, setFlow] = useState<"expense" | "income">("expense");
  const [amountStr, setAmountStr] = useState("");
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState<string>(NONE);
  const [merchantName, setMerchantName] = useState("");
  const [authorizedDate, setAuthorizedDate] = useState("");
  const [userNote, setUserNote] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const {
    data: cashWallet,
    isLoading: walletLoading,
    isError: walletError,
    error: walletErr,
  } = useQuery({
    queryKey: ["accounts", "cash-wallet"],
    queryFn: () => accountsApi.cashWallet(),
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    setFormError(null);
  }, [open]);

  const createMutation = useMutation({
    mutationFn: (body: ManualCashTransactionCreate) => transactionsApi.create(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["reports"] });
      await queryClient.invalidateQueries({ queryKey: ["budgets"] });
      await queryClient.invalidateQueries({ queryKey: ["accounts"] });
      await queryClient.invalidateQueries({ queryKey: ["accounts", "cash-wallet"] });
      onOpenChange(false);
      setAmountStr("");
      setName("");
      setCategoryId(NONE);
      setMerchantName("");
      setAuthorizedDate("");
      setUserNote("");
      setFlow("expense");
    },
    onError: (e: Error) => {
      setFormError(e.message || "Failed to create transaction");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    const cents = parseAmountToCents(amountStr, flow);
    if (cents == null) {
      setFormError("Enter a positive amount.");
      return;
    }
    const trimmedName = name.trim();
    if (!trimmedName) {
      setFormError("Enter a description.");
      return;
    }
    const body: ManualCashTransactionCreate = {
      amount_cents: cents,
      date,
      name: trimmedName,
    };
    if (categoryId !== NONE) body.category_id = Number(categoryId);
    if (merchantName.trim()) body.merchant_name = merchantName.trim();
    if (authorizedDate.trim()) body.authorized_date = authorizedDate.trim();
    if (userNote.trim()) body.user_note = userNote.trim();
    createMutation.mutate(body);
  };

  const walletErrMsg =
    walletError && walletErr instanceof Error ? walletErr.message : "Could not load Cash wallet.";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[min(90vh,720px)] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add cash transaction</DialogTitle>
          <DialogDescription>
            Offline cash spending or income is stored as <span className="font-mono text-foreground">source=cash</span>{" "}
            on your personal <span className="font-medium text-foreground">Cash</span> wallet (no bank link). It
            appears with Plaid transactions in lists, budgets, and reports. Payment channel is set to{" "}
            <span className="font-mono text-foreground">other</span>; currency is USD; transactions are never pending.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {walletError ? <p className="text-sm text-destructive">{walletErrMsg}</p> : null}
          {walletLoading ? (
            <p className="text-sm text-muted-foreground">Preparing your Cash wallet…</p>
          ) : cashWallet ? (
            <p className="text-xs text-muted-foreground">
              Wallet: <span className="font-medium text-foreground">{cashWallet.name}</span>
            </p>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="cash-date">
              Posted date <span className="text-destructive">*</span>
            </Label>
            <Input id="cash-date" type="date" value={date} onChange={(ev) => setDate(ev.target.value)} required />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="cash-name">
              Description <span className="text-destructive">*</span>
            </Label>
            <Input
              id="cash-name"
              value={name}
              onChange={(ev) => setName(ev.target.value)}
              placeholder="What was this for?"
              maxLength={500}
              required
            />
            <p className="text-xs text-muted-foreground">Maps to the transaction name (bank-style label).</p>
          </div>

          <div className="grid gap-2">
            <Label>Expense or income</Label>
            <Select value={flow} onValueChange={(v) => setFlow(v as "expense" | "income")}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="expense">Expense (outflow, positive amount in Plaid convention)</SelectItem>
                <SelectItem value="income">Income (inflow, negative amount in Plaid convention)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="cash-amount">
              Amount <span className="text-destructive">*</span>
            </Label>
            <Input
              id="cash-amount"
              inputMode="decimal"
              value={amountStr}
              onChange={(ev) => setAmountStr(ev.target.value)}
              placeholder="0.00"
              required
            />
            <p className="text-xs text-muted-foreground">Enter a positive number; flow above sets expense vs income.</p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="cash-category">Category</Label>
            <Select value={categoryId} onValueChange={setCategoryId}>
              <SelectTrigger id="cash-category">
                <SelectValue placeholder="Optional" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>None</SelectItem>
                {categories.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="cash-merchant">Merchant name</Label>
            <Input id="cash-merchant" value={merchantName} onChange={(ev) => setMerchantName(ev.target.value)} />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="cash-auth-date">Authorized date</Label>
            <Input id="cash-auth-date" type="date" value={authorizedDate} onChange={(ev) => setAuthorizedDate(ev.target.value)} />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="cash-note">Note</Label>
            <Input id="cash-note" value={userNote} onChange={(ev) => setUserNote(ev.target.value)} />
          </div>

          {formError ? <p className="text-sm text-destructive">{formError}</p> : null}

          <DialogFooter className="gap-2 sm:gap-0">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={createMutation.isPending || walletLoading || walletError || !cashWallet}
            >
              {createMutation.isPending ? "Saving…" : "Add transaction"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
