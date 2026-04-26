"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CreditCard as CreditCardIcon,
  Landmark,
  PiggyBank,
  TrendingUp,
  UserRound,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { accountsApi } from "@/lib/api";
import type { Account, Member } from "@/types/v2";
import { ManualOverrideField } from "./manual-override-field";
import {
  TYPE_COLORS,
  cardGradient,
  darken,
  formatMoney,
  formatSyncedAt,
} from "./helpers";

/**
 * Pick the icon that represents an account type. Used as the visual centerpiece
 * of the institution-logo placeholder when Plaid hasn't given us a brand
 * graphic — letters ("CC", "CO") read as a glitch, but a stylized type-icon on
 * a brand-colored disc reads as design.
 */
function accountTypeIcon(type: string): LucideIcon {
  switch (type) {
    case "credit":
      return CreditCardIcon;
    case "loan":
      return PiggyBank;
    case "investment":
      return TrendingUp;
    case "depository":
      return Landmark;
    default:
      return Wallet;
  }
}

// ---------------------------------------------------------------------------
// Face helpers
// ---------------------------------------------------------------------------

interface FaceProps {
  account: Account;
  color: string;
  size: "default" | "compact";
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
      // eslint-disable-next-line @next/next/no-img-element -- base64 data URL stored in DB
      <img
        src={`data:image/png;base64,${account.institution_logo}`}
        alt={account.name}
        width={size}
        height={size}
        style={{ width: size, height: size }}
        className="rounded-md bg-white/95 object-contain p-1 shadow-sm"
      />
    );
  }
  // No Plaid logo. Instead of awkward initials ("CC", "CO"), render a
  // disc tinted with the institution's brand color (or the type accent
  // when Plaid didn't give us a color either) plus a Lucide icon that
  // signals the account type.
  const accentColor =
    account.institution_color ?? TYPE_COLORS[account.type] ?? TYPE_COLORS.other;
  const Icon = accountTypeIcon(account.type);
  if (variant === "light") {
    return (
      <div
        className="flex items-center justify-center rounded-md"
        style={{
          width: size,
          height: size,
          backgroundColor: `${accentColor}22`,
          color: accentColor,
        }}
      >
        <Icon style={{ width: size * 0.55, height: size * 0.55 }} aria-hidden />
      </div>
    );
  }
  return (
    <div
      className="flex items-center justify-center rounded-md text-white shadow-sm ring-1 ring-white/15"
      style={{
        width: size,
        height: size,
        backgroundColor: `${accentColor}d9`, // ~85% alpha — translucent over gradient
      }}
    >
      <Icon style={{ width: size * 0.55, height: size * 0.55 }} aria-hidden />
    </div>
  );
}

function TypeLabel({ type }: { type: string }) {
  const labels: Record<string, string> = {
    depository: "Checking / Savings",
    credit: "Credit Card",
    loan: "Loan",
    investment: "Investment",
    other: "Account",
  };
  return (
    <span className="rounded-full bg-white/20 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-widest text-white/90">
      {labels[type] ?? type}
    </span>
  );
}

function ChipIcon({ compact }: { compact: boolean }) {
  const w = compact ? 30 : 38;
  const h = compact ? 22 : 28;
  return (
    <svg viewBox="0 0 38 28" width={w} height={h} className="opacity-80">
      <rect x="0" y="0" width="38" height="28" rx="4" fill="rgba(255,255,255,0.25)" />
      <rect x="0" y="9" width="38" height="10" fill="rgba(255,255,255,0.12)" />
      <rect x="13" y="0" width="12" height="28" fill="rgba(255,255,255,0.12)" />
      <rect x="13" y="9" width="12" height="10" fill="rgba(255,255,255,0.18)" />
    </svg>
  );
}

function CardFront({ account, color, size }: FaceProps) {
  const compact = size === "compact";
  const name = account.official_name || account.name;
  const mask = account.mask ? `•••• ${account.mask}` : null;
  const isDebt = account.type === "credit" || account.type === "loan";
  // Bigger logo than before — the previous 30px was lost on the card. 40
  // and 52 give the institution mark proper visual weight without
  // overwhelming the layout.
  const logoSize = compact ? 40 : 52;

  return (
    <div
      className={
        compact
          ? "absolute inset-0 flex flex-col justify-between overflow-hidden rounded-xl p-3 text-white"
          : "absolute inset-0 flex flex-col justify-between overflow-hidden rounded-2xl p-5 text-white"
      }
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
        <InstitutionLogo account={account} size={logoSize} />
        <TypeLabel type={account.type} />
      </div>

      {/* Middle: chip + account label */}
      <div className="relative flex items-end justify-between">
        {account.type === "credit" ? <ChipIcon compact={compact} /> : <div />}
        <p
          className={
            compact
              ? "max-w-[60%] truncate text-right text-[11px] font-medium text-white/80"
              : "max-w-[60%] truncate text-right text-sm font-medium text-white/80"
          }
          title={name}
        >
          {name}
        </p>
      </div>

      {/* Bottom row */}
      <div className="relative flex items-end justify-between">
        <div>
          {mask ? (
            <p
              className={
                compact
                  ? "font-mono text-xs tracking-widest text-white/90"
                  : "font-mono text-base tracking-widest text-white/90"
              }
            >
              {mask}
            </p>
          ) : (
            <p className="text-[10px] text-white/60 italic">No card number</p>
          )}
          <div className="mt-1 flex items-center gap-1.5">
            <OwnerBadge username={account.owner_username} />
          </div>
        </div>
        <div className="text-right">
          <p className="text-[9px] uppercase tracking-widest text-white/60">
            {isDebt ? "Balance" : "Current"}
          </p>
          <p
            className={
              compact
                ? "text-base font-bold tabular-nums"
                : "text-xl font-bold tabular-nums"
            }
          >
            {formatMoney(account.current_balance_cents, account.currency)}
          </p>
        </div>
      </div>
    </div>
  );
}

