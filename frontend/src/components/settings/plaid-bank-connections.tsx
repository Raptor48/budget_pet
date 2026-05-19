"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { usePlaidLink } from "react-plaid-link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Building2, ChevronDown, Trash2, AlertCircle, Clock, RotateCcw, Loader2,
  ImageDown,
} from "lucide-react";
import { accountsApi, plaidApi } from "@/lib/api";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { TRANSACTIONS_DATE_RANGE_QUERY_KEY } from "@/lib/hooks/use-transactions-date-range";
import type { Account, PlaidItem } from "@/types/v2";
import { AutosyncPanel } from "./autosync-card";

// ---------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------
function formatAccountSubtype(account: Account): string {
  const sub = (account.subtype || "").trim();
  if (sub) return sub.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
  const t = (account.type || "").trim();
  if (t) return t.replace(/^\w/, (c) => c.toUpperCase());
  return "Account";
}

/**
 * Build a one-line account summary for the collapsed bank header. Sole
 * purpose: distinguish duplicate banks (Chase × 2, PayPal × 2) without
 * forcing the user to expand each row. Uses the first account's
 * mask + owner; falls back to owner-only when masks are missing; returns
 * null when there's nothing distinguishing.
 */
function buildBankSummary(accounts: Account[]): string | null {
  if (accounts.length === 0) return null;
  const first = accounts[0];
  const parts: string[] = [];
  if (first.mask) parts.push(`··${first.mask}`);
  if (first.owner_username) parts.push(`@${first.owner_username}`);
  if (accounts.length > 1) parts.push(`+${accounts.length - 1} more`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

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
  // Set of item_ids whose details panel is open. Multi-open allowed so the
  // user can compare two banks side-by-side without clicking back and forth.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // Track whether we've already auto-expanded the attention-needing items
  // on this mount so subsequent refetches don't re-expand rows the user
  // explicitly closed.
  const autoExpandedRef = useRef(false);

  const { data: items = [], isLoading: itemsLoading } = useQuery<PlaidItem[]>({
    queryKey: ["plaid-items"],
    queryFn: plaidApi.listItems,
  });

  // Auto-expand rows that need login fixes — puts the Fix-connection
  // button one click away instead of two, and explains the global
  // attention banner above.
  useEffect(() => {
    if (autoExpandedRef.current || items.length === 0) return;
    const needAttention = items.filter((i) => i.item_login_required).map((i) => i.item_id);
    if (needAttention.length > 0) {
      setExpanded((prev) => {
        const next = new Set(prev);
        needAttention.forEach((id) => next.add(id));
        return next;
      });
    }
    autoExpandedRef.current = true;
  }, [items]);

  const toggleExpand = useCallback((itemId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }, []);

  // Fetch accounts so we can show what came from each Plaid item. Backend
  // already scopes by viewer (admin sees all, user sees own) — the same
  // policy applies to items, so accounts and items align row-for-row.
  const { data: accounts = [] } = useQuery<Account[]>({
    queryKey: ["accounts"],
    queryFn: () => accountsApi.list(true),
  });

  // O(1) lookup of accounts belonging to a given plaid_item_id. Cash wallet
  // and any standalone manual accounts have no plaid_item_id and are
  // skipped — they don't belong under a bank in this list.
  const accountsByItem = useMemo(() => {
    const map = new Map<string, Account[]>();
    for (const a of accounts) {
      if (!a.plaid_item_id) continue;
      const arr = map.get(a.plaid_item_id) ?? [];
      arr.push(a);
      map.set(a.plaid_item_id, arr);
    }
    return map;
  }, [accounts]);

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

  const refreshBrandingMutation = useMutation({
    mutationFn: (itemId: string) => plaidApi.refreshBranding(itemId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["plaid-items"] });
      queryClient.invalidateQueries({ queryKey: ["v2-accounts"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      const inst = result.institution_name ?? "the bank";
      if (result.logo_present) {
        notify.success(`Logo refreshed for ${inst}.`);
      } else {
        notify.info(
          `Plaid still doesn't have a logo for ${inst}. Try again later — coverage changes over time.`,
        );
      }
    },
    onError: (err) =>
      notify.error(err instanceof Error ? err.message : "Could not refresh branding."),
  });

  return (
    <Card id="settings-bank-connections" className="gap-3">
      <CardHeader className="flex flex-row items-start justify-between gap-3 pb-3 border-b">
        <div>
          <CardTitle className="flex items-center gap-2 text-base font-bold text-foreground">
            <Building2 className="h-4 w-4 text-muted-foreground" />
            Bank Connections
          </CardTitle>
          <CardDescription className="mt-1">
            Connect your bank via Plaid to import transactions, sync balances and
            discover recurring subscriptions.
          </CardDescription>
        </div>
        <ConnectBankButton
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ["plaid-items"] })}
          buttonSize="sm"
        />
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Per-row `Needs attention` pill + auto-expand replace the old
            global attention banner — the call-to-action sits exactly on
            the broken bank instead of telling the user one of them is
            broken. */}

        {/* Connected banks. Header / Connect-Bank button moved up into the
            Card header to remove the redundant `Connected Accounts` sublabel. */}
        <div className="space-y-2">
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
            <TooltipProvider delayDuration={300}>
            <div className="space-y-2">
              {items.map((item) => {
                const childAccounts = accountsByItem.get(item.item_id) ?? [];
                const isExpanded = expanded.has(item.item_id);
                const needsAttention = Boolean(item.item_login_required);
                const summary = buildBankSummary(childAccounts);
                const syncedDate = item.last_synced_at ? new Date(item.last_synced_at) : null;
                return (
                <div
                  key={item.item_id}
                  className={cn(
                    "overflow-hidden rounded-lg border transition-colors",
                    needsAttention && "border-amber-500/50",
                    isExpanded && "bg-muted/10",
                  )}
                >
                  {/* Clickable header — toggles the details panel. Whole
                      row is one button so the click target is generous. */}
                  <button
                    type="button"
                    onClick={() => toggleExpand(item.item_id)}
                    aria-expanded={isExpanded}
                    aria-controls={`bank-details-${item.item_id}`}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/30"
                  >
                    {/* Logo. Base64 data URL prefix added at render boundary
                        per CLAUDE.md / docs/data-model.md. */}
                    <div className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted">
                      {item.institution_logo ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={`data:image/png;base64,${item.institution_logo}`}
                          alt=""
                          className="size-full object-contain"
                        />
                      ) : (
                        <Building2 className="size-5 text-muted-foreground" />
                      )}
                    </div>

                    {/* Name + summary + sync time. Summary line (mask · owner)
                        is what disambiguates duplicate Plaid items (Chase × 2)
                        in the collapsed state — without it the only clue is
                        the sync timestamp, which differs by seconds. */}
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm font-medium">
                        <span>{item.institution_name ?? "Unknown Bank"}</span>
                        {summary ? (
                          <span className="text-xs font-normal text-muted-foreground">
                            {summary}
                          </span>
                        ) : null}
                        {needsAttention ? (
                          <span
                            className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-300"
                            title="Bank login expired — click to fix"
                          >
                            <AlertCircle className="size-3" />
                            Needs attention
                          </span>
                        ) : null}
                      </p>
                      {/* Relative time keeps the row scannable. Full
                          timestamp lives in the tooltip for anyone who
                          needs the precise moment. */}
                      {syncedDate ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="inline-flex cursor-help items-center gap-1 text-xs text-muted-foreground">
                              <Clock className="h-3 w-3 shrink-0" />
                              Synced{" "}
                              {formatDistanceToNow(syncedDate, { addSuffix: true })}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent side="bottom" className="text-xs">
                            {syncedDate.toLocaleString()}
                          </TooltipContent>
                        </Tooltip>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                          <Clock className="h-3 w-3 shrink-0" />
                          Never synced
                        </span>
                      )}
                    </div>

                    {/* Trailing chip: account count + chevron. Rotates 180°
                        when expanded — single visual cue for the row state. */}
                    <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
                      <span className="tabular-nums">
                        {childAccounts.length}{" "}
                        {childAccounts.length === 1 ? "account" : "accounts"}
                      </span>
                      <ChevronDown
                        className={cn(
                          "size-4 transition-transform duration-200",
                          isExpanded && "rotate-180",
                        )}
                      />
                    </div>
                  </button>

                  {/* Expanded details panel — accounts list + actions. Lives
                      in DOM only when open so the page stays compact when
                      everything is collapsed. */}
                  {isExpanded ? (
                    <div
                      id={`bank-details-${item.item_id}`}
                      className="border-t border-border/60 px-4 py-3 space-y-4"
                    >
                      {childAccounts.length > 0 ? (
                        <div>
                          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground mb-1.5">
                            Accounts
                          </p>
                          <ul className="grid grid-cols-1 gap-y-1 sm:grid-cols-2">
                            {childAccounts.map((a) => (
                              <li
                                key={a.id}
                                className="flex min-w-0 items-center gap-2 text-xs"
                              >
                                <span className="inline-flex shrink-0 items-center rounded border border-border/60 bg-muted/40 px-1.5 py-0.5 font-mono tabular-nums text-muted-foreground">
                                  {a.mask ? `··${a.mask}` : "—"}
                                </span>
                                <span className="min-w-0 truncate font-medium">
                                  {a.name}
                                </span>
                                <span className="shrink-0 text-muted-foreground">
                                  {formatAccountSubtype(a)}
                                </span>
                                {a.owner_username ? (
                                  <span className="ml-auto shrink-0 text-muted-foreground">
                                    @{a.owner_username}
                                  </span>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          No accounts yet — try syncing this bank.
                        </p>
                      )}

                      {/* Two action clusters split by `justify-between`:
                          neutral / primary actions on the left (the things
                          a user does routinely), destructive on the right
                          (the things you only do once). Visual gap between
                          them prevents misclicks. */}
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
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
                          {!item.institution_logo ? (
                            <Button
                              size="sm"
                              variant="outline"
                              title="Re-fetch institution logo from Plaid"
                              className="gap-1.5"
                              onClick={() => refreshBrandingMutation.mutate(item.item_id)}
                              disabled={
                                refreshBrandingMutation.isPending &&
                                refreshBrandingMutation.variables === item.item_id
                              }
                            >
                              {refreshBrandingMutation.isPending &&
                              refreshBrandingMutation.variables === item.item_id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <ImageDown className="h-3.5 w-3.5" />
                              )}
                              Refresh logo
                            </Button>
                          ) : null}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            size="sm"
                            variant="destructive"
                            title="Reset sync cursor — re-imports all transactions on next sync"
                            className="gap-1.5"
                            onClick={() => setResetTarget(item.item_id)}
                            disabled={resetCursorMutation.isPending && resetTarget === item.item_id}
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                            Reset
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            className="gap-1.5"
                            onClick={() => setDeleteTarget(item.item_id)}
                            disabled={deleteMutation.isPending && deleteTarget === item.item_id}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Remove
                          </Button>
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>
                );
              })}
            </div>
            </TooltipProvider>
          )}
        </div>

        {/* "Sync now" lives in the global AppLayout header now — it's
            persistent across navigations, single source. The local Sync Now
            box that used to live here was a confusing duplicate. */}

        {/* Autosync schedule + webhook toggle. Hidden when no banks. */}
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
