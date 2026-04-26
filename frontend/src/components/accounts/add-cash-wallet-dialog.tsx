"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Wallet } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { accountsApi, membersApi } from "@/lib/api";
import { useAuth } from "@/contexts/auth-context";
import { notify } from "@/lib/notify";

function dollarsToCents(raw: string): number | null {
  if (!raw.trim()) return 0;
  const n = Number.parseFloat(raw.replace(/[^0-9.\-]/g, ""));
  if (!Number.isFinite(n) || n < 0) return null;
  return Math.round(n * 100);
}

/**
 * Modal for creating a manual cash wallet with a custom name + starting
 * balance + owner. Powered by `POST /api/accounts/cash-wallet`. Replaces
 * the implicit auto-creation that happened on Accounts page load — wallets
 * are now always user-initiated.
 */
export function AddCashWalletDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated?: () => void;
}) {
  const queryClient = useQueryClient();
  const { user } = useAuth();

  const [name, setName] = useState("");
  const [balance, setBalance] = useState("");
  const [ownerId, setOwnerId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  // Members are needed for the owner picker (owner-role users) and to
  // resolve the signed-in user's numeric id from their username — the
  // auth User type only carries username + is_owner.
  const membersQuery = useQuery({
    queryKey: ["members"],
    queryFn: () => membersApi.list(),
    enabled: open,
  });
  const members = membersQuery.data ?? [];
  const meId = members.find((m) => m.username === user?.username)?.id ?? null;

  // Reset form whenever the dialog re-opens — otherwise editing a
  // half-typed value lingers until the next mount.
  useEffect(() => {
    if (open) {
      setName("");
      setBalance("");
      setOwnerId(meId != null ? String(meId) : "");
      setError(null);
    }
  }, [open, meId]);

  const mutation = useMutation({
    mutationFn: (payload: {
      name: string;
      initial_balance_cents: number;
      owner_user_id?: number | null;
    }) => accountsApi.createCashWallet(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["v2-accounts"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      notify.success("Cash wallet created.");
      onOpenChange(false);
      onCreated?.();
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : "Could not create wallet.");
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Give the wallet a name.");
      return;
    }
    const cents = dollarsToCents(balance);
    if (cents === null) {
      setError("Starting balance must be a non-negative number.");
      return;
    }
    const owner = ownerId ? Number.parseInt(ownerId, 10) : undefined;
    mutation.mutate({
      name: name.trim(),
      initial_balance_cents: cents,
      owner_user_id: Number.isFinite(owner) ? owner : undefined,
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
              <Wallet className="size-4" aria-hidden />
            </span>
            Add cash wallet
          </DialogTitle>
          <DialogDescription>
            A manual ledger you control — perfect for envelope budgeting,
            travel pockets, or anything not on a linked bank.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="cash-wallet-name">Name</Label>
            <Input
              id="cash-wallet-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Cash, Travel envelope"
              maxLength={80}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="cash-wallet-balance">Starting balance (USD)</Label>
            <Input
              id="cash-wallet-balance"
              inputMode="decimal"
              value={balance}
              onChange={(e) => setBalance(e.target.value)}
              placeholder="0.00"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="cash-wallet-owner">Owner</Label>
            {user?.is_owner && members.length > 1 ? (
              <Select value={ownerId} onValueChange={setOwnerId}>
                <SelectTrigger id="cash-wallet-owner">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {members.map((m) => (
                    <SelectItem key={m.id} value={String(m.id)}>
                      {m.username}
                      {meId === m.id ? " (you)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm">
                {user?.username ?? "you"}
                <span className="ml-2 text-xs text-muted-foreground">
                  Defaults to the signed-in user
                </span>
              </p>
            )}
          </div>

          {error && (
            <p className="text-destructive text-xs" role="alert">
              {error}
            </p>
          )}

          <DialogFooter className="pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending} className="gap-1.5">
              {mutation.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Wallet className="size-4" aria-hidden />
              )}
              Create wallet
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
