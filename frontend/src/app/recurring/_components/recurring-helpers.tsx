/**
 * Pure helpers + tiny presentational components shared by the Recurring page
 * surface. Keeps `page.tsx` focused on layout / data wiring.
 */
"use client";

import Image from "next/image";
import { useState } from "react";

import { cn } from "@/lib/utils";
import { normalizeTransactionTitle } from "@/lib/transaction-display";
import type { RecurringStream } from "@/types/v2";

/** Threshold above which `price_change_pct` is surfaced. */
export const PRICE_CHANGE_THRESHOLD_PCT = 10;

/** Default snooze window (days) for a price-change alert. */
export const SNOOZE_DAYS_DEFAULT = 30;

// ---------------------------------------------------------------------------
// Pure formatters
// ---------------------------------------------------------------------------

export function formatFrequency(f: string | null | undefined): string {
  if (!f) return "—";
  return f.replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export function parsePriceChangePct(raw: string | null | undefined): number | null {
  if (raw == null || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/**
 * Pick the best stream title — prefers the user-edited label, then the backend
 * normalized `display_title`, then the local title-normalizer as a fallback.
 */
export function streamTitle(stream: RecurringStream): string {
  const ul = stream.user_label?.trim();
  if (ul) return ul;
  const backendNorm = stream.display_title?.trim();
  if (backendNorm) return backendNorm;
  return normalizeTransactionTitle({
    merchant_name: stream.merchant_name,
    name: stream.description,
    description: stream.description,
  });
}

/**
 * Convert a stream's average per-period cents into a *monthly* equivalent.
 * Used by the KPI summary so we can sum across mixed cadences.
 *
 * Returns 0 for streams with missing data or unknown cadence — KPI sums
 * are always lower bounds, never inflated by guesses.
 */
export function monthlyCostCents(stream: RecurringStream): number {
  const cents = stream.average_amount_cents;
  if (cents == null) return 0;
  const freq = (stream.frequency || "").toUpperCase();
  switch (freq) {
    case "WEEKLY":
      return Math.round(cents * (52 / 12));
    case "BIWEEKLY":
      return Math.round(cents * (26 / 12));
    case "SEMI_MONTHLY":
      return cents * 2;
    case "MONTHLY":
      return cents;
    case "ANNUALLY":
      return Math.round(cents / 12);
    default:
      return 0;
  }
}

export function annualCostCents(stream: RecurringStream): number {
  return monthlyCostCents(stream) * 12;
}

/** Lightweight wallet-style account label, e.g. "•5993 · @Denis". */
export function accountTag(stream: RecurringStream): string {
  const mask = stream.account_mask ? `··${stream.account_mask}` : "";
  const owner = stream.owner_username ? `@${stream.owner_username}` : "";
  if (mask && owner) return `${mask} · ${owner}`;
  return mask || owner || "";
}

// ---------------------------------------------------------------------------
// Merchant avatar (gradient fallback, deterministic by merchant key)
// ---------------------------------------------------------------------------

const MERCHANT_GRADIENTS = [
  "from-rose-500 to-pink-500",
  "from-orange-500 to-amber-500",
  "from-yellow-500 to-lime-500",
  "from-emerald-500 to-teal-500",
  "from-cyan-500 to-sky-500",
  "from-blue-500 to-indigo-500",
  "from-violet-500 to-fuchsia-500",
  "from-fuchsia-500 to-rose-500",
] as const;

function pickGradient(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  }
  return MERCHANT_GRADIENTS[Math.abs(hash) % MERCHANT_GRADIENTS.length];
}

function initials(name: string): string {
  const cleaned = name.trim();
  if (!cleaned) return "?";
  const parts = cleaned.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return ((parts[0]![0] ?? "") + (parts[1]![0] ?? "")).toUpperCase();
}

/**
 * Avatar for a recurring stream — Plaid does not return logos on the
 * recurring endpoint, so we always render the deterministic gradient
 * fallback (same algorithm as MerchantAvatar in transactions/page.tsx).
 *
 * If a future enhancement joins streams to a transaction logo, accept an
 * optional `logoUrl` and fall back gracefully — already wired below.
 */
export function StreamAvatar({
  stream,
  logoUrl,
  size = 40,
}: {
  stream: RecurringStream;
  logoUrl?: string | null;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const name = streamTitle(stream);
  const seed =
    (stream.merchant_name || name || "?")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "") || "?";
  const gradient = pickGradient(seed);
  const showImg = Boolean(logoUrl) && !failed;
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-full text-sm font-semibold",
        showImg
          ? "border border-border bg-muted text-muted-foreground"
          : `bg-gradient-to-br text-white shadow-sm ${gradient}`,
      )}
      style={{ width: size, height: size }}
    >
      {showImg ? (
        <Image
          src={logoUrl!}
          alt=""
          width={size}
          height={size}
          className="size-full object-cover"
          onError={() => setFailed(true)}
          unoptimized
        />
      ) : (
        <span className="leading-none drop-shadow-sm">{initials(name)}</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// User-status pill
// ---------------------------------------------------------------------------

export function effectiveUserStatus(
  stream: RecurringStream,
): "active" | "paused" | "unsubscribed" | "cancelled" {
  return stream.user_status ?? "active";
}

export function UserStatusPill({
  status,
  className,
}: {
  status: "active" | "paused" | "unsubscribed" | "cancelled";
  className?: string;
}) {
  if (status === "active") return null;
  const map = {
    paused:
      "border-amber-500/50 bg-amber-500/10 text-amber-800 dark:text-amber-200",
    // `unsubscribed` is a pending-verification state — sky/blue reads as
    // "in flight" rather than the terminal grey of `cancelled`.
    unsubscribed:
      "border-sky-500/50 bg-sky-500/10 text-sky-700 dark:text-sky-200",
    cancelled:
      "border-muted-foreground/40 bg-muted text-muted-foreground",
  } as const;
  const label =
    status === "paused"
      ? "Paused"
      : status === "unsubscribed"
        ? "Unsubscribing"
        : "Cancelled";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        map[status],
        className,
      )}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Snooze helpers
// ---------------------------------------------------------------------------

export function isSnoozedNow(stream: RecurringStream): boolean {
  const until = stream.price_change_snoozed_until;
  if (!until) return false;
  const d = new Date(`${until}T00:00:00`);
  if (Number.isNaN(d.getTime())) return false;
  return d.getTime() >= Date.now();
}
