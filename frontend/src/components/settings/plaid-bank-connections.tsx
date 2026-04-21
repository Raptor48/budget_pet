"use client";

import { useState, useCallback } from "react";
import { usePlaidLink } from "react-plaid-link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Building2, RefreshCw, Trash2, CheckCircle, AlertCircle, Clock, RotateCcw, Loader2,
} from "lucide-react";
import { plaidApi } from "@/lib/api";
import { TRANSACTIONS_DATE_RANGE_QUERY_KEY } from "@/lib/hooks/use-transactions-date-range";
import type { PlaidItem, PlaidSyncResult } from "@/types/v2";
import { AutosyncPanel } from "./autosync-card";

// ---------------------------------------------------------------
// Plaid Link button
// ---------------------------------------------------------------
function ConnectBankButton({
  onSuccess,
  itemId,
  label = "Connect Bank",
  buttonVariant = "default",
  buttonSize = "default",
}: {
  onSuccess: () => void;
  /** When set, Plaid Link opens in update mode for this item. */
  itemId?: string;
  label?: string;
  buttonVariant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  buttonSize?: "default" | "sm" | "lg" | "icon";
}) {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { open, ready } = usePlaidLink({
    token: linkToken ?? "",
    onSuccess: async (publicToken, metadata) => {
      try {
        await plaidApi.exchangeToken(publicToken, metadata.institution?.name ?? undefined);
        localStorage.removeItem("plaid_link_token");
        onSuccess();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to connect bank account.");
      }
    },
    onExit: () => {
      localStorage.removeItem("plaid_link_token");
      setLinkToken(null);
    },
  });

  const handleConnect = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const { link_token } = await plaidApi.getLinkToken(itemId);
      // Store token for OAuth redirect resume (needed when bank redirects to /oauth page)
      localStorage.setItem("plaid_link_token", link_token);
      setLinkToken(link_token);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to start bank connection.";
      setError(msg);
      console.error("Failed to get link token:", e);
    } finally {
      setLoading(false);
    }
  }, [itemId]);

  // Auto-open Plaid Link once we have a token
  if (linkToken && ready) {
    open();
    setLinkToken(null);
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        type="button"
        variant={buttonVariant}
        size={buttonSize}
        onClick={handleConnect}
        disabled={loading}
        className="gap-2"
      >
        <Building2 className="h-4 w-4" />
        {loading ? "Connecting..." : label}
      </Button>
      {error && (
        <p className="text-xs text-destructive max-w-xs">{error}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// Danger confirmation dialog
// ---------------------------------------------------------------
function DangerConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  loading,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  loading?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-destructive">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={loading} className="gap-2">
            {loading && <Loader2 className="size-4 animate-spin" />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------
// Main component
// ---------------------------------------------------------------
export function PlaidBankConnections() {
  const queryClient = useQueryClient();

  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [resetTarget, setResetTarget] = useState<string | null>(null);

  const { data: items = [], isLoading: itemsLoading } = useQuery<PlaidItem[]>({
    queryKey: ["plaid-items"],
    queryFn: plaidApi.listItems,
  });

  const { data: syncLog = [] } = useQuery({
    queryKey: ["plaid-sync-log"],
    queryFn: plaidApi.getSyncLog,
  });

  const syncMutation = useMutation<PlaidSyncResult[]>({
    mutationFn: plaidApi.sync,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plaid-items"] });
      queryClient.invalidateQueries({ queryKey: ["plaid-sync-log"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: TRANSACTIONS_DATE_RANGE_QUERY_KEY });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: ({ itemId, purge }: { itemId: string; purge: boolean }) =>
      plaidApi.deleteItem(itemId, { purge }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plaid-items"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: TRANSACTIONS_DATE_RANGE_QUERY_KEY });
      setDeleteTarget(null);
    },
  });

  const { data: deleteSummary } = useQuery({
    queryKey: ["plaid-item-data-summary", deleteTarget],
    queryFn: () =>
      deleteTarget ? plaidApi.getItemDataSummary(deleteTarget) : Promise.resolve(null),
    enabled: deleteTarget !== null,
  });

  const resetCursorMutation = useMutation({
    mutationFn: (itemId: string) => plaidApi.resetCursor(itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plaid-items"] });
      setResetTarget(null);
    },
  });

  const lastSync = syncLog[0] as (typeof syncLog)[0] | undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Building2 className="h-5 w-5" />
          Bank Connections
        </CardTitle>
        <CardDescription>
          Connect your bank via Plaid to automatically import transactions, sync balances and
          discover recurring subscriptions.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {items.some((i) => i.item_login_required) ? (
          <Alert variant="destructive" className="border-amber-600/50 bg-amber-500/10 text-amber-950 dark:text-amber-100">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
              <span>
                A bank connection needs attention. Open Link to refresh credentials.
              </span>
            </AlertDescription>
          </Alert>
        ) : null}

        {/* Connected banks */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Connected Accounts</span>
            <ConnectBankButton
              onSuccess={() => queryClient.invalidateQueries({ queryKey: ["plaid-items"] })}
            />
          </div>

          {itemsLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : items.length === 0 ? (
            <Alert>
              <Building2 className="h-4 w-4" />
              <AlertDescription>
                No banks connected yet. Click Connect Bank to link your account.
                In sandbox mode, use <strong>user_good</strong> / <strong>pass_good</strong>.
              </AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-2">
              {items.map((item) => (
                <div
                  key={item.item_id}
                  className="flex items-center justify-between rounded-lg border px-4 py-3"
                >
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <p className="text-sm font-medium">
                      {item.institution_name ?? "Unknown Bank"}
                    </p>
                    <p className="text-xs text-muted-foreground flex items-center gap-1">
                      <Clock className="h-3 w-3 shrink-0" />
                      {item.last_synced_at
                        ? `Last synced: ${new Date(item.last_synced_at).toLocaleString()}`
                        : "Never synced"}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center justify-end gap-1 ml-3">
                    <ConnectBankButton
                      itemId={item.item_id}
                      label={item.item_login_required ? "Fix connection" : "Update login"}
                      buttonVariant={item.item_login_required ? "default" : "outline"}
                      buttonSize="sm"
                      onSuccess={() => {
                        queryClient.invalidateQueries({ queryKey: ["plaid-items"] });
                        queryClient.invalidateQueries({ queryKey: ["plaid-sync-log"] });
                      }}
                    />
                    {/* Reset cursor — danger */}
                    <Button
                      size="sm"
                      variant="outline"
                      title="Reset sync cursor — re-imports all transactions on next sync"
                      className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:border-destructive gap-1.5"
                      onClick={() => setResetTarget(item.item_id)}
                      disabled={resetCursorMutation.isPending && resetTarget === item.item_id}
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      Reset
                    </Button>
                    {/* Delete — danger */}
                    <Button
                      size="sm"
                      variant="outline"
                      className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:border-destructive gap-1.5"
                      onClick={() => setDeleteTarget(item.item_id)}
                      disabled={deleteMutation.isPending && deleteTarget === item.item_id}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Remove
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Manual sync — directly under bank list */}
        <div className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-0.5">
              <p className="text-sm font-medium">Sync Now</p>
              <p className="text-xs text-muted-foreground">
                Pull latest transactions, update balances, recurring streams, and investments.
              </p>
              {/* Last sync info */}
              {!syncMutation.data && lastSync ? (
                <div className="flex items-center gap-2 pt-1">
                  <Badge
                    variant={lastSync.status === "ok" ? "default" : "destructive"}
                    className="text-xs"
                  >
                    {lastSync.status}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {new Date(lastSync.synced_at).toLocaleString()} —
                    +{lastSync.transactions_added} transactions
                  </span>
                </div>
              ) : null}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-busy={syncMutation.isPending}
              onClick={() => {
                if (syncMutation.isPending) return;
                syncMutation.mutate();
              }}
              disabled={syncMutation.isPending || items.length === 0}
              className="relative min-w-[7.5rem] shrink-0 gap-2"
            >
              <span
                className={syncMutation.isPending ? "invisible flex items-center gap-2" : "flex items-center gap-2"}
              >
                <RefreshCw className="h-4 w-4" />
                Sync
              </span>
              {syncMutation.isPending ? (
                <span className="pointer-events-none absolute inset-0 flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  Syncing…
                </span>
              ) : null}
            </Button>
          </div>

          {/* Sync results */}
          {syncMutation.data && (
            <div className="mt-3 space-y-1">
              {syncMutation.data.map((r) => (
                <Alert key={r.item_id} variant={r.status === "ok" ? "default" : "destructive"}>
                  {r.status === "ok"
                    ? <CheckCircle className="h-4 w-4" />
                    : <AlertCircle className="h-4 w-4" />}
                  <AlertDescription>
                    {r.status === "ok"
                      ? `Synced: +${r.transactions_added} transactions, ${r.balances_updated} balances updated`
                      : `Error: ${r.error_msg}`}
                  </AlertDescription>
                </Alert>
              ))}
            </div>
          )}
        </div>

        {/* Autosync schedule + webhook toggle — after Sync Now. Hidden when no banks. */}
        {items.length > 0 ? <AutosyncPanel /> : null}
      </CardContent>

      {/* Danger dialogs */}
      <DangerConfirmDialog
        open={resetTarget !== null}
        onOpenChange={(o) => !o && setResetTarget(null)}
        title="Reset Sync Cursor?"
        description="This will re-import all transactions from this bank on the next sync. Existing transactions will not be duplicated, but the sync may take longer."
        confirmLabel="Yes, Reset"
        onConfirm={() => resetTarget && resetCursorMutation.mutate(resetTarget)}
        loading={resetCursorMutation.isPending}
      />

      <RemoveBankDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        summary={deleteSummary ?? null}
        loading={deleteMutation.isPending}
        onConfirm={(purge) => {
          if (deleteTarget) deleteMutation.mutate({ itemId: deleteTarget, purge });
        }}
      />
    </Card>
  );
}

// ---------------------------------------------------------------
// Remove bank dialog — Keep data (safe) vs Delete everything (purge)
// ---------------------------------------------------------------
function RemoveBankDialog({
  open,
  onOpenChange,
  summary,
  loading,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  summary: { transactions_count: number; accounts_count: number } | null;
  loading?: boolean;
  onConfirm: (purge: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-destructive">Remove Bank Connection?</DialogTitle>
          <DialogDescription>
            {summary
              ? `This bank has ${summary.accounts_count} account(s) and ${summary.transactions_count} imported transaction(s). Choose what to do with that data.`
              : "This will permanently disconnect this bank."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 text-sm">
          <Alert className="border-amber-600/50 bg-amber-500/10 text-amber-950 dark:text-amber-100">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              If you reconnect this bank later, Plaid will issue new account IDs and will
              re-import all transactions from scratch. Unless you delete existing data now,
              you will see duplicate transactions and accounts after reconnecting.
            </AlertDescription>
          </Alert>
        </div>

        <DialogFooter className="flex flex-col gap-2 sm:flex-col sm:items-stretch sm:space-x-0">
          <Button
            variant="destructive"
            disabled={loading}
            onClick={() => onConfirm(true)}
            className="gap-2"
          >
            {loading && <Loader2 className="size-4 animate-spin" />}
            Delete everything (recommended)
          </Button>
          <Button
            variant="outline"
            disabled={loading}
            onClick={() => onConfirm(false)}
            className="gap-2"
          >
            Keep imported data (may duplicate on reconnect)
          </Button>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
