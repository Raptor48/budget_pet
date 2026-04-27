"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { ArrowUpRight, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { PlaidTxnAmount } from "@/components/ui/plaid-txn-amount";
import { transactionsApi } from "@/lib/api";
import type { Account, Transaction } from "@/types/v2";
import { formatMoney, TYPE_COLORS } from "./helpers";

const RECENT_TX_LIMIT = 6;

function txTitle(tx: Transaction): string {
  return tx.display_title || tx.merchant_name || tx.name || "Transaction";
}

function shortDate(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Detail panel for non-card accounts (checking, savings, loan, investment).
 *
 * Surfaces the data we already pull from Plaid for these accounts —
 * current + available balance, last sync timestamp, mask, owner — and
 * adds the latest transactions hitting the account so users can spot-
 * check activity without leaving the Accounts page.
 *
 * Cards have their own flip-back UI; this dialog is for everything else.
 */
export function AccountDetailDialog({
  account,
  open,
  onOpenChange,
}: {
  account: Account | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const accountId = account?.id ?? null;
  const recentQuery = useQuery({
    queryKey: ["transactions", "account-recent", accountId, RECENT_TX_LIMIT],
    queryFn: () =>
      transactionsApi.list({ account_id: accountId!, limit: RECENT_TX_LIMIT }),
    enabled: open && accountId != null,
  });
  const recent = recentQuery.data ?? [];

  if (!account) return null;

  const accentColor =
    account.institution_color ?? TYPE_COLORS[account.type] ?? TYPE_COLORS.other;
  const subtitle =
    account.institution_name ||
    (account.subtype ?? account.type).replaceAll("_", " ");
  const syncedRel = account.last_synced_at
    ? formatDistanceToNow(new Date(account.last_synced_at), { addSuffix: true })
    : null;

  // Show the Available chip only when Plaid actually distinguishes it
  // from current — depository accounts often differ (pending holds);
  // loans / investments don't have a meaningful "available".
  const showAvailable =
    account.type === "depository" &&
    account.available_balance_cents != null &&
    account.available_balance_cents !== account.current_balance_cents;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <div className="flex items-start gap-3">
            <span
              className="flex size-10 shrink-0 items-center justify-center rounded-lg text-base font-bold uppercase"
              style={{
                backgroundColor: `${accentColor}22`,
                color: accentColor,
              }}
              aria-hidden
            >
              {(account.institution_name ?? account.name)[0]?.toUpperCase() ?? "?"}
            </span>
            <div className="min-w-0 flex-1">
              <DialogTitle className="truncate text-base">
                {account.official_name || account.name}
              </DialogTitle>
              <DialogDescription className="flex items-center gap-2 text-xs">
                <span className="capitalize">{subtitle}</span>
                {account.mask ? (
                  <>
                    <span className="text-border">•</span>
                    <span className="font-mono">•••• {account.mask}</span>
                  </>
                ) : null}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Balance grid */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-border/60 bg-muted/30 px-3 py-2">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">
                Current
              </p>
              <p className="mt-0.5 text-lg font-bold tabular-nums">
                {formatMoney(account.current_balance_cents, account.currency)}
              </p>
            </div>
            {showAvailable ? (
              <div className="rounded-lg border border-border/60 bg-muted/30 px-3 py-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">
                  Available
                </p>
                <p className="mt-0.5 text-lg font-bold tabular-nums">
                  {formatMoney(account.available_balance_cents!, account.currency)}
                </p>
              </div>
            ) : (
              <div className="rounded-lg border border-border/60 bg-muted/30 px-3 py-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">
                  Currency
                </p>
                <p className="mt-0.5 text-lg font-bold tabular-nums">
                  {account.currency}
                </p>
              </div>
            )}
          </div>

          {/* Meta line: owner + synced */}
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            {account.owner_username ? (
              <span>
                Owner{" "}
                <span className="font-medium text-foreground">
                  {account.owner_username}
                </span>
              </span>
            ) : null}
            {account.owner_username && syncedRel ? (
              <span className="text-border">•</span>
            ) : null}
            {syncedRel ? <span>Synced {syncedRel}</span> : null}
          </p>

          {/* Recent transactions */}
          <div className="space-y-2 border-t border-border/40 pt-3">
            <div className="flex items-baseline justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Recent activity
              </h3>
              <Link
                href={`/transactions?account_id=${account.id}`}
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                onClick={() => onOpenChange(false)}
              >
                View all
                <ArrowUpRight className="size-3" aria-hidden />
              </Link>
            </div>

            {recentQuery.isLoading ? (
              <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Loading…
              </div>
            ) : recent.length === 0 ? (
              <p className="rounded-md border border-dashed border-border/60 bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
                No transactions on this account yet.
              </p>
            ) : (
              <ul className="space-y-1">
                {recent.map((tx, i) => (
                  <li
                    key={tx.id}
                    className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-muted/40 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300"
                    style={{ animationDelay: `${Math.min(i, 6) * 30}ms` }}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium leading-tight">
                        {txTitle(tx)}
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        {shortDate(tx.date)}
                      </p>
                    </div>
                    <PlaidTxnAmount
                      cents={tx.amount_cents}
                      size="sm"
                      tone="flow"
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
