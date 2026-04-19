/**
 * Canonical label formatter for account / card pickers across the app.
 *
 * We always prepend the owner when we know it (joined from `users.username`
 * via `accounts.user_id` or the fallback on `plaid_items.user_id`) so the
 * picker makes sense even in single-user families today and keeps working
 * once a second member joins without any UI change. The separator mirrors
 * the middle-dot convention used elsewhere (Select triggers, transaction
 * rows).
 *
 * Format: `Owner · AccountName [· ····mask]`
 *
 * Rules:
 *  - Owner is skipped only when `owner_username` is unknown (happens for
 *    legacy rows where the plaid_items fallback didn't resolve yet).
 *  - Mask is skipped when null/empty (cash wallets, some investment
 *    accounts) — there's no stable last-4 to show.
 *  - Whitespace is collapsed and trimmed so consumers can safely feed
 *    partial objects without generating orphan separators.
 */
import type { Account } from "@/types/v2";

export function formatAccountPickerLabel(
  account: Pick<Account, "name" | "mask" | "owner_username">,
): string {
  const parts: string[] = [];

  const owner = account.owner_username?.trim();
  if (owner) parts.push(owner);

  const name = account.name?.trim();
  if (name) parts.push(name);

  const mask = account.mask?.trim();
  if (mask) parts.push(`····${mask}`);

  return parts.join(" · ");
}
