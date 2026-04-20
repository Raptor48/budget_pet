"use client";

import type { Account } from "@/types/v2";
import { TYPE_COLORS, formatDate, formatMoney } from "./helpers";

// ---------------------------------------------------------------------------
// Institution logo (light variant, duplicated lean copy of flip-card's)
// ---------------------------------------------------------------------------

function InstitutionLogo({
  account,
  size = 36,
}: {
  account: Account;
  size?: number;
}) {
  if (account.institution_logo) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={`data:image/png;base64,${account.institution_logo}`}
        alt={account.name}
        width={size}
        height={size}
        style={{ width: size, height: size }}
        className="rounded-md object-contain"
      />
    );
  }
  const accentColor =
    account.institution_color ?? TYPE_COLORS[account.type] ?? TYPE_COLORS.other;
  const initials = (account.name || "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
  return (
    <div
      className="flex items-center justify-center rounded-md font-bold"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.38,
        backgroundColor: `${accentColor}22`,
        color: accentColor,
      }}
    >
      {initials}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Secondary info line (loan APR, depository availability, etc.)
// ---------------------------------------------------------------------------

function AccountTileSecondaryInfo({ account }: { account: Account }) {
  if (account.type === "loan") {
    const apr = account.apr_percent ?? account.apr_percent_manual;
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0">
        {apr != null && (
          <span className="text-xs text-muted-foreground">
            APR {apr}%
            {account.apr_percent == null && account.apr_percent_manual != null && (
              <span className="ml-1 rounded-full bg-muted px-1.5 py-0.5 text-[9px] font-semibold uppercase text-muted-foreground">
                Manual
              </span>
            )}
          </span>
        )}
        {account.min_payment_cents != null && (
          <span className="text-xs text-muted-foreground">
            Min {formatMoney(account.min_payment_cents, account.currency)}/mo
          </span>
        )}
        {account.expected_payoff_date && (
          <span className="text-xs text-muted-foreground">
            Payoff {formatDate(account.expected_payoff_date)}
          </span>
        )}
      </div>
    );
  }
  if (
    account.type === "depository" &&
    account.available_balance_cents != null &&
    account.available_balance_cents !== account.current_balance_cents
  ) {
    return (
      <span className="text-xs text-muted-foreground tabular-nums">
        {formatMoney(account.available_balance_cents, account.currency)} available
      </span>
    );
  }
  if (account.type === "investment") {
    return <span className="text-xs text-muted-foreground">Portfolio</span>;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Tile
// ---------------------------------------------------------------------------

export function AccountTile({
  account,
  size = "default",
}: {
  account: Account;
  size?: "default" | "compact";
}) {
  const compact = size === "compact";
  const accentColor =
    account.institution_color ?? TYPE_COLORS[account.type] ?? TYPE_COLORS.other;
  const name = account.official_name || account.name;
  const logoSize = compact ? 28 : 36;

  return (
    <div className="relative overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm transition-shadow hover:shadow-md">
      {/* Left accent bar */}
      <div
        className="absolute inset-y-0 left-0 w-1 rounded-l-xl"
        style={{ backgroundColor: accentColor }}
      />
      <div
        className={
          compact
            ? "flex items-center gap-2.5 py-2 pl-4 pr-3"
            : "flex items-center gap-3 py-3 pl-5 pr-4"
        }
      >
        <InstitutionLogo account={account} size={logoSize} />
        <div className="min-w-0 flex-1">
          <p
            className={
              compact
                ? "truncate text-[13px] font-semibold leading-snug"
                : "truncate text-sm font-semibold leading-snug"
            }
            title={name}
          >
            {name}
          </p>
          <div className="flex items-center gap-1.5">
            {account.mask && (
              <span className="font-mono text-[11px] text-muted-foreground">
                •••• {account.mask}
              </span>
            )}
            <span
              className="rounded-full px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide"
              style={{
                backgroundColor: `${accentColor}22`,
                color: accentColor,
              }}
            >
              {(account.subtype || account.type).replaceAll("_", " ")}
            </span>
          </div>
          {!compact && <AccountTileSecondaryInfo account={account} />}
        </div>
        <div className="shrink-0 text-right">
          <p
            className={
              compact
                ? "text-[13px] font-bold tabular-nums"
                : "font-bold tabular-nums"
            }
          >
            {formatMoney(account.current_balance_cents, account.currency)}
          </p>
          {account.owner_username && !compact && (
            <p className="text-[10px] text-muted-foreground">
              {account.owner_username}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
