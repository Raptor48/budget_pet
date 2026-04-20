"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Trash2, Wallet } from "lucide-react";
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
import { accountsApi } from "@/lib/api";
import type { Account } from "@/types/v2";
import { formatMoney } from "./helpers";

/**
 * Cash wallet panel. Lives inside an owner column (compact variant)
 * or at the bottom of the Accounts page as a standalone section.
 *
 * Compact variant trims font sizes and vertical padding so it fits
 * naturally alongside FlipCards and AccountTiles in a single column.
 */
export function CashWalletSection({
  account,
  variant = "section",
}: {
  account: Account;
  variant?: "section" | "compact";
}) {
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [balanceInput, setBalanceInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const updateMutation = useMutation({
    mutationFn: (cents: number) =>
      accountsApi.update(account.id, { current_balance_cents: cents }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["v2-accounts"] });
      setEditOpen(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => accountsApi.delete(account.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["v2-accounts"] });
      queryClient.removeQueries({ queryKey: ["accounts", "cash-wallet-ensure"] });
      setDeleteOpen(false);
    },
  });

  function openEdit() {
    setBalanceInput((account.current_balance_cents / 100).toFixed(2));
    setEditOpen(true);
    setTimeout(() => inputRef.current?.select(), 50);
  }

  function handleSaveBalance() {
    const parsed = parseFloat(balanceInput.replace(/[^0-9.\-]/g, ""));
    if (isNaN(parsed)) return;
    updateMutation.mutate(Math.round(parsed * 100));
  }

  const formattedBalance = formatMoney(
    account.current_balance_cents,
    account.currency ?? "USD",
  );

  const compact = variant === "compact";

  const card = compact ? (
    <div className="relative overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm">
      <div className="absolute inset-y-0 left-0 w-1 rounded-l-xl bg-emerald-500" />
      <div className="flex items-center gap-2.5 py-2 pl-4 pr-3">
        <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-500">
          <Wallet className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold leading-snug">
            {account.name}
          </p>
          <p className="text-[10px] text-muted-foreground">Manual cash wallet</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[13px] font-bold tabular-nums">{formattedBalance}</p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="size-7"
            onClick={openEdit}
            title="Edit balance"
          >
            <Pencil className="size-3.5" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="size-7 text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => setDeleteOpen(true)}
            title="Delete wallet"
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>
    </div>
  ) : (
    <div className="flex flex-col gap-4 rounded-xl border border-border/60 bg-card px-4 py-4 shadow-sm sm:flex-row sm:items-center sm:gap-3 sm:px-5">
      <div className="flex min-w-0 items-start gap-3 sm:min-w-0 sm:flex-1 sm:items-center">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-500">
          <Wallet className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{account.name}</p>
          <p className="text-xs text-muted-foreground">
            Manual cash tracking wallet
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center justify-between gap-3 border-t border-border/50 pt-3 sm:border-t-0 sm:pt-0">
        <div className="text-left sm:text-right">
          <p className="text-lg font-bold tabular-nums">{formattedBalance}</p>
          {account.owner_username && (
            <p className="text-[10px] text-muted-foreground">
              {account.owner_username}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={openEdit}
          >
            <Pencil className="size-3.5" />
            Edit balance
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 className="size-3.5" />
            Delete
          </Button>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {compact ? (
        card
      ) : (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Cash Wallet</h2>
          {card}
        </section>
      )}

      {/* Edit balance dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-xs">
          <DialogHeader>
            <DialogTitle>Edit Cash Wallet balance</DialogTitle>
            <DialogDescription>
              Set the current balance directly. This does not create a transaction.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="cash-balance">Balance (USD)</Label>
            <Input
              id="cash-balance"
              ref={inputRef}
              type="number"
              step="0.01"
              value={balanceInput}
              onChange={(e) => setBalanceInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSaveBalance()}
              placeholder="0.00"
            />
          </div>
          {updateMutation.isError && (
            <p className="text-sm text-destructive">
              {updateMutation.error instanceof Error
                ? updateMutation.error.message
                : "Failed to update balance"}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setEditOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleSaveBalance}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Saving…
                </>
              ) : (
                "Save"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete Cash Wallet?</DialogTitle>
            <DialogDescription>
              The wallet will be deactivated. Existing cash transactions will remain in your history
              but will no longer be linked to an active account.
            </DialogDescription>
          </DialogHeader>
          {deleteMutation.isError && (
            <p className="text-sm text-destructive">
              {deleteMutation.error instanceof Error
                ? deleteMutation.error.message
                : "Failed to delete wallet"}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Deleting…
                </>
              ) : (
                "Delete wallet"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
