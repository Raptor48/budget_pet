import { formatPlaidTxnAmountForDisplay, isPlaidTxnInflowCents, isPlaidTxnOutflowCents } from "@/lib/plaid-transaction-amount";
import { cn } from "@/lib/utils";

export type PlaidTxnAmountSize = "sm" | "base" | "inherit";

export type PlaidTxnAmountTone = "flow" | "muted" | "neutral";

const sizeClass: Record<PlaidTxnAmountSize, string> = {
  sm: "text-sm font-semibold",
  base: "text-base font-semibold",
  inherit: "font-semibold",
};

type PlaidTxnAmountProps = {
  cents: number;
  currency?: string;
  className?: string;
  size?: PlaidTxnAmountSize;
  /** flow: red outflow / green inflow (Plaid transaction cents). muted|neutral: no flow colors */
  tone?: PlaidTxnAmountTone;
};

/**
 * Renders a Plaid-style transaction amount with optional flow coloring.
 * Values follow Plaid Transactions: positive = outflow, negative = inflow.
 */
export function PlaidTxnAmount({
  cents,
  currency = "USD",
  className,
  size = "inherit",
  tone = "flow",
}: PlaidTxnAmountProps) {
  const label = formatPlaidTxnAmountForDisplay(cents, currency);

  const toneClass =
    tone === "muted"
      ? "text-muted-foreground"
      : tone === "neutral"
        ? "text-foreground"
        : cn(
            isPlaidTxnOutflowCents(cents) && "text-red-600 dark:text-red-400",
            isPlaidTxnInflowCents(cents) && "text-emerald-600 dark:text-emerald-400",
            cents === 0 && "text-muted-foreground",
          );

  return (
    <span className={cn("tabular-nums", sizeClass[size], toneClass, className)} title={label}>
      {label}
    </span>
  );
}
