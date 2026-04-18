"use client";

import { cn } from "@/lib/utils";
import { CreditCard } from "lucide-react";

/**
 * Compact pill that identifies WHO is charged for a transaction/recurring stream.
 * Shows: account name, last-4 mask, and optionally the owner username.
 *
 * Intentionally display-only — clicking does nothing; upstream pages can wrap
 * it in a link (e.g. to /accounts) if needed.
 */
export function AccountChip({
  accountName,
  mask,
  owner,
  variant = "default",
  className,
}: {
  accountName?: string | null;
  mask?: string | null;
  owner?: string | null;
  /** "compact" omits the owner and uses smaller padding for dense tables. */
  variant?: "default" | "compact";
  className?: string;
}) {
  const hasName = Boolean(accountName?.trim());
  const hasAny = hasName || Boolean(mask) || Boolean(owner);
  if (!hasAny) {
    return (
      <span className={cn("text-muted-foreground text-xs italic", className)}>—</span>
    );
  }
  const compact = variant === "compact";
  return (
    <span
      className={cn(
        "inline-flex min-w-0 items-center gap-1.5 rounded-md border border-border/70 bg-muted/40 px-2 py-0.5 text-xs",
        compact ? "py-0" : "py-1",
        className,
      )}
      title={[accountName, mask ? `••${mask}` : null, owner ? `@${owner}` : null]
        .filter(Boolean)
        .join(" · ")}
    >
      <CreditCard className="size-3 shrink-0 opacity-70" aria-hidden />
      <span className="truncate font-medium">
        {accountName?.trim() || "Account"}
      </span>
      {mask ? (
        <span className="shrink-0 tabular-nums text-muted-foreground">••{mask}</span>
      ) : null}
      {owner && !compact ? (
        <span className="shrink-0 text-muted-foreground">· @{owner}</span>
      ) : null}
    </span>
  );
}
