"use client";

/**
 * ManualOverrideField — renders a credit_limit / APR cell on the account
 * card back.
 *
 * Tri-state:
 *   1. Plaid reports the value      → render it verbatim (read-only).
 *   2. Plaid omits it, user set it  → render manual value with a small
 *                                     "Manual" tag and a pencil to edit.
 *   3. Plaid omits it, no manual    → render "Not reported by bank" +
 *                                     "Enter manually" button.
 *
 * Used inside the dark card back so all typography sticks to the
 * white/white-muted palette. The popover input stays in the default
 * theme for readability.
 */

import { useEffect, useState } from "react";
import { Info, Pencil, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { accountsApi } from "@/lib/api";
import type { Account } from "@/types/v2";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

type FieldKind = "credit_limit" | "apr";

interface ManualOverrideFieldProps {
  account: Account;
  kind: FieldKind;
  label: string;
  /** Format the resolved (Plaid or manual) value for read-only display. */
  format: (value: number | string) => string;
}

const HINT_TEXT =
  "Some banks (e.g. Capital One) don't expose this through Plaid. Enter your own number from the bank app to keep reports and the rich card view accurate.";

export function ManualOverrideField({
  account,
  kind,
  label,
  format,
}: ManualOverrideFieldProps) {
  const plaidValue =
    kind === "credit_limit" ? account.credit_limit_cents : account.apr_percent;
  const manualValue =
    kind === "credit_limit"
      ? account.credit_limit_cents_manual
      : account.apr_percent_manual;

  // Plaid value always wins, even if a manual one sits alongside it.
  const effective: number | string | null =
    plaidValue ?? manualValue ?? null;
  const source: "plaid" | "manual" | "missing" =
    plaidValue != null ? "plaid" : manualValue != null ? "manual" : "missing";

  return (
    <div>
      <div className="flex items-center gap-1">
        <p className="text-white/50">{label}</p>
        {source === "missing" && (
          <span
            title={HINT_TEXT}
            className="text-white/40 hover:text-white/70"
            aria-label={HINT_TEXT}
          >
            <Info className="size-3" />
          </span>
        )}
      </div>

      {source === "plaid" && (
        <p className="font-semibold text-white tabular-nums">
          {format(effective as number | string)}
        </p>
      )}

      {source === "manual" && (
        <ManualValueRow
          account={account}
          kind={kind}
          label={label}
          value={manualValue as number | string}
          format={format}
        />
      )}

      {source === "missing" && (
        <EnterManuallyButton account={account} kind={kind} label={label} />
      )}
    </div>
  );
}

function ManualValueRow({
  account,
  kind,
  label,
  value,
  format,
}: {
  account: Account;
  kind: FieldKind;
  label: string;
  value: number | string;
  format: (value: number | string) => string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <p className="font-semibold text-white tabular-nums">{format(value)}</p>
      <span className="rounded-full bg-white/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-white/80">
        Manual
      </span>
      <OverridePopover
        account={account}
        kind={kind}
        label={label}
        initial={value}
        trigger={
          <button
            type="button"
            className="rounded-full p-0.5 text-white/60 hover:bg-white/10 hover:text-white"
            aria-label="Edit manual value"
          >
            <Pencil className="size-3" />
          </button>
        }
      />
    </div>
  );
}

function EnterManuallyButton({
  account,
  kind,
  label,
}: {
  account: Account;
  kind: FieldKind;
  label: string;
}) {
  return (
    <OverridePopover
      account={account}
      kind={kind}
      label={label}
      initial=""
      trigger={
        <button
          type="button"
          className="w-full text-left text-[11px] text-white/70 hover:text-white"
        >
          <span className="italic">Not reported by bank</span>{" "}
          <span className="underline underline-offset-2">Enter manually</span>
        </button>
      }
    />
  );
}

function OverridePopover({
  account,
  kind,
  label,
  initial,
  trigger,
}: {
  account: Account;
  kind: FieldKind;
  label: string;
  initial: number | string;
  trigger: React.ReactNode;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<string>(() => formatInitial(kind, initial));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setValue(formatInitial(kind, initial));
      setError(null);
    }
  }, [open, initial, kind]);

  const mutation = useMutation({
    mutationFn: (payload: Partial<Account>) =>
      accountsApi.update(account.id, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["v2-accounts"] });
      setOpen(false);
    },
    onError: (err: unknown) => {
      const message =
        err && typeof err === "object" && "message" in err
          ? String((err as { message?: unknown }).message ?? "Failed to save")
          : "Failed to save";
      setError(message);
    },
  });

  function handleSave() {
    setError(null);
    if (kind === "credit_limit") {
      const cents = parseCreditLimit(value);
      if (cents === null) {
        setError("Enter a positive amount, e.g. 5000");
        return;
      }
      mutation.mutate({ credit_limit_cents_manual: cents });
    } else {
      const apr = parseApr(value);
      if (apr === null) {
        setError("Enter APR in percent, e.g. 19.99");
        return;
      }
      mutation.mutate({ apr_percent_manual: apr });
    }
  }

  function handleClear() {
    setError(null);
    mutation.mutate(
      kind === "credit_limit"
        ? { credit_limit_cents_manual: null }
        : { apr_percent_manual: null },
    );
  }

  const isEditing = initial !== "";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent className="w-80" align="end">
        <div className="space-y-3">
          <div>
            <p className="text-sm font-semibold">Set {label.toLowerCase()}</p>
            <p className="text-xs text-muted-foreground">{HINT_TEXT}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="manual-override-input" className="text-xs">
              {kind === "credit_limit" ? "Amount" : "APR %"}
            </Label>
            <Input
              id="manual-override-input"
              inputMode="decimal"
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={kind === "credit_limit" ? "5000" : "19.99"}
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
          <div className="flex items-center justify-between gap-2">
            {isEditing ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleClear}
                disabled={mutation.isPending}
                className="text-destructive hover:text-destructive"
              >
                <X className="size-3" /> Clear
              </Button>
            ) : (
              <span />
            )}
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setOpen(false)}
                disabled={mutation.isPending}
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={handleSave}
                disabled={mutation.isPending || !value.trim()}
              >
                {mutation.isPending ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

/**
 * Turn the stored representation into what the input should show.
 * Credit limit is stored as integer cents; APR as a decimal string.
 */
function formatInitial(kind: FieldKind, value: number | string): string {
  if (value === "" || value == null) return "";
  if (kind === "credit_limit") {
    const cents = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(cents)) return "";
    return (cents / 100).toFixed(2).replace(/\.00$/, "");
  }
  // APR: drop trailing zeros for readability, keep at most 3 decimals.
  const s = String(value);
  return s.replace(/0+$/, "").replace(/\.$/, "");
}

function parseNumber(raw: string): number | null {
  const trimmed = raw.trim().replace(",", ".");
  if (!trimmed) return null;
  const num = Number(trimmed);
  if (!Number.isFinite(num) || num < 0) return null;
  return num;
}

function parseCreditLimit(raw: string): number | null {
  const num = parseNumber(raw);
  if (num === null) return null;
  return Math.round(num * 100);
}

function parseApr(raw: string): string | null {
  const num = parseNumber(raw);
  if (num === null || num > 100) return null;
  return num.toFixed(3);
}
