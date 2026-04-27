"use client";

import { useState } from "react";
import Image from "next/image";
import { format } from "date-fns";
import { ArrowLeftRight, CreditCard, EyeOff, Loader2, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PlaidTxnAmount } from "@/components/ui/plaid-txn-amount";
import { normalizeTransactionTitle, rawTransactionTitle } from "@/lib/transaction-display";
import { cn } from "@/lib/utils";
import type { Transaction } from "@/types/v2";

function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function displayName(tx: Transaction): string {
  return normalizeTransactionTitle(tx);
}

function displayDateShort(tx: Transaction): string {
  const d = tx.authorized_date || tx.date;
  try {
    return format(new Date(d), "MMM d");
  } catch {
    return String(d).slice(0, 10);
  }
}

function MobileMerchantAvatar({ tx }: { tx: Transaction }) {
  const [failed, setFailed] = useState(false);
  const name = displayName(tx);
  const showImg = Boolean(tx.logo_url) && !failed;

  return (
    <div className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted text-[10px] font-semibold text-muted-foreground">
      {showImg ? (
        <Image
          src={tx.logo_url!}
          alt=""
          width={36}
          height={36}
          className="size-full object-cover"
          onError={() => setFailed(true)}
          unoptimized
        />
      ) : (
        <span className="leading-none">{initialsFromName(name)}</span>
      )}
    </div>
  );
}

function MobileAccountLine({ tx }: { tx: Transaction }) {
  const mask = tx.account_mask;
  const name = tx.account_name;
  const owner = tx.owner_username;
  if (!mask && !name) return null;
  const cardLabel = mask ? `•••• ${mask}` : (name ?? "");
  return (
    <span className="flex min-w-0 items-center gap-1 text-[11px] text-muted-foreground">
      <CreditCard className="size-3 shrink-0 opacity-70" aria-hidden />
      {owner ? <span className="shrink-0 font-medium text-foreground/80">{owner}</span> : null}
      <span className="truncate font-mono tracking-wide">{cardLabel}</span>
    </span>
  );
}

export type TransactionMobileCardProps = {
  tx: Transaction;
  highlight?: boolean;
  onOpen: () => void;
  onDeleteCash?: (e: React.MouseEvent) => void;
  cashDeletePending?: boolean;
  loadingList?: boolean;
  /** Used by the parent list to stagger the entrance animation. */
  index?: number;
};

/**
 * Compact transaction row for viewports below `md`. Tap opens details; cash
 * rows optionally show a small delete control.
 */
export function TransactionMobileCard({
  tx,
  highlight,
  onOpen,
  onDeleteCash,
  cashDeletePending,
  loadingList,
  index = 0,
}: TransactionMobileCardProps) {
  const title = displayName(tx);

  return (
    <button
      type="button"
      id={`txn-row-${tx.id}`}
      data-txn-id={tx.id}
      onClick={onOpen}
      className={cn(
        "relative flex w-full min-w-0 items-start gap-2 rounded-lg border border-border/80 bg-card px-3 py-2.5 text-left transition-colors",
        "hover:bg-muted/40 active:bg-muted/60",
        "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300",
        highlight && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        tx.is_private &&
          "relative border-amber-500/30 bg-amber-500/[0.04] before:absolute before:inset-y-2 before:left-1 before:w-0.5 before:rounded-full before:bg-amber-500/50",
      )}
      style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}
    >
      <MobileMerchantAvatar tx={tx} />
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p
              className="line-clamp-2 min-w-0 break-words text-sm font-medium leading-snug"
              title={rawTransactionTitle(tx) || title}
            >
              {title}
            </p>
            <MobileAccountLine tx={tx} />
          </div>
          <div className="flex shrink-0 flex-col items-end gap-0.5">
            <PlaidTxnAmount cents={tx.amount_cents} size="sm" tone="flow" />
            <span className="text-[10px] text-muted-foreground tabular-nums">
              {displayDateShort(tx)}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          {tx.is_pending ? (
            <Badge variant="secondary" className="px-1.5 py-0 text-[9px] uppercase tracking-wide">
              Pending
            </Badge>
          ) : null}
          {tx.is_private ? (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-500/10 px-1.5 py-0 text-[9px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-400">
              <EyeOff className="size-2.5" aria-hidden />
              Private
            </span>
          ) : null}
          {/* Source of truth: ``transaction_class``. The legacy
              ``is_internal_transfer`` boolean can briefly disagree on
              freshly-imported historical rows; reading from the modern
              column matches what the aggregates count. See
              docs/categorization-precedence.md §4. */}
          {tx.transaction_class === "internal_transfer" ? (
            <span
              className="inline-flex items-center gap-0.5 rounded-full bg-sky-500/10 px-1.5 py-0 text-[9px] font-medium uppercase tracking-wide text-sky-700 dark:text-sky-400"
              title="Intra-family transfer — excluded from income/expense totals."
            >
              <ArrowLeftRight className="size-2.5" aria-hidden />
              Internal
            </span>
          ) : null}
          {onDeleteCash ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="ml-auto size-7 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
              title="Delete cash transaction"
              disabled={loadingList || cashDeletePending}
              onClick={(e) => {
                e.stopPropagation();
                onDeleteCash(e);
              }}
            >
              {cashDeletePending ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <Trash2 className="size-3.5" aria-hidden />
              )}
              <span className="sr-only">Delete cash transaction</span>
            </Button>
          ) : null}
        </div>
      </div>
    </button>
  );
}
