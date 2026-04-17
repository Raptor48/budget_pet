"use client";

import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Trash2, UserRound, Wallet } from "lucide-react";
import { useAuth } from "@/contexts/auth-context";
import { AppLayout } from "@/components/layout/app-layout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { accountsApi, membersApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Account, Member } from "@/types/v2";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatMoney(cents: number, currency = "USD"): string {
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

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function formatSyncedAt(iso: string | null): string {
  if (!iso) return "Never synced";
  try {
    return new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

const TYPE_COLORS: Record<string, string> = {
  depository: "#1a56db",
  credit:     "#7e3af2",
  loan:       "#b45309",
  investment: "#057a55",
  other:      "#374151",
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

function lighten(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const [r, g, b] = rgb.map((c) => Math.min(255, Math.round(c + (255 - c) * amount)));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

function darken(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const [r, g, b] = rgb.map((c) => Math.max(0, Math.round(c * (1 - amount))));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

function cardGradient(baseColor: string): string {
  const dark = darken(baseColor, 0.35);
  const light = lighten(baseColor, 0.15);
  return `linear-gradient(135deg, ${dark} 0%, ${baseColor} 45%, ${light} 100%)`;
}

// ---------------------------------------------------------------------------
// Net worth helpers
// ---------------------------------------------------------------------------

function sumBalance(accounts: Account[]): number {
  return accounts.reduce((s, a) => s + a.current_balance_cents, 0);
}

function netWorthCents(accounts: Account[]): number {
  const by = (t: string) => accounts.filter((a) => a.type === t);
  return (
    sumBalance(by("depository")) -
    sumBalance(by("credit")) -
    sumBalance(by("loan")) +
    sumBalance(by("investment"))
  );
}

function groupByType(accounts: Account[]) {
  const order = ["depository", "credit", "loan", "investment", "other"] as const;
  const buckets: Record<string, Account[]> = {};
  for (const t of order) buckets[t] = [];
  for (const a of accounts) {
    const key = order.includes(a.type as (typeof order)[number]) ? (a.type as (typeof order)[number]) : "other";
    buckets[key].push(a);
  }
  for (const t of order) buckets[t].sort((x, y) => x.name.localeCompare(y.name));
  return buckets;
}

/** Credit cards and depository accounts that Plaid marks as card-like (subtype contains "card"). */
function isCardLikeAccount(a: Account): boolean {
  if (a.type === "credit") return true;
  const st = (a.subtype || "").toLowerCase();
  if (a.type === "depository" && st.includes("card")) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Card face content components
// ---------------------------------------------------------------------------

interface FaceProps {
  account: Account;
  color: string;
}

function InstitutionLogo({
  account,
  size = 36,
  variant = "dark",
}: {
  account: Account;
  size?: number;
  /** "dark" = used on gradient card face; "light" = used on light card background */
  variant?: "dark" | "light";
}) {
  if (account.institution_logo) {
    return (
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
  if (variant === "light") {
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
  return (
    <div
      className="flex items-center justify-center rounded-md bg-white/20 text-white font-bold"
      style={{ width: size, height: size, fontSize: size * 0.38 }}
    >
      {initials}
    </div>
  );
}

function TypeLabel({ type }: { type: string }) {
  const labels: Record<string, string> = {
    depository: "Checking / Savings",
    credit:     "Credit Card",
    loan:       "Loan",
    investment: "Investment",
    other:      "Account",
  };
  return (
    <span className="rounded-full bg-white/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-widest text-white/90">
      {labels[type] ?? type}
    </span>
  );
}

function ChipIcon() {
  return (
    <svg viewBox="0 0 38 28" width="38" height="28" className="opacity-80">
      <rect x="0" y="0" width="38" height="28" rx="4" fill="rgba(255,255,255,0.25)" />
      <rect x="0" y="9" width="38" height="10" fill="rgba(255,255,255,0.12)" />
      <rect x="13" y="0" width="12" height="28" fill="rgba(255,255,255,0.12)" />
      <rect x="13" y="9" width="12" height="10" fill="rgba(255,255,255,0.18)" />
    </svg>
  );
}

function CardFront({ account, color }: FaceProps) {
  const name = account.official_name || account.name;
  const mask = account.mask ? `•••• ${account.mask}` : null;
  const isDebt = account.type === "credit" || account.type === "loan";

  return (
    <div
      className="absolute inset-0 flex flex-col justify-between overflow-hidden rounded-2xl p-5 text-white"
      style={{
        background: cardGradient(color),
        backfaceVisibility: "hidden",
        WebkitBackfaceVisibility: "hidden",
      }}
    >
      {/* Decorative circle */}
      <div
        className="pointer-events-none absolute -right-12 -top-12 rounded-full bg-white/10"
        style={{ width: 180, height: 180 }}
      />
      <div
        className="pointer-events-none absolute -bottom-10 -left-10 rounded-full bg-white/5"
        style={{ width: 140, height: 140 }}
      />

      {/* Top row */}
      <div className="relative flex items-start justify-between">
        <InstitutionLogo account={account} size={40} />
        <TypeLabel type={account.type} />
      </div>

      {/* Middle: chip + account label */}
      <div className="relative flex items-end justify-between">
        {account.type === "credit" ? <ChipIcon /> : <div />}
        <p className="max-w-[60%] truncate text-right text-sm font-medium text-white/80" title={name}>
          {name}
        </p>
      </div>

      {/* Bottom row */}
      <div className="relative flex items-end justify-between">
        <div>
          {mask ? (
            <p className="font-mono text-base tracking-widest text-white/90">{mask}</p>
          ) : (
            <p className="text-xs text-white/60 italic">No card number</p>
          )}
          <div className="mt-1 flex items-center gap-1.5">
            <OwnerBadge username={account.owner_username} />
            <p className="text-[10px] text-white/50">Tap for details</p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-[10px] uppercase tracking-widest text-white/60">
            {isDebt ? "Balance" : "Current"}
          </p>
          <p className="text-xl font-bold tabular-nums">
            {formatMoney(account.current_balance_cents, account.currency)}
          </p>
        </div>
      </div>
    </div>
  );
}

function UtilizationBar({ account }: { account: Account }) {
  const limit = account.credit_limit_cents;
  if (limit == null || limit <= 0) return <p className="text-white/50 text-xs">No credit limit on file</p>;
  const pct = (account.current_balance_cents / limit) * 100;
  const capped = Math.min(pct, 100);
  const barColor = pct < 30 ? "#22c55e" : pct <= 75 ? "#f59e0b" : "#ef4444";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[11px] text-white/70">
        <span>Utilization</span>
        <span className="font-semibold text-white">{pct.toFixed(1)}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/20">
        <div className="h-full rounded-full transition-all" style={{ width: `${capped}%`, backgroundColor: barColor }} />
      </div>
    </div>
  );
}

function CardBack({
  account,
  color,
  members,
  currentUser,
  onFlipBack,
}: FaceProps & {
  members: Member[];
  currentUser: { is_owner: boolean } | null;
  onFlipBack: () => void;
}) {
  const isCreditLike = account.type === "credit" || account.type === "loan";
  const isInvestment = account.type === "investment";
  const isDepository = account.type === "depository";

  return (
    <div
      className="absolute inset-0 flex flex-col justify-between overflow-hidden rounded-2xl p-4 text-white"
      style={{
        background: cardGradient(darken(color, 0.1)),
        backfaceVisibility: "hidden",
        WebkitBackfaceVisibility: "hidden",
        transform: "rotateY(180deg)",
      }}
      // Stop all clicks here so they don't bubble to the flip container
      onClick={(e) => e.stopPropagation()}
    >
      {/* Decorative stripe */}
      <div className="absolute left-0 right-0 top-7 h-7 bg-black/30" />

      {/* Header */}
      <div className="relative flex items-center justify-between pt-7">
        <p className="text-[11px] uppercase tracking-widest text-white/60">Details</p>
        <button
          type="button"
          className="flex items-center gap-1 rounded-full bg-white/20 px-2.5 py-0.5 text-[11px] font-medium text-white hover:bg-white/30 active:bg-white/40"
          onClick={onFlipBack}
        >
          ← Back
        </button>
      </div>

      {/* Financial details by account type */}
      <div className="relative flex flex-col gap-1.5">
        {isCreditLike && (
          <>
            <UtilizationBar account={account} />
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
              <div>
                <p className="text-white/50">Limit</p>
                <p className="font-semibold text-white tabular-nums">
                  {account.credit_limit_cents != null ? formatMoney(account.credit_limit_cents, account.currency) : "—"}
                </p>
              </div>
              <div>
                <p className="text-white/50">APR</p>
                <p className="font-semibold text-white tabular-nums">
                  {account.apr_percent != null ? `${account.apr_percent}%` : "—"}
                </p>
              </div>
              <div>
                <p className="text-white/50">Min payment</p>
                <p className="font-semibold text-white tabular-nums">
                  {account.min_payment_cents != null ? formatMoney(account.min_payment_cents, account.currency) : "—"}
                </p>
              </div>
              <div>
                <p className="text-white/50">Due day</p>
                <p className="font-semibold text-white tabular-nums">
                  {account.due_day != null ? `Day ${account.due_day}` : "—"}
                </p>
              </div>
            </div>
            {account.is_overdue && (
              <span className="w-fit rounded-full bg-red-500/30 px-2 py-0.5 text-[10px] font-bold text-red-300">
                OVERDUE
              </span>
            )}
          </>
        )}
        {isInvestment && (
          <div className="text-[11px]">
            <p className="text-white/50">Portfolio value</p>
            <p className="font-semibold text-white tabular-nums">
              {formatMoney(account.current_balance_cents, account.currency)}
            </p>
          </div>
        )}
        {isDepository && (
          <div className="grid grid-cols-2 gap-x-4 text-[11px]">
            <div>
              <p className="text-white/50">Available</p>
              <p className="font-semibold text-white tabular-nums">
                {account.available_balance_cents != null
                  ? formatMoney(account.available_balance_cents, account.currency)
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-white/50">Currency</p>
              <p className="font-semibold text-white">{account.currency}</p>
            </div>
          </div>
        )}
      </div>

      {/* Owner section — always visible, prominent */}
      <div className="relative rounded-xl border border-white/15 bg-black/20 px-3 py-2">
        <OwnerSelector account={account} members={members} currentUser={currentUser} />
      </div>

      {/* Footer: last synced */}
      <p className="relative text-[10px] text-white/40">
        Synced: {formatSyncedAt(account.last_synced_at)}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Owner badge (shown on front face)
// ---------------------------------------------------------------------------

function OwnerBadge({ username }: { username: string | null }) {
  if (!username) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-black/25 px-2 py-0.5 text-[10px] font-medium text-white/90 backdrop-blur-sm">
      <UserRound className="size-2.5 shrink-0" />
      {username}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Owner reassign selector (shown on back face, owner-only)
// ---------------------------------------------------------------------------

function OwnerSelector({
  account,
  members,
  currentUser,
}: {
  account: Account;
  members: Member[];
  currentUser: { is_owner: boolean } | null;
}) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (userId: number | null) => accountsApi.assignOwner(account.id, userId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["v2-accounts"] });
      void queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  const label = (
    <p className="mb-1.5 flex items-center gap-1 text-[10px] uppercase tracking-widest text-white/50">
      <UserRound className="size-3" />
      Owner
    </p>
  );

  // Still loading — show skeleton
  if (currentUser === null) {
    return (
      <div>
        {label}
        <p className="text-sm text-white/40 italic">Loading…</p>
      </div>
    );
  }

  // Non-owner users: read-only view
  if (!currentUser.is_owner) {
    return (
      <div>
        {label}
        <p className="text-sm font-semibold text-white">
          {account.owner_username ?? "Unassigned"}
        </p>
      </div>
    );
  }

  // Owner: editable dropdown
  const NONE = "__none__";
  const current = account.user_id != null ? String(account.user_id) : NONE;

  return (
    <div>
      {label}
      <Select
        value={current}
        onValueChange={(v) => {
          const uid = v === NONE ? null : Number(v);
          mutation.mutate(uid);
        }}
        disabled={mutation.isPending || members.length === 0}
      >
        <SelectTrigger
          className="h-8 w-full border-white/25 bg-white/15 text-sm font-semibold text-white hover:bg-white/25 focus:ring-white/30"
          onClick={(e) => e.stopPropagation()}
        >
          <SelectValue placeholder={members.length === 0 ? "No users yet…" : "Assign owner…"} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE} className="text-sm text-muted-foreground">
            Unassigned
          </SelectItem>
          {members.map((m) => (
            <SelectItem key={m.id} value={String(m.id)} className="text-sm">
              {m.username}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {mutation.isPending && (
        <p className="mt-1 text-[10px] text-white/50">Saving…</p>
      )}
      {mutation.isSuccess && (
        <p className="mt-1 text-[10px] text-emerald-300">Saved ✓</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Flip card wrapper
// ---------------------------------------------------------------------------

function FlipCard({
  account,
  members,
  currentUser,
}: {
  account: Account;
  members: Member[];
  currentUser: { is_owner: boolean } | null;
}) {
  const [flipped, setFlipped] = useState(false);
  const color = account.institution_color ?? TYPE_COLORS[account.type] ?? TYPE_COLORS.other;

  return (
    <div
      className="w-full cursor-pointer select-none"
      style={{ perspective: "1000px" }}
      onClick={() => setFlipped((f) => !f)}
      role="button"
      tabIndex={0}
      aria-label={`${account.name} — tap to ${flipped ? "see front" : "see details"}`}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setFlipped((f) => !f); }}
    >
      <div
        className="relative w-full transition-transform duration-500"
        style={{
          aspectRatio: "85.6 / 54",
          transformStyle: "preserve-3d",
          transform: flipped ? "rotateY(180deg)" : "rotateY(0deg)",
        }}
      >
        <CardFront account={account} color={color} />
        <CardBack
          account={account}
          color={color}
          members={members}
          currentUser={currentUser}
          onFlipBack={() => setFlipped(false)}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section components
// ---------------------------------------------------------------------------

const SECTION_TITLES: Record<string, string> = {
  depository: "Checking & Savings",
  credit:     "Credit Cards",
  loan:       "Loans",
  investment: "Investments",
  other:      "Other Accounts",
};

function AccountTileSecondaryInfo({ account }: { account: Account }) {
  if (account.type === "loan") {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0">
        {account.apr_percent != null && (
          <span className="text-xs text-muted-foreground">APR {account.apr_percent}%</span>
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

function AccountTile({ account }: { account: Account }) {
  const accentColor =
    account.institution_color ?? TYPE_COLORS[account.type] ?? TYPE_COLORS.other;
  const name = account.official_name || account.name;

  return (
    <div className="relative overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm transition-shadow hover:shadow-md">
      {/* Left accent bar */}
      <div
        className="absolute inset-y-0 left-0 w-1 rounded-l-xl"
        style={{ backgroundColor: accentColor }}
      />
      <div className="flex items-center gap-3 py-3 pl-5 pr-4">
        <InstitutionLogo account={account} size={36} variant="light" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold leading-snug" title={name}>
            {name}
          </p>
          <div className="flex items-center gap-1.5">
            {account.mask && (
              <span className="font-mono text-xs text-muted-foreground">
                •••• {account.mask}
              </span>
            )}
            <span
              className="rounded-full px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide"
              style={{
                backgroundColor: `${accentColor}22`,
                color: accentColor,
              }}
            >
              {(account.subtype || account.type).replaceAll("_", " ")}
            </span>
          </div>
          <AccountTileSecondaryInfo account={account} />
        </div>
        <div className="shrink-0 text-right">
          <p className="font-bold tabular-nums">
            {formatMoney(account.current_balance_cents, account.currency)}
          </p>
          {account.owner_username && (
            <p className="text-[10px] text-muted-foreground">{account.owner_username}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function AccountSection({
  type,
  accounts,
  members,
  currentUser,
  mode,
  titleOverride,
}: {
  type: string;
  accounts: Account[];
  members: Member[];
  currentUser: { is_owner: boolean } | null;
  mode: "card" | "tile";
  titleOverride?: string;
}) {
  if (accounts.length === 0) return null;
  const title = titleOverride ?? SECTION_TITLES[type] ?? type;
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      <div
        className={
          mode === "card"
            ? "grid gap-6 sm:grid-cols-2 xl:grid-cols-3"
            : "flex flex-col gap-2"
        }
      >
        {accounts.map((account) =>
          mode === "card" ? (
            <FlipCard key={account.id} account={account} members={members} currentUser={currentUser} />
          ) : (
            <AccountTile key={account.id} account={account} />
          ),
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Cash wallet management
// ---------------------------------------------------------------------------

function CashWalletSection({ account }: { account: Account }) {
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [balanceInput, setBalanceInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const updateMutation = useMutation({
    mutationFn: (cents: number) =>
      accountsApi.update(account.id, { current_balance_cents: cents }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["v2-accounts"] });
      setEditOpen(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => accountsApi.delete(account.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["v2-accounts"] });
      setDeleteOpen(false);
    },
  });

  function openEdit() {
    setBalanceInput((account.current_balance_cents / 100).toFixed(2));
    setEditOpen(true);
    setTimeout(() => inputRef.current?.select(), 50);
  }

  function handleSaveBalance() {
    const parsed = parseFloat(balanceInput.replace(/[^0-9.\-]/g, ""));
    if (isNaN(parsed)) return;
    updateMutation.mutate(Math.round(parsed * 100));
  }

  const formattedBalance = formatMoney(account.current_balance_cents, account.currency ?? "USD");

  return (
    <>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Cash Wallet</h2>
        <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-card px-5 py-4 shadow-sm">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-500">
            <Wallet className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-semibold">{account.name}</p>
            <p className="text-xs text-muted-foreground">Manual cash tracking wallet</p>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-lg font-bold tabular-nums">{formattedBalance}</p>
            {account.owner_username && (
              <p className="text-[10px] text-muted-foreground">{account.owner_username}</p>
            )}
          </div>
          <div className="flex shrink-0 gap-2">
            <Button type="button" size="sm" variant="outline" className="gap-1.5" onClick={openEdit}>
              <Pencil className="size-3.5" />
              Edit balance
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2 className="size-3.5" />
              Delete
            </Button>
          </div>
        </div>
      </section>

      {/* Edit balance dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-xs">
          <DialogHeader>
            <DialogTitle>Edit Cash Wallet balance</DialogTitle>
            <DialogDescription>
              Set the current balance directly. This does not create a transaction.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="cash-balance">Balance (USD)</Label>
            <Input
              id="cash-balance"
              ref={inputRef}
              type="number"
              step="0.01"
              value={balanceInput}
              onChange={(e) => setBalanceInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSaveBalance()}
              placeholder="0.00"
            />
          </div>
          {updateMutation.isError && (
            <p className="text-sm text-destructive">
              {updateMutation.error instanceof Error
                ? updateMutation.error.message
                : "Failed to update balance"}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleSaveBalance}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? (
                <><Loader2 className="size-4 animate-spin" /> Saving…</>
              ) : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete Cash Wallet?</DialogTitle>
            <DialogDescription>
              The wallet will be deactivated. Existing cash transactions will remain in your history
              but will no longer be linked to an active account.
            </DialogDescription>
          </DialogHeader>
          {deleteMutation.isError && (
            <p className="text-sm text-destructive">
              {deleteMutation.error instanceof Error
                ? deleteMutation.error.message
                : "Failed to delete wallet"}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? (
                <><Loader2 className="size-4 animate-spin" /> Deleting…</>
              ) : "Delete wallet"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ---------------------------------------------------------------------------
// Net worth summary card
// ---------------------------------------------------------------------------

function NetWorthCard({ accounts }: { accounts: Account[] }) {
  const netCents = netWorthCents(accounts);
  const primaryCurrency = accounts[0]?.currency ?? "USD";
  const hasMixedCurrencies = new Set(accounts.map((a) => a.currency.toUpperCase())).size > 1;

  const depository  = sumBalance(accounts.filter((a) => a.type === "depository"));
  const credit      = sumBalance(accounts.filter((a) => a.type === "credit"));
  const loans       = sumBalance(accounts.filter((a) => a.type === "loan"));
  const investments = sumBalance(accounts.filter((a) => a.type === "investment"));

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Net Worth</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className={cn("text-3xl font-bold tabular-nums tracking-tight", netCents < 0 && "text-destructive")}>
          {formatMoney(netCents, primaryCurrency)}
          {hasMixedCurrencies && (
            <span className="ml-2 text-sm font-normal text-amber-600 dark:text-amber-400">
              (mixed currencies, approx.)
            </span>
          )}
        </p>
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {[
            { label: "Checking/Savings", value: depository, positive: true },
            { label: "Investments",      value: investments, positive: true },
            { label: "Credit cards",     value: credit,      positive: false },
            { label: "Loans",            value: loans,       positive: false },
          ].map(({ label, value, positive }) => (
            <div key={label}>
              <p className="text-muted-foreground text-xs">{label}</p>
              <p className={cn("font-semibold tabular-nums", !positive && value > 0 ? "text-destructive" : "")}>
                {formatMoney(value, primaryCurrency)}
              </p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AccountsPage() {
  const { data: accounts = [], isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["v2-accounts", "all"],
    queryFn: () => accountsApi.list(false),
  });

  const { data: members = [] } = useQuery({
    queryKey: ["members"],
    queryFn: () => membersApi.list(),
  });

  const { user: currentUser } = useAuth();

  const grouped = useMemo(() => groupByType(accounts), [accounts]);
  const depositoryCards = useMemo(
    () => grouped.depository.filter(isCardLikeAccount),
    [grouped.depository],
  );
  const depositoryTiles = useMemo(
    () => grouped.depository.filter((a) => !isCardLikeAccount(a) && !a.is_cash_wallet),
    [grouped.depository],
  );

  const cashWallet = useMemo(
    () => grouped.depository.find((a) => a.is_cash_wallet) ?? null,
    [grouped.depository],
  );

  if (isLoading) {
    return (
      <AppLayout>
        <div className="space-y-6">
          <h1 className="text-3xl font-bold">Accounts</h1>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-32 w-full" />
            ))}
          </div>
        </div>
      </AppLayout>
    );
  }

  if (isError) {
    return (
      <AppLayout>
        <div className="space-y-6">
          <h1 className="text-3xl font-bold">Accounts</h1>
          <Card className="border-destructive/50">
            <CardHeader>
              <CardTitle className="text-destructive">Could not load accounts</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground mb-3 text-sm">
                {error instanceof Error ? error.message : "Unknown error"}
              </p>
              <button
                type="button"
                className="text-primary text-sm font-medium underline-offset-4 hover:underline"
                onClick={() => void refetch()}
              >
                Try again
              </button>
            </CardContent>
          </Card>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="space-y-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">Accounts</h1>
            <p className="text-muted-foreground">
              Tap any card to see full details
              {isFetching ? <span className="ml-2 text-xs">Updating…</span> : null}
            </p>
          </div>
        </div>

        {accounts.length > 0 && <NetWorthCard accounts={accounts} />}

        {accounts.length === 0 ? (
          <Card>
            <CardContent className="text-muted-foreground py-10 text-center text-sm">
              No accounts connected yet. Connect a bank in Settings → Bank connections.
            </CardContent>
          </Card>
        ) : (
          <>
            <AccountSection type="credit" accounts={grouped.credit} members={members} currentUser={currentUser} mode="card" />
            {depositoryCards.length > 0 ? (
              <AccountSection
                type="depository"
                accounts={depositoryCards}
                members={members}
                currentUser={currentUser}
                mode="card"
                titleOverride="Debit cards"
              />
            ) : null}
            {depositoryTiles.length > 0 ? (
              <AccountSection
                type="depository"
                accounts={depositoryTiles}
                members={members}
                currentUser={currentUser}
                mode="tile"
                titleOverride="Cash & bank accounts"
              />
            ) : null}
            <AccountSection type="loan" accounts={grouped.loan} members={members} currentUser={currentUser} mode="tile" />
            <AccountSection type="investment" accounts={grouped.investment} members={members} currentUser={currentUser} mode="tile" />
            <AccountSection type="other" accounts={grouped.other} members={members} currentUser={currentUser} mode="tile" />
            {cashWallet ? <CashWalletSection account={cashWallet} /> : null}
          </>
        )}
      </div>
    </AppLayout>
  );
}
