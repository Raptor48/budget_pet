/**
 * Display helpers for Plaid transaction `amount` values stored as integer cents.
 *
 * Plaid convention (Transactions product, not Income):
 * - Positive amount → money moves **out** of the account (debit / spend / payment from account).
 * - Negative amount → money moves **in** (credit / deposit / refund).
 *
 * @see https://plaid.com/docs/api/products/transactions/ — field `amount`
 *
 * We do **not** change stored `amount_cents`; only the user-visible string is adjusted.
 *
 * Rollback: set `NEXT_PUBLIC_PLAID_TXN_SIGNED_DISPLAY=false` (or `0` / `off`) in `.env.local`
 * and restart `next dev` / rebuild.
 */

const LEGACY_FALSE = new Set(["false", "0", "off", "no"]);

export function isPlaidSignedTxnDisplayEnabled(): boolean {
  const raw = process.env.NEXT_PUBLIC_PLAID_TXN_SIGNED_DISPLAY;
  if (raw == null || raw.trim() === "") return true;
  return !LEGACY_FALSE.has(raw.trim().toLowerCase());
}

export function isPlaidTxnOutflowCents(cents: number): boolean {
  return cents > 0;
}

export function isPlaidTxnInflowCents(cents: number): boolean {
  return cents < 0;
}

function formatCurrencyUnsigned(cents: number, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: "never",
  }).format(Math.abs(cents) / 100);
}

/** Raw Intl formatting of cents/100 (legacy UI: keeps API sign on the number). */
export function formatPlaidTxnAmountLegacy(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

/**
 * Formats a Plaid-style signed amount for lists and dialogs:
 * - Outflow (positive cents): `-` + absolute currency (expense tone in UI).
 * - Inflow (negative cents): `+` + absolute currency (income tone in UI).
 * - Zero: unsigned `$0.00`.
 */
export function formatPlaidTxnAmountForDisplay(cents: number, currency = "USD"): string {
  if (!isPlaidSignedTxnDisplayEnabled()) {
    return formatPlaidTxnAmountLegacy(cents, currency);
  }
  const core = formatCurrencyUnsigned(cents, currency);
  if (cents > 0) return `-${core}`;
  if (cents < 0) return `+${core}`;
  return core;
}
