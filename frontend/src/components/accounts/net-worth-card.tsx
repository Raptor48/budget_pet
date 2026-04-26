"use client";

import { Card, CardContent } from "@/components/ui/card";
import { AnimatedMoney } from "@/components/ui/animated-money";
import { cn } from "@/lib/utils";
import type { Account } from "@/types/v2";
import { netWorthCents, sumBalance } from "./helpers";

/**
 * Compact net-worth bar on the Accounts page header.
 *
 * Shape changes from the previous hero version:
 *   - Title is inlined alongside the headline number (no separate header row)
 *   - Headline shrunk from text-3xl to text-2xl so the bar reads as a summary
 *     row, not as the page's hero
 *   - Sub-tiles are filtered: zero-balance categories drop out entirely so we
 *     don't reserve space for "Investments $0.00" when the user has none
 *   - Single-line layout — labels live next to their values, not above
 */
export function NetWorthCard({ accounts }: { accounts: Account[] }) {
  const netCents = netWorthCents(accounts);
  const primaryCurrency = accounts[0]?.currency ?? "USD";
  const hasMixedCurrencies =
    new Set(accounts.map((a) => a.currency.toUpperCase())).size > 1;

  const depository = sumBalance(accounts.filter((a) => a.type === "depository"));
  const credit = sumBalance(accounts.filter((a) => a.type === "credit"));
  const loans = sumBalance(accounts.filter((a) => a.type === "loan"));
  const investments = sumBalance(accounts.filter((a) => a.type === "investment"));

  const tiles = [
    { label: "Checking & savings", value: depository, debt: false },
    { label: "Investments", value: investments, debt: false },
    { label: "Credit cards", value: credit, debt: true },
    { label: "Loans", value: loans, debt: true },
  ].filter((t) => t.value !== 0);

  return (
    <Card className="hero-glow">
      <CardContent className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-baseline gap-3">
          <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            Net worth
          </span>
          <p
            className={cn(
              "text-2xl font-bold tracking-tight tabular-nums",
              netCents < 0 && "text-destructive",
            )}
          >
            <AnimatedMoney cents={netCents} currency={primaryCurrency} />
          </p>
          {hasMixedCurrencies && (
            <span className="text-[11px] font-medium text-amber-600 dark:text-amber-400">
              mixed currencies
            </span>
          )}
        </div>
        {tiles.length > 0 ? (
          <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
            {tiles.map((t) => (
              <li
                key={t.label}
                className="flex items-baseline gap-1.5 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300"
              >
                <span className="text-xs text-muted-foreground">{t.label}</span>
                <AnimatedMoney
                  cents={t.value}
                  currency={primaryCurrency}
                  as="span"
                  className={cn(
                    "font-semibold tabular-nums",
                    t.debt && t.value > 0 && "text-destructive",
                  )}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
