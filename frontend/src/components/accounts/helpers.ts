import type { Account } from "@/types/v2";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

export function formatMoney(cents: number, currency = "USD"): string {
  const code = (currency || "USD").trim().toUpperCase() || "USD";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(cents / 100);
  } catch {
    return `$${(cents / 100).toLocaleString("en-US", { minimumFractionDigits: 2 })} ${code}`;
  }
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export function formatSyncedAt(iso: string | null): string {
  if (!iso) return "Never synced";
  try {
    return new Date(iso).toLocaleString("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

export const TYPE_COLORS: Record<string, string> = {
  depository: "#1a56db",
  credit: "#7e3af2",
  loan: "#b45309",
  investment: "#057a55",
  other: "#374151",
};

function hexToRgb(hex: string): [number, number, number] | null {
  const clean = hex.replace(/^#/, "");
  if (clean.length !== 6) return null;
  return [
    parseInt(clean.slice(0, 2), 16),
    parseInt(clean.slice(2, 4), 16),
    parseInt(clean.slice(4, 6), 16),
  ];
}

export function lighten(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const [r, g, b] = rgb.map((c) =>
    Math.min(255, Math.round(c + (255 - c) * amount)),
  );
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b
    .toString(16)
    .padStart(2, "0")}`;
}

export function darken(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const [r, g, b] = rgb.map((c) => Math.max(0, Math.round(c * (1 - amount))));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b
    .toString(16)
    .padStart(2, "0")}`;
}

export function cardGradient(baseColor: string): string {
  const dark = darken(baseColor, 0.35);
  const light = lighten(baseColor, 0.15);
  return `linear-gradient(135deg, ${dark} 0%, ${baseColor} 45%, ${light} 100%)`;
}

// ---------------------------------------------------------------------------
// Account grouping helpers
// ---------------------------------------------------------------------------

export function sumBalance(accounts: Account[]): number {
  return accounts.reduce((s, a) => s + a.current_balance_cents, 0);
}

export function netWorthCents(accounts: Account[]): number {
  const by = (t: string) => accounts.filter((a) => a.type === t);
  return (
    sumBalance(by("depository")) -
    sumBalance(by("credit")) -
    sumBalance(by("loan")) +
    sumBalance(by("investment"))
  );
}

/** Credit cards and depository accounts that Plaid marks as card-like (subtype contains "card"). */
export function isCardLikeAccount(a: Account): boolean {
  if (a.type === "credit") return true;
  const st = (a.subtype || "").toLowerCase();
  if (a.type === "depository" && st.includes("card")) return true;
  return false;
}

/** Same identity as backend cash wallet row (active or soft-deleted). Must not appear as a generic tile. */
export function isCashWalletShape(a: Account): boolean {
  return (
    a.name === "Cash" &&
    a.type === "depository" &&
    (a.subtype ?? "") === "cash" &&
    (a.plaid_account_id == null || a.plaid_account_id === "")
  );
}
