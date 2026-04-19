"use client";

import { abbreviateAccountDisplayName } from "@/lib/abbreviate-account-name";
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
  abbreviateAccountName = false,
  className,
}: {
  accountName?: string | null;
  mask?: string | null;
  owner?: string | null;
  /** "compact" omits the owner and uses smaller padding for dense tables. */
  variant?: "default" | "compact";
  /**
   * When true, common long product strings (e.g. "TOTAL CHECKING") are
   * shortened for on-screen width; the full name remains in `title`.
   */
  abbreviateAccountName?: boolean;
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
  const displayName = abbreviateAccountName
    ? abbreviateAccountDisplayName(accountName) || accountName?.trim() || "Account"
    : accountName?.trim() || "Account";
  return (
    <span
      className={cn(
        "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border border-border/70 bg-muted/40 px-2 py-0.5 text-xs",
        abbreviateAccountName &&
          "w-full min-w-0 flex-wrap gap-x-1 gap-y-0.5 px-1.5 text-[11px] leading-tight",
        compact ? "py-0" : "py-1",
        className,
      )}
      title={[accountName, mask ? `••${mask}` : null, owner ? `@${owner}` : null]
        .filter(Boolean)
        .join(" · ")}
    >
      <CreditCard
        className={cn("shrink-0 opacity-70", abbreviateAccountName ? "size-2.5" : "size-3")}
        aria-hidden
      />
      <span className="min-w-0 flex-1 truncate font-medium">{displayName}</span>
      {mask ? (
        <span className="shrink-0 tabular-nums text-muted-foreground">••{mask}</span>
      ) : null}
      {owner && !compact ? (
        <span className="shrink-0 text-muted-foreground">· @{owner}</span>
      ) : null}
    </span>
  );
}