function UtilizationBar({ account }: { account: Account }) {
  const limit = account.credit_limit_cents ?? account.credit_limit_cents_manual;
  if (limit == null || limit <= 0)
    return <p className="text-white/50 text-xs">No credit limit on file</p>;
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
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${capped}%`, backgroundColor: barColor }}
        />
      </div>
    </div>
  );
}

function CardBack({
  account,
  color,
  size,
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
  const compact = size === "compact";

  return (
    <div
      className={
        compact
          ? "absolute inset-0 flex flex-col justify-between overflow-hidden rounded-xl p-3 text-white"
          : "absolute inset-0 flex flex-col justify-between overflow-hidden rounded-2xl p-4 text-white"
      }
      style={{
        background: cardGradient(darken(color, 0.1)),
        backfaceVisibility: "hidden",
        WebkitBackfaceVisibility: "hidden",
        transform: "rotateY(180deg)",
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {/* Decorative stripe */}
      <div className="absolute left-0 right-0 top-7 h-7 bg-black/30" />

      {/* Header */}
      <div className="relative flex items-center justify-between pt-7">
        <p className="text-[10px] uppercase tracking-widest text-white/60">Details</p>
        <button
          type="button"
          className="flex items-center gap-1 rounded-full bg-white/20 px-2.5 py-0.5 text-[10px] font-medium text-white hover:bg-white/30 active:bg-white/40"
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
              <ManualOverrideField
                account={account}
                kind="credit_limit"
                label="Limit"
                format={(v) => formatMoney(Number(v), account.currency)}
              />
              <ManualOverrideField
                account={account}
                kind="apr"
                label="APR"
                format={(v) => `${v}%`}
              />
              <div>
                <p className="text-white/50">Min payment</p>
                <p className="font-semibold text-white tabular-nums">
                  {account.min_payment_cents != null
                    ? formatMoney(account.min_payment_cents, account.currency)
                    : "—"}
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

      {/* Owner section */}
      <div className="relative rounded-xl border border-white/15 bg-black/20 px-3 py-2">
        <OwnerSelector account={account} members={members} currentUser={currentUser} />
      </div>

      {/* Footer: last synced */}
      <p className="relative text-[9px] text-white/40">
        Synced: {formatSyncedAt(account.last_synced_at)}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Owner badge (front face) / owner selector (back face)
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
    mutationFn: (userId: number | null) =>
      accountsApi.assignOwner(account.id, userId),
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

  if (currentUser === null) {
    return (
      <div>
        {label}
        <p className="text-sm text-white/40 italic">Loading…</p>
      </div>
    );
  }

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
          <SelectValue
            placeholder={members.length === 0 ? "No users yet…" : "Assign owner…"}
          />
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

export function FlipCard({
  account,
  members,
  currentUser,
  size = "default",
}: {
  account: Account;
  members: Member[];
  currentUser: { is_owner: boolean } | null;
  /** compact shrinks padding, fonts, chip and logo for owner-column layout. */
  size?: "default" | "compact";
}) {
  const [flipped, setFlipped] = useState(false);
  const color =
    account.institution_color ?? TYPE_COLORS[account.type] ?? TYPE_COLORS.other;

  return (
    <div
      // Card stretches to the full owner-column width; the column itself
      // is what's capped at ~440px (in OwnerColumn) so the card and the
      // list rows below it line up exactly. Capping here too made the
      // columns look lopsided — wide column, narrow card, empty gutter.
      className="w-full cursor-pointer select-none"
      style={{ perspective: "1000px" }}
      onClick={() => setFlipped((f) => !f)}
      role="button"
      tabIndex={0}
      aria-label={`${account.name} — tap to ${flipped ? "see front" : "see details"}`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") setFlipped((f) => !f);
      }}
    >
      <div
        className="relative w-full transition-transform duration-500"
        style={{
          aspectRatio: "85.6 / 54",
          transformStyle: "preserve-3d",
          transform: flipped ? "rotateY(180deg)" : "rotateY(0deg)",
        }}
      >
        <CardFront account={account} color={color} size={size} />
        <CardBack
          account={account}
          color={color}
          size={size}
          members={members}
          currentUser={currentUser}
          onFlipBack={() => setFlipped(false)}
        />
      </div>
    </div>
  );
}
