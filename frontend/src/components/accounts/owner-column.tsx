"use client";

import { useState } from "react";
import { UserRound } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Account, Member } from "@/types/v2";
import { AccountDetailDialog } from "./account-detail-dialog";
import { AccountTile } from "./account-tile";
import { CashWalletSection } from "./cash-wallet-section";
import { FlipCard } from "./flip-card";
import {
  formatMoney,
  isCardLikeAccount,
  isCashWalletShape,
  netWorthCents,
} from "./helpers";

// ---------------------------------------------------------------------------
// Section sub-block
// ---------------------------------------------------------------------------

/**
 * One section under an owner header.
 *
 * `layout="cards"` uses an auto-fit grid: cards reflow into 2 columns once
 * the parent owner-column is wide enough (~720px+), so on a 1920px screen
 * with 2 owners the cards wrap inside instead of leaving a huge gutter on
 * either side. Cards collapse back to a single column on narrow viewports.
 *
 * `layout="stack"` keeps list rows full-width — bank rows, loans, etc. read
 * as data tables and shouldn't wrap into 2 columns.
 */
function ColumnSection({
  title,
  layout = "stack",
  children,
}: {
  title: string;
  layout?: "stack" | "cards";
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      {layout === "cards" ? (
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(280px,1fr))]">
          {children}
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">{children}</div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function initialsOf(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase() ?? "")
      .join("") || "?"
  );
}

function OwnerHeader({
  name,
  accounts,
  isUnassigned,
}: {
  name: string;
  accounts: Account[];
  isUnassigned: boolean;
}) {
  const accountCount = accounts.length;
  const netCents = netWorthCents(accounts);
  const currency = accounts[0]?.currency ?? "USD";

  return (
    <header className="flex items-center gap-3 pb-1">
      <div
        className={cn(
          "flex size-11 shrink-0 items-center justify-center rounded-full text-sm font-bold shadow-sm ring-2 ring-border/60",
          isUnassigned
            ? "bg-muted text-muted-foreground"
            : "bg-gradient-to-br from-primary/25 to-primary/10 text-primary",
        )}
      >
        {isUnassigned ? (
          <UserRound className="size-5" />
        ) : (
          <span>{initialsOf(name)}</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <h2
          className={cn(
            "truncate text-xl font-semibold leading-tight sm:text-2xl",
            isUnassigned && "text-muted-foreground",
          )}
          title={name}
        >
          {name}
        </h2>
        <p className="text-xs text-muted-foreground tabular-nums">
          {accountCount} {accountCount === 1 ? "account" : "accounts"}
          <span className="mx-1.5 text-border">•</span>
          <span
            className={cn(
              "font-medium",
              netCents < 0 && "text-destructive",
            )}
          >
            Net {formatMoney(netCents, currency)}
          </span>
        </p>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Column
// ---------------------------------------------------------------------------

export function OwnerColumn({
  name,
  accounts,
  members,
  currentUser,
  isUnassigned = false,
}: {
  name: string;
  accounts: Account[];
  members: Member[];
  currentUser: { is_owner: boolean } | null;
  isUnassigned?: boolean;
}) {
  // Account-detail dialog state lives on the owner column so the dialog
  // is reused across every list section (banks, loans, investments) under
  // this owner. Click any non-cash bank-style row → dialog opens with the
  // account's recent activity + balances.
  const [detailAccount, setDetailAccount] = useState<Account | null>(null);

  // Partition accounts by the same rules the legacy page used.
  const creditCards = accounts.filter((a) => a.type === "credit");
  const debitCards = accounts.filter(
    (a) => a.type === "depository" && isCardLikeAccount(a),
  );
  const cashWallet = accounts.find((a) => a.is_cash_wallet) ?? null;
  const bankAccounts = accounts.filter(
    (a) =>
      a.type === "depository" &&
      !isCardLikeAccount(a) &&
      !a.is_cash_wallet &&
      !isCashWalletShape(a),
  );
  const loans = accounts.filter((a) => a.type === "loan");
  const investments = accounts.filter((a) => a.type === "investment");
  const other = accounts.filter((a) => a.type === "other");

  if (accounts.length === 0) return null;

  return (
    // Owner column stretches to its grid cell. Cards inside reflow via
    // an auto-fit grid (see ColumnSection layout="cards") — on a wide
    // viewport with few owners the cards pack into 2 columns inside the
    // owner block instead of leaving big side gutters; on narrow
    // viewports they fall back to a single column.
    <div className="flex w-full flex-col gap-4 rounded-2xl border border-border/60 bg-card/40 p-4 shadow-sm">
      <OwnerHeader name={name} accounts={accounts} isUnassigned={isUnassigned} />

      {creditCards.length > 0 && (
        <ColumnSection title="Credit Cards" layout="cards">
          {creditCards.map((account) => (
            <FlipCard
              key={account.id}
              account={account}
              members={members}
              currentUser={currentUser}
              size="compact"
            />
          ))}
        </ColumnSection>
      )}

      {debitCards.length > 0 && (
        <ColumnSection title="Debit Cards" layout="cards">
          {debitCards.map((account) => (
            <FlipCard
              key={account.id}
              account={account}
              members={members}
              currentUser={currentUser}
              size="compact"
            />
          ))}
        </ColumnSection>
      )}

      {bankAccounts.length > 0 && (
        <ColumnSection title="Cash & Bank Accounts">
          {bankAccounts.map((account) => (
            <AccountTile
              key={account.id}
              account={account}
              size="compact"
              onSelect={setDetailAccount}
            />
          ))}
        </ColumnSection>
      )}

      {loans.length > 0 && (
        <ColumnSection title="Loans">
          {loans.map((account) => (
            <AccountTile
              key={account.id}
              account={account}
              size="compact"
              onSelect={setDetailAccount}
            />
          ))}
        </ColumnSection>
      )}

      {investments.length > 0 && (
        <ColumnSection title="Investments">
          {investments.map((account) => (
            <AccountTile
              key={account.id}
              account={account}
              size="compact"
              onSelect={setDetailAccount}
            />
          ))}
        </ColumnSection>
      )}

      {other.length > 0 && (
        <ColumnSection title="Other Accounts">
          {other.map((account) => (
            <AccountTile
              key={account.id}
              account={account}
              size="compact"
              onSelect={setDetailAccount}
            />
          ))}
        </ColumnSection>
      )}

      {cashWallet && (
        <ColumnSection title="Cash Wallet">
          <CashWalletSection account={cashWallet} variant="compact" />
        </ColumnSection>
      )}

      {/* Detail dialog shared across every section above. */}
      <AccountDetailDialog
        account={detailAccount}
        open={detailAccount != null}
        onOpenChange={(v) => {
          if (!v) setDetailAccount(null);
        }}
      />
    </div>
  );
}
