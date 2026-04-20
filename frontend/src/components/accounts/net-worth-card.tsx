"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AnimatedMoney } from "@/components/ui/animated-money";
import { cn } from "@/lib/utils";
import type { Account } from "@/types/v2";
import { netWorthCents, sumBalance } from "./helpers";

export function NetWorthCard({ accounts }: { accounts: Account[] }) {
  const netCents = netWorthCents(accounts);
  const primaryCurrency = accounts[0]?.currency ?? "USD";
  const hasMixedCurrencies =
    new Set(accounts.map((a) => a.currency.toUpperCase())).size > 1;

  const depository = sumBalance(accounts.filter((a) => a.type === "depository"));
  const credit = sumBalance(accounts.filter((a) => a.type === "credit"));
  const loans = sumBalance(accounts.filter((a) => a.type === "loan"));
  const investments = sumBalance(accounts.filter((a) => a.type === "investment"));

  return (
    <Card className="hero-glow">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Net Worth</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p
          className={cn(
            "text-3xl font-bold tracking-tight",
            netCents < 0 && "text-destructive",
          )}
        >
          <AnimatedMoney cents={netCents} currency={primaryCurrency} />
          {hasMixedCurrencies && (
            <span className="ml-2 text-sm font-normal text-amber-600 dark:text-amber-400">
              (mixed currencies, approx.)
            </span>
          )}
        </p>
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {[
            { label: "Checking/Savings", value: depository, positive: true },
            { label: "Investments", value: investments, positive: true },
            { label: "Credit cards", value: credit, positive: false },
            { label: "Loans", value: loans, positive: false },
          ].map(({ label, value, positive }) => (
            <div key={label}>
              <p className="text-muted-foreground text-xs">{label}</p>
              <AnimatedMoney
                cents={value}
                currency={primaryCurrency}
                as="p"
                className={cn(
                  "font-semibold",
                  !positive && value > 0 ? "text-destructive" : "",
                )}
              />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
