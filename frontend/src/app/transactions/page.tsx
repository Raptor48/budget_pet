"use client";

import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, isValid } from "date-fns";
import { ArrowLeftRight, Columns2, CreditCard, Download, EyeOff, Eye, Loader2, Settings, Store, Trash2, Wifi, CircleDot } from "lucide-react";

import { AddCashTransactionDialog } from "@/app/transactions/_components/add-cash-transaction-dialog";
import { CreateRuleFromTransactionButton } from "@/app/transactions/_components/create-rule-from-transaction-button";
import { InternalTransferSettingsDialog } from "@/app/transactions/_components/internal-transfer-settings-dialog";
import { TransactionMobileCard } from "@/app/transactions/_components/transaction-mobile-card";
import { AppLayout } from "@/components/layout/app-layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { MonthYearPicker } from "@/components/ui/month-year-picker";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PlaidTxnAmount } from "@/components/ui/plaid-txn-amount";
import { formatAccountPickerLabel } from "@/lib/account-picker-label";
import { getAuthHeaders } from "@/lib/auth";
import {
  accountsApi,
  ApiError,
  categoriesApi,
  membersApi,
  tagsApi,
  transactionsApi,
} from "@/lib/api";
import { TRANSACTIONS_DATE_RANGE_QUERY_KEY } from "@/lib/hooks/use-transactions-date-range";
import { confirm, notify, onMutationError } from "@/lib/notify";
import {
  formatPlaidTxnAmountForDisplay,
  formatPlaidTxnAmountLegacy,
} from "@/lib/plaid-transaction-amount";
import { normalizeTransactionTitle, rawTransactionTitle } from "@/lib/transaction-display";
import { cn } from "@/lib/utils";
import type {
  Category,
  Counterparty,
  Location,
  PaymentMeta,
  Tag,
  Transaction,
  TransactionClass,
  TransactionFilters,
  TransactionSplit,
} from "@/types/v2";

const ALL = "all";

function formatMoney(cents: number): string {
  return formatPlaidTxnAmountForDisplay(cents, "USD");
}

function currentMonth(): string {
  return format(new Date(), "yyyy-MM");
}


function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function displayName(tx: Transaction): string {
  return normalizeTransactionTitle(tx);
}

function displayDate(tx: Transaction): string {
  const d = tx.authorized_date || tx.date;
  try {
    return format(new Date(d), "MMM d, yyyy");
  } catch {
    return d;
  }
}

function channelIcon(paymentChannel: string | null) {
  const c = (paymentChannel || "").toLowerCase();
  if (c === "online") {
    return <Wifi className="size-4 shrink-0 text-sky-600 dark:text-sky-400" aria-label="Online" />;
  }
  if (c.includes("store") || c === "in store") {
    return <Store className="size-4 shrink-0 text-amber-700 dark:text-amber-500" aria-label="In store" />;
  }
  return <CircleDot className="size-4 shrink-0 text-muted-foreground" aria-label="Other channel" />;
}

function AccountChip({ tx }: { tx: Transaction }) {
  const mask = tx.account_mask;
  const name = tx.account_name;
  const owner = tx.owner_username;
  if (!mask && !name) return null;

  const cardLabel = mask ? `•••• ${mask}` : (name ?? "");
  const title = [owner, name, mask ? `····${mask}` : null].filter(Boolean).join(" · ");

  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-[11px] text-muted-foreground"
      title={title}
    >
      <CreditCard className="size-3 shrink-0" />
      {owner ? (
        <span className="hidden font-medium text-foreground/70 sm:inline">{owner}</span>
      ) : null}
      <span className="font-mono tracking-wide">{cardLabel}</span>
    </span>
  );
}

function MerchantAvatar({ tx }: { tx: Transaction }) {
  const [failed, setFailed] = useState(false);
  const name = displayName(tx);
  const showImg = Boolean(tx.logo_url) && !failed;

  return (
    <div className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted text-xs font-semibold text-muted-foreground">
      {showImg ? (
        <img
          src={tx.logo_url!}
          alt=""
          className="size-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="leading-none">{initialsFromName(name)}</span>
      )}
    </div>
  );
}

function parseCoord(raw: unknown): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string") {
    const x = parseFloat(raw);
    return Number.isFinite(x) ? x : null;
  }
  return null;
}

function asLocation(v: unknown): Location | null {
  if (v == null) return null;
  if (typeof v === "string") {
    try {
      return asLocation(JSON.parse(v));
    } catch {
      return null;
    }
  }
  if (typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  return {
    address: typeof o.address === "string" ? o.address : null,
    city: typeof o.city === "string" ? o.city : null,
    region: typeof o.region === "string" ? o.region : null,
    postal_code: typeof o.postal_code === "string" ? o.postal_code : null,
    country: typeof o.country === "string" ? o.country : null,
    lat: parseCoord(o.lat),
    lon: parseCoord(o.lon),
    store_number: typeof o.store_number === "string" ? o.store_number : null,
  };
}

function formatLocationHuman(loc: Location | null): string | null {
  if (!loc) return null;
  const line = [loc.address, loc.city, loc.region, loc.postal_code].filter(Boolean).join(", ");
  if (line) return line;
  if (loc.store_number) return `Store ${loc.store_number}`;
  if (loc.lat != null && loc.lon != null) {
    return `${Number(loc.lat).toFixed(5)}, ${Number(loc.lon).toFixed(5)}`;
  }
  return null;
}

function asPaymentMeta(v: unknown): PaymentMeta | null {
  if (v == null) return null;
  if (typeof v === "string") {
    try {
      return asPaymentMeta(JSON.parse(v));
    } catch {
      return null;
    }
  }
  if (typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const pick = (k: string): string | null => {
    const x = o[k];
    return typeof x === "string" && x.trim() ? x : null;
  };
  return {
    reference_number: pick("reference_number"),
    ppd_id: pick("ppd_id"),
    payee: pick("payee"),
    payer: pick("payer"),
    payment_method: pick("payment_method"),
    payment_processor: pick("payment_processor"),
    reason: pick("reason"),
  };
}

const PAYMENT_META_LABELS: Record<keyof PaymentMeta, string> = {
  reference_number: "Reference",
  ppd_id: "PPD ID",
  payee: "Payee",
  payer: "Payer",
  payment_method: "Payment method",
  payment_processor: "Processor",
  reason: "Reason",
};

function paymentMetaRows(meta: PaymentMeta | null): { label: string; value: string }[] {
  if (!meta) return [];
  return (Object.keys(PAYMENT_META_LABELS) as (keyof PaymentMeta)[])
    .map((k) => ({ key: k, value: meta[k] }))
    .filter((x): x is { key: keyof PaymentMeta; value: string } => x.value != null && x.value.trim() !== "")
    .map((x) => ({ label: PAYMENT_META_LABELS[x.key], value: x.value }));
}

function formatDateTimeShort(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (!isValid(d)) return null;
  try {
    return format(d, "MMM d, yyyy · HH:mm");
  } catch {
    return null;
  }
}

function formatAuthorizedDateOnly(isoDate: string): string {
  const d = new Date(isoDate);
  if (!isValid(d)) return isoDate;
  try {
    return format(d, "MMM d, yyyy");
  } catch {
    return isoDate;
  }
}

/** Plaid / DB may return JSONB as array, string, or object — normalize for UI. */
function normalizeCounterparties(raw: unknown): Counterparty[] {
  if (raw == null) return [];
  if (typeof raw === "string") {
    try {
      return normalizeCounterparties(JSON.parse(raw));
    } catch {
      return [];
    }
  }
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((x): x is Record<string, unknown> => x != null && typeof x === "object" && !Array.isArray(x))
    .map((o) => ({
      name: String(o.name ?? o.merchant_name ?? "Unknown"),
      entity_id: o.entity_id != null ? String(o.entity_id) : null,
      type: String(o.type ?? "unknown"),
      website: typeof o.website === "string" && o.website ? o.website : null,
      logo_url: typeof o.logo_url === "string" && o.logo_url ? o.logo_url : null,
      confidence_level: String(o.confidence_level ?? ""),
    }));
}

function safeWebsiteHref(website: string): string {
  return website.startsWith("http://") || website.startsWith("https://") ? website : `https://${website}`;
}

/** Maps Plaid `personal_finance_category.confidence_level` to a short label (Plaid publishes exact thresholds only for VERY_HIGH and HIGH). */
function pfcConfidencePercentLabel(level: string | null | undefined): string {
  const key = (level ?? "").toUpperCase().replace(/\s+/g, "_");
  switch (key) {
    case "VERY_HIGH":
      return ">98%";
    case "HIGH":
      return ">90%";
    case "MEDIUM":
      return "~50–90%";
    case "LOW":
      return "<50%";
    default:
      return "—";
  }
}

function pfcConfidenceTooltipBody(level: string | null | undefined): { title: string; body: string } {
  const key = (level ?? "UNKNOWN").toUpperCase().replace(/\s+/g, "_");
  const titles: Record<string, string> = {
    VERY_HIGH: "Very high confidence",
    HIGH: "High confidence",
    MEDIUM: "Medium confidence",
    LOW: "Low confidence",
    UNKNOWN: "Unknown confidence",
  };
  const bodies: Record<string, string> = {
    VERY_HIGH:
      "Plaid estimates over a 98% probability that this category matches what the transaction was for.",
    HIGH:
      "Plaid estimates over a 90% probability that this category matches what the transaction was for.",
    MEDIUM:
      "Plaid is moderately confident; some details may differ from the best-fit category. The badge shows an approximate band; only Very high and High have published probability thresholds.",
    LOW:
      "This category may reflect the transaction, but another category could be more accurate. The badge shows an approximate band; only Very high and High have published probability thresholds.",
    UNKNOWN: "Plaid did not provide a confidence score for this category.",
  };
  return {
    title: titles[key] ?? titles.UNKNOWN,
    body: bodies[key] ?? bodies.UNKNOWN,
  };
}

function DetailRow({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[7.5rem_1fr] sm:gap-x-3">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm text-foreground">{children}</dd>
    </div>
  );
}

function TransactionDetailsDialog({
  transactionId,
  open,
  onOpenChange,
  categories,
  onSave,
  isSaving,
  onDeleteCash,
  isDeletingCash,
  onTogglePrivate,
  isTogglingPrivate,
  onSetClassOverride,
  isSettingClassOverride,
}: {
  transactionId: number | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  categories: Category[];
  onSave: (payload: { category_id: number | null; user_note: string }) => void | Promise<void>;
  isSaving: boolean;
  onDeleteCash?: (id: number) => Promise<void>;
  isDeletingCash?: boolean;
  onTogglePrivate?: (id: number, isPrivate: boolean) => void;
  isTogglingPrivate?: boolean;
  /**
   * Replaces the pre-V2 "Mark internal transfer" toggle. Passing `null`
   * clears the pin and returns the row to the auto-classifier's control;
   * passing any of the four classes persists a `manual_class_override`
   * on the server (see docs/reports-math.md §3 rule 1).
   */
  onSetClassOverride?: (id: number, override: TransactionClass | null) => void;
  isSettingClassOverride?: boolean;
}) {
  const [editNote, setEditNote] = useState("");
  const [editCategoryId, setEditCategoryId] = useState(ALL);

  const {
    data: transaction,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["transaction", transactionId],
    queryFn: () => transactionsApi.get(transactionId!),
    enabled: open && transactionId != null,
  });

  useEffect(() => {
    if (!transaction) return;
    setEditNote(transaction.user_note ?? "");
    setEditCategoryId(transaction.category_id == null ? ALL : String(transaction.category_id));
  }, [transaction]);

  const handleSave = async () => {
    try {
      await onSave({
        user_note: editNote,
        category_id: editCategoryId === ALL ? null : Number(editCategoryId),
      });
    } catch {
      /* onSave's mutation reports the error via toast */
    }
  };

  const loc = transaction ? asLocation(transaction.location) : null;
  const locText = transaction ? formatLocationHuman(loc) : null;
  const metaRows = transaction ? paymentMetaRows(asPaymentMeta(transaction.payment_meta)) : [];
  const counterparties = transaction ? normalizeCounterparties(transaction.counterparties) : [];
  const bankName = transaction ? (transaction.name ?? "").trim() : "";
  const merchantLabel = transaction ? (transaction.merchant_name ?? "").trim() : "";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[min(90vh,calc(100dvh-1.5rem))] w-[min(520px,calc(100vw-1.5rem))] flex-col gap-0 overflow-hidden p-0">
        <div className="shrink-0 border-b border-border px-5 py-4">
          <DialogHeader className="space-y-0 text-left">
            <DialogTitle className="text-base font-semibold">Transaction details</DialogTitle>
            <DialogDescription className="sr-only">
              Plaid fields, location, and your category and note.
            </DialogDescription>
          </DialogHeader>
          {transaction && !isLoading && !isError ? (
            <div className="mt-3 flex min-w-0 items-start gap-3">
              <MerchantAvatar tx={transaction} />
              <div className="min-w-0 flex-1 space-y-1">
                <p
                  className="break-words font-semibold leading-tight"
                  title={rawTransactionTitle(transaction) || displayName(transaction)}
                >
                  {displayName(transaction)}
                </p>
                {bankName && bankName !== merchantLabel ? (
                  <p className="text-xs text-muted-foreground" title={bankName}>
                    Bank description: {bankName}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-2 pt-0.5">
                  <PlaidTxnAmount cents={Number(transaction.amount_cents) || 0} size="base" tone="flow" />
                  {transaction.is_pending ? (
                    <Badge variant="secondary" className="text-[10px] uppercase tracking-wide">
                      Pending
                    </Badge>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        {isLoading ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-sm text-muted-foreground">
            <Loader2 className="size-8 animate-spin text-muted-foreground" aria-hidden />
            Loading transaction details…
          </div>
        ) : null}

        {isError ? (
          <div className="px-5 py-10 text-center text-sm text-destructive" role="alert">
            {error instanceof Error ? error.message : "Failed to load transaction"}
          </div>
        ) : null}

        {transaction && !isLoading && !isError ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <dl className="space-y-3">
            <DetailRow label="Account">
              <div className="flex flex-wrap items-center gap-2">
                {channelIcon(transaction.payment_channel)}
                <AccountChip tx={transaction} />
              </div>
            </DetailRow>
            <DetailRow label="Posted date">{displayDate(transaction)}</DetailRow>
            {transaction.authorized_date && transaction.authorized_date !== transaction.date ? (
              <DetailRow label="Authorized">
                {formatAuthorizedDateOnly(String(transaction.authorized_date))}
              </DetailRow>
            ) : null}
            {formatDateTimeShort(transaction.authorized_datetime) ? (
              <DetailRow label="Authorized (time)">{formatDateTimeShort(transaction.authorized_datetime)}</DetailRow>
            ) : null}
            {formatDateTimeShort(transaction.datetime) ? (
              <DetailRow label="Posted (time)">{formatDateTimeShort(transaction.datetime)}</DetailRow>
            ) : null}
            <DetailRow label="Channel">{transaction.payment_channel ?? "—"}</DetailRow>
            {(transaction.pfc_detailed || transaction.pfc_primary) && (
              <DetailRow
                label={
                  <span className="inline-flex items-center gap-1">
                    <span>Category</span>
                    {transaction.pfc_confidence ? (
                      <TooltipProvider delayDuration={250}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span
                              tabIndex={0}
                              className="-m-0.5 inline-flex shrink-0 cursor-default rounded border border-border/60 bg-muted/40 px-1 py-0.5 font-mono text-[10px] tabular-nums leading-none text-muted-foreground transition-colors hover:border-border hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:outline-none"
                              aria-label="Plaid category confidence"
                            >
                              {pfcConfidencePercentLabel(transaction.pfc_confidence)}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent
                            side="top"
                            className="max-w-[min(280px,calc(100vw-2rem))] border-border/80 bg-popover px-3 py-2 text-xs font-normal leading-snug text-popover-foreground shadow-md"
                          >
                            {(() => {
                              const { title, body } = pfcConfidenceTooltipBody(transaction.pfc_confidence);
                              return (
                                <>
                                  <span className="block font-medium text-foreground">{title}</span>
                                  <span className="mt-1 block text-muted-foreground">{body}</span>
                                  <span className="mt-1.5 block font-mono text-[10px] text-muted-foreground/80">
                                    {transaction.pfc_confidence}
                                  </span>
                                </>
                              );
                            })()}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    ) : null}
                  </span>
                }
              >
                <span className="break-words">
                  {[transaction.pfc_primary, transaction.pfc_detailed].filter(Boolean).join(" · ")}
                </span>
              </DetailRow>
            )}
            {typeof transaction.website === "string" && transaction.website.trim() ? (
              <DetailRow label="Website">
                <a
                  href={safeWebsiteHref(transaction.website.trim())}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary underline-offset-4 hover:underline"
                >
                  {transaction.website}
                </a>
              </DetailRow>
            ) : null}
            {locText ? (
              <DetailRow label="Location">
                <div className="space-y-1">
                  <p className="break-words">{locText}</p>
                  {loc?.country ? <p className="text-xs text-muted-foreground">{loc.country}</p> : null}
                  {loc?.lat != null && loc?.lon != null ? (
                    <a
                      href={`https://www.google.com/maps?q=${loc.lat},${loc.lon}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary text-xs underline-offset-4 hover:underline"
                    >
                      Open in Maps
                    </a>
                  ) : null}
                </div>
              </DetailRow>
            ) : null}
            {metaRows.length > 0 ? (
              <DetailRow label="Payment details">
                <ul className="space-y-1">
                  {metaRows.map((r) => (
                    <li key={r.label} className="break-words text-sm">
                      <span className="text-muted-foreground">{r.label}: </span>
                      {r.value}
                    </li>
                  ))}
                </ul>
              </DetailRow>
            ) : null}
            {counterparties.length > 0 ? (
              <DetailRow label="Counterparties">
                <ul className="space-y-2">
                  {counterparties.map((c, i) => (
                    <li key={i} className="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5 text-sm">
                      <span className="font-medium">{c.name || "Unknown"}</span>
                      <span className="text-muted-foreground"> · {c.type}</span>
                      {c.website ? (
                        <span className="mt-0.5 block">
                          <a
                            href={safeWebsiteHref(c.website)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary text-xs underline-offset-4 hover:underline"
                          >
                            {c.website}
                          </a>
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </DetailRow>
            ) : null}
            <DetailRow label="Source">{transaction.source}</DetailRow>
            {transaction.plaid_transaction_id ? (
              <DetailRow label="Plaid ID">
                <code className="break-all rounded bg-muted px-1.5 py-0.5 text-[11px]">
                  {transaction.plaid_transaction_id}
                </code>
              </DetailRow>
            ) : null}
          </dl>

          <Separator className="my-5" />

          <div className="space-y-4">
            <h3 className="text-sm font-semibold">Your edits</h3>
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label>Category</Label>
                <Select value={editCategoryId} onValueChange={setEditCategoryId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Category" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Uncategorized</SelectItem>
                    {categories.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {transaction.source === "plaid" || transaction.source === "plaid_sandbox" ? (
                  <div className="pt-1">
                    <CreateRuleFromTransactionButton
                      transaction={transaction}
                      category={
                        editCategoryId === ALL
                          ? null
                          : (categories.find((c) => String(c.id) === editCategoryId) ?? null)
                      }
                    />
                  </div>
                ) : null}
              </div>
              <div className="grid gap-2">
                <Label htmlFor="txn-detail-note">Note</Label>
                <Input
                  id="txn-detail-note"
                  placeholder="Your note"
                  value={editNote}
                  onChange={(e) => setEditNote(e.target.value)}
                />
              </div>
            </div>
          </div>
        </div>
        ) : null}

        <DialogFooter className="shrink-0 flex-col gap-2 border-t border-border px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            {transaction && !isLoading && !isError && onTogglePrivate ? (
              <div className="flex flex-col gap-1">
                <Button
                  type="button"
                  variant={transaction.is_private ? "secondary" : "outline"}
                  className="gap-1.5"
                  disabled={isTogglingPrivate || isSaving}
                  onClick={() => onTogglePrivate(transaction.id, !transaction.is_private)}
                  title={transaction.is_private ? "Make visible to others" : "Hide from others"}
                >
                  {isTogglingPrivate ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : transaction.is_private ? (
                    <EyeOff className="size-4" />
                  ) : (
                    <Eye className="size-4" />
                  )}
                  {transaction.is_private ? "Hidden" : "Make private"}
                </Button>
                <p className="text-[11px] text-muted-foreground">
                  {transaction.is_private
                    ? "Hidden from other family members."
                    : "Hide the amount from other family members (e.g. a gift)."}
                </p>
              </div>
            ) : null}
            {transaction && !isLoading && !isError && onSetClassOverride ? (
              <div className="flex flex-col gap-1">
                <Label htmlFor="txn-class-override" className="text-xs">
                  Classify as
                </Label>
                <Select
                  value={
                    transaction.manual_class_override ?? "auto"
                  }
                  onValueChange={(value) => {
                    const next: TransactionClass | null =
                      value === "auto" ? null : (value as TransactionClass);
                    onSetClassOverride(transaction.id, next);
                  }}
                  disabled={isSettingClassOverride || isSaving}
                >
                  <SelectTrigger id="txn-class-override" className="gap-1.5">
                    {isSettingClassOverride ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <ArrowLeftRight className="size-4" />
                    )}
                    <SelectValue placeholder="Auto" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">
                      Auto ({transaction.transaction_class.replace("_", " ")})
                    </SelectItem>
                    <SelectItem value="income">Income</SelectItem>
                    <SelectItem value="expense">Expense</SelectItem>
                    <SelectItem value="internal_transfer">
                      Internal transfer
                    </SelectItem>
                    <SelectItem value="uncategorized">Uncategorized</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-muted-foreground">
                  {transaction.manual_class_override != null
                    ? `Pinned as ${transaction.manual_class_override.replace("_", " ")} — the auto-classifier will leave this row alone.`
                    : "Auto-classified. Pick a class to override the classifier (e.g. mark a family Zelle as Internal transfer)."}
                </p>
              </div>
            ) : null}
            {transaction && !isLoading && !isError && transaction.source === "cash" && onDeleteCash ? (
              <Button
                type="button"
                variant="destructive"
                className="gap-1.5"
                disabled={isDeletingCash || isSaving}
                onClick={async () => {
                  const ok = await confirm({
                    title: "Delete cash transaction?",
                    description:
                      "This cannot be undone. Your Cash wallet balance will be adjusted.",
                    destructive: true,
                    confirmLabel: "Delete",
                  });
                  if (!ok) return;
                  try {
                    await onDeleteCash(transaction.id);
                    onOpenChange(false);
                  } catch {
                    /* mutation onError surfaces the error via toast */
                  }
                }}
              >
                {isDeletingCash ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Deleting…
                  </>
                ) : (
                  <>
                    <Trash2 className="size-4" />
                    Delete
                  </>
                )}
              </Button>
            ) : null}
          </div>
          <div className="flex w-full flex-wrap justify-end gap-2 sm:w-auto">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            {transaction && !isLoading && !isError ? (
              <Button type="button" onClick={handleSave} disabled={isSaving || isDeletingCash}>
                {isSaving ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Saving…
                  </>
                ) : (
                  "Save changes"
                )}
              </Button>
            ) : null}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type SplitDraftRow = {
  category_id: number | null;
  tag_id: number | null;
  /** Raw string from the input — converted to cents only on save */
  amount_str: string;
  note: string;
};

function strToCents(s: string): number {
  const n = parseFloat(s.replace(",", "."));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

function centsToStr(c: number): string {
  return (c / 100).toFixed(2);
}

function SplitTransactionDialog({
  transaction,
  open,
  onOpenChange,
  categories,
}: {
  transaction: Transaction | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  categories: Category[];
}) {
  const queryClient = useQueryClient();
  const txId = transaction?.id ?? null;

  const { data: splits = [], isLoading } = useQuery({
    queryKey: ["transaction-splits", txId],
    queryFn: () => transactionsApi.getSplits(txId!),
    enabled: open && txId != null,
  });

  const [draft, setDraft] = useState<SplitDraftRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !transaction || isLoading) return;
    setError(null);
    if (splits.length > 0) {
      setDraft(
        splits.map((s) => ({
          category_id: s.category_id,
          tag_id: s.tag_id,
          amount_str: centsToStr(s.amount_cents),
          note: s.note ?? "",
        })),
      );
    } else {
      setDraft([
        {
          category_id: transaction.category_id,
          tag_id: null,
          amount_str: centsToStr(transaction.amount_cents),
          note: "",
        },
      ]);
    }
  }, [open, transaction, splits, isLoading]);

  const setSplitsMutation = useMutation({
    mutationFn: (body: SplitDraftRow[]) =>
      transactionsApi.setSplits(txId!, body.map((r) => ({
        category_id: r.category_id,
        tag_id: r.tag_id,
        amount_cents: strToCents(r.amount_str),
        note: r.note || undefined,
      }))),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["transaction-splits", txId] });
      onOpenChange(false);
    },
    onError: (e: Error) => {
      setError(e.message || "Failed to save splits");
    },
  });

  const total = transaction?.amount_cents ?? 0;

  /**
   * Auto-balance rules:
   *  • 2 rows: editing either row always updates the OTHER row to (total - edited).
   *  • 3+ rows: editing any non-last row updates the LAST row to the remainder.
   *  • 3+ rows, editing the last row: only the indicator shows; no auto-balance
   *    (user is manually fine-tuning).
   */
  const updateRow = (index: number, patch: Partial<SplitDraftRow>) => {
    setDraft((rows) => {
      const updated = rows.map((r, i) => (i === index ? { ...r, ...patch } : r));

      if ("amount_str" in patch && rows.length >= 2) {
        if (rows.length === 2) {
          // Always balance the other row
          const other = index === 0 ? 1 : 0;
          const remaining = total - strToCents(updated[index].amount_str);
          updated[other] = { ...updated[other], amount_str: (remaining / 100).toFixed(2) };
        } else if (index < rows.length - 1) {
          // 3+ rows: balance the last row when editing any other
          const sumExceptLast = updated
            .slice(0, -1)
            .reduce((a, r) => a + strToCents(r.amount_str), 0);
          const remaining = total - sumExceptLast;
          const last = updated.length - 1;
          updated[last] = { ...updated[last], amount_str: (remaining / 100).toFixed(2) };
        }
      }

      return updated;
    });
  };

  /** New row is pre-filled with the remaining unallocated amount. */
  const addRow = () => {
    setDraft((rows) => {
      const used = rows.reduce((a, r) => a + strToCents(r.amount_str), 0);
      const remaining = total - used;
      return [
        ...rows,
        {
          category_id: null,
          tag_id: null,
          amount_str: remaining !== 0 ? (remaining / 100).toFixed(2) : "",
          note: "",
        },
      ];
    });
  };

  const removeRow = (index: number) => {
    setDraft((rows) => rows.filter((_, i) => i !== index));
  };

  const handleSave = () => {
    if (!transaction || txId == null) return;
    if (draft.length === 0) {
      setError("Add at least one split line.");
      return;
    }
    const sum = draft.reduce((a, r) => a + strToCents(r.amount_str), 0);
    if (sum !== transaction.amount_cents) {
      setError(
        `Split amounts must sum to ${formatMoney(transaction.amount_cents)} (currently ${formatMoney(sum)}).`,
      );
      return;
    }
    setError(null);
    setSplitsMutation.mutate(draft);
  };

  const totalLabel = transaction
    ? `${formatMoney(transaction.amount_cents)} (${transaction.amount_cents > 0 ? "outflow" : transaction.amount_cents < 0 ? "inflow" : "zero"})`
    : "";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex w-[min(480px,calc(100vw-1.5rem))] flex-col gap-0 overflow-hidden p-0">
        {/* ── Header ── */}
        <div className="shrink-0 border-b border-border px-5 py-4">
          <DialogTitle className="text-base font-semibold">Split transaction</DialogTitle>
          {transaction ? (
            <div className="mt-1 flex min-w-0 items-center gap-2">
              <p
                className="min-w-0 flex-1 truncate text-sm text-muted-foreground"
                title={rawTransactionTitle(transaction) || displayName(transaction)}
              >
                {displayName(transaction)}
              </p>
              <PlaidTxnAmount
                cents={transaction.amount_cents}
                size="sm"
                tone="flow"
                className="shrink-0"
              />
            </div>
          ) : null}
        </div>

        {/* ── Body ── */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {isLoading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading splits…
            </div>
          ) : (
            <div className="space-y-3">
              {error ? (
                <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
                  {error}
                </p>
              ) : null}

              {/* Remaining indicator */}
              {transaction && (() => {
                const used = draft.reduce((a, r) => a + strToCents(r.amount_str), 0);
                const remaining = transaction.amount_cents - used;
                return remaining !== 0 ? (
                  <p className="text-xs text-muted-foreground">
                    Remaining to allocate:{" "}
                    <span className={cn("font-semibold tabular-nums", remaining !== 0 ? "text-amber-500" : "")}>
                      {formatPlaidTxnAmountLegacy(remaining)}
                    </span>
                  </p>
                ) : null;
              })()}

              {/* Split rows as cards */}
              <div className="space-y-2">
                {draft.map((row, i) => (
                  <div
                    key={i}
                    className="rounded-lg border border-border bg-muted/30 p-3"
                  >
                    {/* Row header: index + remove */}
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-xs font-medium text-muted-foreground">
                        Part {i + 1}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-6 text-muted-foreground hover:text-destructive"
                        disabled={draft.length <= 1}
                        onClick={() => removeRow(i)}
                        aria-label="Remove split"
                      >
                        ✕
                      </Button>
                    </div>

                    {/* Category + Amount in a row that wraps */}
                    <div className="flex flex-wrap gap-2">
                      <div className="min-w-0 flex-1 overflow-hidden">
                        <Select
                          value={row.category_id == null ? ALL : String(row.category_id)}
                          onValueChange={(v) =>
                            updateRow(i, { category_id: v === ALL ? null : Number(v) })
                          }
                        >
                          <SelectTrigger className="w-full [&_[data-slot=select-value]]:truncate">
                            <SelectValue placeholder="Uncategorized" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={ALL}>Uncategorized</SelectItem>
                            {categories.map((c) => (
                              <SelectItem key={c.id} value={String(c.id)}>
                                {c.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="w-28 shrink-0">
                        <Input
                          inputMode="decimal"
                          className="tabular-nums"
                          placeholder="0.00"
                          value={row.amount_str}
                          onChange={(e) =>
                            updateRow(i, { amount_str: e.target.value })
                          }
                          onBlur={(e) => {
                            // On blur: normalise to 2 dp if valid, keep as-is otherwise
                            const n = parseFloat(e.target.value.replace(",", "."));
                            if (Number.isFinite(n)) {
                              updateRow(i, { amount_str: n.toFixed(2) });
                            }
                          }}
                        />
                      </div>
                    </div>

                    <Input
                      className="mt-2"
                      placeholder="Note (optional)"
                      value={row.note}
                      onChange={(e) => updateRow(i, { note: e.target.value })}
                    />
                  </div>
                ))}
              </div>

              <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={addRow}>
                + Add part
              </Button>
            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="shrink-0 border-t border-border px-5 py-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">{totalLabel}</p>
            <div className="flex gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={handleSave}
                disabled={isLoading || setSplitsMutation.isPending || !transaction}
              >
                {setSplitsMutation.isPending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Saving…
                  </>
                ) : (
                  "Save splits"
                )}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TransactionsSkeleton() {
  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-4">
          <div className="size-10 animate-pulse rounded-full bg-muted" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-48 animate-pulse rounded bg-muted" />
            <div className="h-3 w-32 animate-pulse rounded bg-muted" />
          </div>
          <div className="h-6 w-20 animate-pulse rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}

export default function TransactionsPage() {
  const queryClient = useQueryClient();
  const detailTxIdRef = useRef<number | null>(null);
  const splitTxRef = useRef<Transaction | null>(null);
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const highlightIdRaw = searchParams.get("highlight");
  const highlightId =
    highlightIdRaw != null && highlightIdRaw !== "" && Number.isFinite(Number(highlightIdRaw))
      ? Number(highlightIdRaw)
      : null;

  const [month, setMonth] = useState(currentMonth);
  const [accountId, setAccountId] = useState<string>(ALL);
  const [categoryId, setCategoryId] = useState<string>(ALL);
  const [tagFilterId, setTagFilterId] = useState<string>(ALL);
  const [channel, setChannel] = useState<string>(ALL);
  const [personId, setPersonId] = useState<string>(ALL);
  const [searchInput, setSearchInput] = useState("");
  /**
   * "Show internal transactions" toggle — default OFF so intra-family
   * transfers (classifier's `internal_transfer` class) are hidden from the
   * list the same way they are excluded from income/expense reports. Users
   * can flip it on to audit the pairs or override a mis-classification.
   */
  const [showInternalTransfers, setShowInternalTransfers] = useState(false);
  const deferredSearch = useDeferredValue(searchInput);

  const filtersAreDefault =
    accountId === ALL &&
    categoryId === ALL &&
    tagFilterId === ALL &&
    channel === ALL &&
    personId === ALL &&
    searchInput.trim() === "" &&
    showInternalTransfers === false;

  const resetFilters = useCallback(() => {
    setAccountId(ALL);
    setCategoryId(ALL);
    setTagFilterId(ALL);
    setChannel(ALL);
    setPersonId(ALL);
    setSearchInput("");
    setShowInternalTransfers(false);
  }, []);

  const [detailOpen, setDetailOpen] = useState(false);
  const [detailTxId, setDetailTxId] = useState<number | null>(null);
  const [splitTx, setSplitTx] = useState<Transaction | null>(null);
  const [splitOpen, setSplitOpen] = useState(false);
  const [addCashOpen, setAddCashOpen] = useState(false);
  const [internalTransferSettingsOpen, setInternalTransferSettingsOpen] = useState(false);

  detailTxIdRef.current = detailTxId;
  splitTxRef.current = splitTx;

  const listFilters: TransactionFilters = useMemo(
    () => ({
      month,
      account_id: accountId === ALL ? undefined : Number(accountId),
      category_id: categoryId === ALL ? undefined : Number(categoryId),
      tag_id: tagFilterId === ALL ? undefined : Number(tagFilterId),
      search: deferredSearch.trim() || undefined,
      channel: channel === ALL ? undefined : channel,
      user_id: personId === ALL ? undefined : Number(personId),
      // Only send the flag when the user opted into hiding — keeps the
      // backend contract minimal (`undefined` == default include).
      exclude_internal_transfers: showInternalTransfers ? undefined : true,
    }),
    [month, accountId, categoryId, tagFilterId, channel, deferredSearch, personId, showInternalTransfers],
  );

  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => accountsApi.list(true),
  });

  const { data: members = [] } = useQuery({
    queryKey: ["members"],
    queryFn: () => membersApi.list(),
  });

  const { data: categories = [] } = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
  });

  const { data: allTags = [] } = useQuery({
    queryKey: ["tags"],
    queryFn: () => tagsApi.list(),
  });

  const {
    data: transactions = [],
    isLoading,
    isFetching,
    error,
  } = useQuery({
    queryKey: ["transactions", listFilters],
    queryFn: () => transactionsApi.list(listFilters),
  });

  useEffect(() => {
    if (highlightId == null || isLoading || transactions.length === 0) return;
    const el = document.getElementById(`txn-row-${highlightId}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      window.setTimeout(() => {
        if (typeof window !== "undefined" && window.history?.replaceState) {
          window.history.replaceState(null, "", pathname);
        }
      }, 400);
    }
  }, [highlightId, isLoading, transactions, pathname]);

  const categoryById = useMemo(() => {
    const m = new Map<number, Category>();
    categories.forEach((c) => m.set(c.id, c));
    return m;
  }, [categories]);

  const updateMutation = useMutation({
    mutationFn: (payload: { id: number; category_id?: number | null; user_note?: string }) =>
      transactionsApi.update(payload.id, {
        category_id: payload.category_id,
        user_note: payload.user_note,
      }),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["transaction", variables.id] });
    },
    onError: onMutationError("Failed to save changes."),
  });

  const togglePrivateMutation = useMutation({
    mutationFn: ({ id, is_private }: { id: number; is_private: boolean }) =>
      transactionsApi.update(id, { is_private }),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["transaction", variables.id] });
    },
    onError: onMutationError("Could not update privacy."),
  });

  /**
   * Pin / un-pin a row to a specific `transaction_class`. Supersedes the
   * pre-V2 `is_internal_transfer` boolean toggle — now the user can mark a
   * row as any of the four canonical classes (or "auto" = clear override).
   * The backend writes `manual_class_override` so the classifier never
   * overwrites the user's pick on the next sync.
   */
  const setClassOverrideMutation = useMutation({
    mutationFn: ({
      id,
      override,
    }: {
      id: number;
      override: TransactionClass | null;
    }) =>
      transactionsApi.update(id, {
        transaction_class: override ?? undefined,
        // When clearing the override we drop the legacy
        // `is_internal_transfer` mirror back to false so both knobs stay
        // in sync. The backend's patch handler does the same on its own,
        // but the round-trip is immediate and keeps the UI honest if the
        // fetch races with the next list invalidation.
        ...(override == null ? { is_internal_transfer: false } : {}),
      }),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["transaction", variables.id] });
      // Class changes feed every income/expense aggregate — refresh
      // reports and budgets so the change is visible immediately.
      await queryClient.invalidateQueries({ queryKey: ["reports"] });
      await queryClient.invalidateQueries({ queryKey: ["budgets"] });
    },
    onError: onMutationError("Could not update transaction class."),
  });

  const addTagMutation = useMutation({
    mutationFn: ({ txId, tagId }: { txId: number; tagId: number }) =>
      transactionsApi.addTag(txId, tagId),
    onSuccess: async (_, { txId }) => {
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["transaction", txId] });
    },
    onError: onMutationError("Could not add tag."),
  });

  const removeTagMutation = useMutation({
    mutationFn: ({ txId, tagId }: { txId: number; tagId: number }) =>
      transactionsApi.removeTag(txId, tagId),
    onSuccess: async (_, { txId }) => {
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["transaction", txId] });
    },
    onError: onMutationError("Could not remove tag."),
  });

  const deleteCashMutation = useMutation({
    mutationFn: (id: number) => transactionsApi.delete(id),
    onSuccess: async (_, deletedId) => {
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      await queryClient.invalidateQueries({ queryKey: ["transaction", deletedId] });
      await queryClient.invalidateQueries({ queryKey: ["transaction-splits", deletedId] });
      await queryClient.invalidateQueries({ queryKey: ["accounts", "cash-wallet"] });
      await queryClient.invalidateQueries({ queryKey: ["accounts"] });
      await queryClient.invalidateQueries({ queryKey: TRANSACTIONS_DATE_RANGE_QUERY_KEY });
      if (detailTxIdRef.current === deletedId) {
        setDetailOpen(false);
        setDetailTxId(null);
      }
      if (splitTxRef.current?.id === deletedId) {
        setSplitOpen(false);
        setSplitTx(null);
      }
    },
    onError: onMutationError("Could not delete transaction."),
  });

  const deleteCashById = useCallback(
    (id: number) => deleteCashMutation.mutateAsync(id),
    [deleteCashMutation],
  );

  const requestDeleteCashTx = useCallback(
    async (tx: Transaction, e: MouseEvent) => {
      e.stopPropagation();
      const ok = await confirm({
        title: "Delete cash transaction?",
        description: `"${displayName(tx)}" will be removed and your Cash wallet balance adjusted.`,
        destructive: true,
        confirmLabel: "Delete",
      });
      if (!ok) return;
      try {
        await deleteCashMutation.mutateAsync(tx.id);
      } catch {
        /* mutation onError surfaces the error via toast */
      }
    },
    [deleteCashMutation],
  );

  const handleExportCsv = useCallback(async () => {
    const exportFilters: TransactionFilters = {
      month: listFilters.month,
      account_id: listFilters.account_id,
      category_id: listFilters.category_id,
      tag_id: listFilters.tag_id,
      exclude_internal_transfers: listFilters.exclude_internal_transfers,
    };
    const url = transactionsApi.exportUrl(exportFilters);
    try {
      const res = await fetch(url, {
        credentials: "include",
        headers: getAuthHeaders() as Record<string, string>,
      });
      if (!res.ok) {
        throw new Error(`Export failed (${res.status})`);
      }
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = `transactions-${month || "export"}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Export failed";
      notify.error(msg);
    }
  }, [
    listFilters.month,
    listFilters.account_id,
    listFilters.category_id,
    listFilters.tag_id,
    listFilters.exclude_internal_transfers,
    month,
  ]);

  const loadingList = isLoading || isFetching;

  return (
    <AppLayout>
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Transactions</h1>
            <p className="text-sm text-muted-foreground">
              Review, tag, and categorize imported, cash, and linked account activity.
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => setInternalTransferSettingsOpen(true)}
              title="Internal-transfer settings"
              aria-label="Internal-transfer settings"
            >
              <Settings className="size-4" />
            </Button>
            <Button type="button" onClick={() => setAddCashOpen(true)}>
              Add cash transaction
            </Button>
          </div>
        </div>

        <AddCashTransactionDialog open={addCashOpen} onOpenChange={setAddCashOpen} categories={categories} />
        <InternalTransferSettingsDialog
          open={internalTransferSettingsOpen}
          onOpenChange={setInternalTransferSettingsOpen}
        />

        <Card className="border-border/80 shadow-sm">
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Filters</CardTitle>
            <CardDescription>Narrow down by period, account, category, channel, or text.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3 lg:flex lg:flex-row lg:flex-wrap lg:items-end">
              <div className="col-span-full grid min-w-0 gap-2 sm:col-span-2 md:col-span-3 lg:col-span-1 lg:w-[min(100%,17.5rem)] lg:max-w-none lg:shrink-0">
                <Label>Month</Label>
                <MonthYearPicker value={month} onChange={setMonth} />
              </div>

              <div className="grid min-w-0 gap-2 lg:min-w-[200px] lg:flex-1">
                <Label>Account</Label>
                <Select value={accountId} onValueChange={setAccountId}>
                  <SelectTrigger className="w-full [&_[data-slot=select-value]]:truncate">
                    <SelectValue placeholder="Account" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>All accounts</SelectItem>
                    {accounts.map((a) => (
                      <SelectItem key={a.id} value={String(a.id)}>
                        {formatAccountPickerLabel(a)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid min-w-0 gap-2 lg:min-w-[200px] lg:flex-1">
                <Label>Category</Label>
                <Select value={categoryId} onValueChange={setCategoryId}>
                  <SelectTrigger className="w-full [&_[data-slot=select-value]]:truncate">
                    <SelectValue placeholder="Category" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>All categories</SelectItem>
                    {categories.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid min-w-0 gap-2 lg:min-w-[160px]">
                <Label>Tag</Label>
                <Select value={tagFilterId} onValueChange={setTagFilterId}>
                  <SelectTrigger className="w-full [&_[data-slot=select-value]]:truncate">
                    <SelectValue placeholder="Tag" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>All tags</SelectItem>
                    {allTags.map((t) => (
                      <SelectItem key={t.id} value={String(t.id)}>
                        {t.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {members.length > 1 && (
                <div className="grid min-w-0 gap-2 lg:min-w-[150px]">
                  <Label>Person</Label>
                  <Select value={personId} onValueChange={setPersonId}>
                    <SelectTrigger className="w-full [&_[data-slot=select-value]]:truncate">
                      <SelectValue placeholder="Person" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL}>Everyone</SelectItem>
                      {members.map((m) => (
                        <SelectItem key={m.id} value={String(m.id)}>
                          {m.username}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              <div className="grid min-w-0 gap-2 lg:min-w-[160px]">
                <Label>Channel</Label>
                <Select value={channel} onValueChange={setChannel}>
                  <SelectTrigger className="w-full [&_[data-slot=select-value]]:truncate">
                    <SelectValue placeholder="Channel" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>All channels</SelectItem>
                    <SelectItem value="online">Online</SelectItem>
                    <SelectItem value="in store">In store</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="col-span-1 grid gap-2 sm:col-span-2 md:col-span-3 lg:col-span-1 lg:min-w-[220px] lg:flex-[2]">
                <Label htmlFor="search">Search</Label>
                <Input
                  id="search"
                  placeholder="Merchant, name, note…"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                />
              </div>

              <Button type="button" variant="secondary" className="col-span-2 gap-2 sm:col-span-1 lg:col-auto lg:shrink-0" onClick={handleExportCsv}>
                <Download className="size-4" />
                Export CSV
              </Button>
            </div>

            <div className="flex flex-col gap-3 border-t border-border/70 pt-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-2.5">
                <Switch
                  id="show-internal-transfers"
                  checked={showInternalTransfers}
                  onCheckedChange={setShowInternalTransfers}
                  className="mt-0.5"
                />
                <div className="flex flex-col gap-0.5">
                  <Label htmlFor="show-internal-transfers" className="cursor-pointer text-sm">
                    Show internal transactions
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    Hidden by default. Toggle on to audit intra-family transfers excluded from income / expense totals.
                  </p>
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="gap-1.5 self-end text-muted-foreground hover:text-foreground sm:self-auto"
                onClick={resetFilters}
                disabled={filtersAreDefault}
                title="Clear account, category, tag, channel, person, search, and internal-transfer filters"
              >
                Reset filters
              </Button>
            </div>
          </CardContent>
        </Card>

        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error instanceof Error ? error.message : "Failed to load transactions"}
          </p>
        ) : null}

        {isLoading ? <TransactionsSkeleton /> : null}

        {!isLoading && transactions.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
              <p className="text-lg font-medium">No transactions</p>
              <p className="max-w-sm text-sm text-muted-foreground">
                Try changing the month or clearing filters to see more results.
              </p>
            </CardContent>
          </Card>
        ) : null}

        {!isLoading && transactions.length > 0 ? (
          <>
            <div className="space-y-2 md:hidden">
              {transactions.map((tx) => (
                <TransactionMobileCard
                  key={tx.id}
                  tx={tx}
                  highlight={highlightId === tx.id}
                  loadingList={loadingList}
                  onOpen={() => {
                    setDetailTxId(tx.id);
                    setDetailOpen(true);
                  }}
                  onDeleteCash={
                    tx.source === "cash" ? (ev) => requestDeleteCashTx(tx, ev) : undefined
                  }
                  cashDeletePending={
                    deleteCashMutation.isPending && deleteCashMutation.variables === tx.id
                  }
                />
              ))}
            </div>

            <Card className="hidden overflow-hidden border-border/80 shadow-sm md:block">
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="w-[44px]" />
                        <TableHead>Transaction</TableHead>
                        <TableHead className="hidden md:table-cell">Category</TableHead>
                        <TableHead className="hidden sm:table-cell">Date</TableHead>
                        <TableHead className="text-right">Amount</TableHead>
                        <TableHead className="hidden min-w-[148px] text-right sm:table-cell">
                          Actions
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {transactions.map((tx) => {
                        const cat =
                          tx.category_id != null ? categoryById.get(tx.category_id) : undefined;
                        const catLabel =
                          cat?.name ?? tx.pfc_detailed ?? tx.pfc_primary ?? "Uncategorized";
                        const availableTagsToAdd = allTags.filter(
                          (t) => !tx.tags.some((x) => x.id === t.id),
                        );

                        return (
                          <FragmentRow
                            key={tx.id}
                            tx={tx}
                            catLabel={catLabel}
                            categoryById={categoryById}
                            availableTagsToAdd={availableTagsToAdd}
                            loadingList={loadingList}
                            highlight={highlightId === tx.id}
                            onRowClick={() => {
                              setDetailTxId(tx.id);
                              setDetailOpen(true);
                            }}
                            onOpenSplit={(e) => {
                              e.stopPropagation();
                              setDetailOpen(false);
                              setDetailTxId(null);
                              setSplitTx(tx);
                              setSplitOpen(true);
                            }}
                            onAddTag={(tagId) => addTagMutation.mutate({ txId: tx.id, tagId })}
                            onRemoveTag={(tagId, e) => {
                              e.stopPropagation();
                              removeTagMutation.mutate({ txId: tx.id, tagId });
                            }}
                            onDeleteCash={
                              tx.source === "cash"
                                ? (ev) => requestDeleteCashTx(tx, ev)
                                : undefined
                            }
                            cashDeletePending={
                              deleteCashMutation.isPending &&
                              deleteCashMutation.variables === tx.id
                            }
                          />
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </>
        ) : null}

        <TransactionDetailsDialog
          transactionId={detailTxId}
          open={detailOpen && detailTxId != null}
          onOpenChange={(o) => {
            setDetailOpen(o);
            if (!o) setDetailTxId(null);
          }}
          categories={categories}
          onSave={async (payload) => {
            if (detailTxId == null) return;
            await updateMutation.mutateAsync({
              id: detailTxId,
              category_id: payload.category_id,
              user_note: payload.user_note,
            });
          }}
          isSaving={updateMutation.isPending}
          onDeleteCash={deleteCashById}
          isDeletingCash={
            deleteCashMutation.isPending &&
            detailTxId != null &&
            deleteCashMutation.variables === detailTxId
          }
          onTogglePrivate={(id, isPrivate) =>
            togglePrivateMutation.mutate({ id, is_private: isPrivate })
          }
          isTogglingPrivate={
            togglePrivateMutation.isPending &&
            detailTxId != null &&
            togglePrivateMutation.variables?.id === detailTxId
          }
          onSetClassOverride={(id, override) =>
            setClassOverrideMutation.mutate({ id, override })
          }
          isSettingClassOverride={
            setClassOverrideMutation.isPending &&
            detailTxId != null &&
            setClassOverrideMutation.variables?.id === detailTxId
          }
        />

        <SplitTransactionDialog
          transaction={splitTx}
          open={splitOpen}
          onOpenChange={(o) => {
            setSplitOpen(o);
            if (!o) setSplitTx(null);
          }}
          categories={categories}
        />
      </div>
    </AppLayout>
  );
}

function FragmentRow({
  tx,
  catLabel,
  categoryById,
  availableTagsToAdd,
  loadingList,
  highlight,
  onRowClick,
  onOpenSplit,
  onAddTag,
  onRemoveTag,
  onDeleteCash,
  cashDeletePending,
}: {
  tx: Transaction;
  catLabel: string;
  categoryById: Map<number, Category>;
  availableTagsToAdd: Tag[];
  loadingList: boolean;
  highlight?: boolean;
  onRowClick: () => void;
  onOpenSplit: (e: MouseEvent) => void;
  onAddTag: (tagId: number) => void;
  onRemoveTag: (tagId: number, e: MouseEvent) => void;
  onDeleteCash?: (e: MouseEvent) => void;
  cashDeletePending?: boolean;
}) {
  const cat = tx.category_id != null ? categoryById.get(tx.category_id) : undefined;
  const hasSplits = tx.splits && tx.splits.length > 0;

  return (
    <>
      <TableRow
        id={`txn-row-${tx.id}`}
        data-txn-id={tx.id}
        className={cn(
          "cursor-pointer transition-[box-shadow] duration-300",
          highlight && "ring-2 ring-primary ring-offset-2 ring-offset-background",
          tx.is_private &&
            "relative bg-amber-500/[0.04] before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:border-l-2 before:border-dashed before:border-amber-500/60",
        )}
        onClick={onRowClick}
      >
        <TableCell className="align-middle">
          <MerchantAvatar tx={tx} />
        </TableCell>
        <TableCell className="max-w-[280px] min-w-0 align-middle">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span
                className="line-clamp-1 min-w-0 break-all font-medium leading-tight"
                title={rawTransactionTitle(tx) || displayName(tx)}
              >
                {displayName(tx)}
              </span>
              {tx.is_pending ? (
                <Badge
                  variant="secondary"
                  className="text-[10px] uppercase tracking-wide"
                  title="Awaiting clearing — amount may change when the bank posts the transaction."
                >
                  Pending
                </Badge>
              ) : null}
              {tx.is_private ? (
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-400">
                        <EyeOff className="size-3" />
                        Private
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p className="max-w-[240px] text-xs">
                        Only you can see the amount and details. Other family members see this row as hidden.
                      </p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              ) : null}
              {tx.is_internal_transfer ? (
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-sky-700 dark:text-sky-400">
                        <ArrowLeftRight className="size-3" />
                        Internal
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p className="max-w-[240px] text-xs">
                        Flagged as an intra-family transfer. Excluded from income and expense totals to avoid double-counting.
                      </p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {channelIcon(tx.payment_channel)}
              <AccountChip tx={tx} />
              {onDeleteCash ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive sm:hidden"
                  title="Delete cash transaction"
                  disabled={loadingList || cashDeletePending}
                  onClick={onDeleteCash}
                >
                  <Trash2 className="size-4" aria-hidden />
                  <span className="sr-only">Delete cash transaction</span>
                </Button>
              ) : null}
              <div className="flex flex-wrap gap-1">
                {tx.tags.map((t) => (
                  <Badge
                    key={t.id}
                    variant="outline"
                    className="border-transparent px-2 py-0 text-[11px] font-medium text-white"
                    style={{ backgroundColor: t.color || "var(--muted)" }}
                    asChild
                  >
                    <button
                      type="button"
                      className="inline-flex items-center gap-1"
                      onClick={(e) => onRemoveTag(t.id, e)}
                      title="Remove tag"
                    >
                      {t.name}
                      <span className="opacity-80">×</span>
                    </button>
                  </Badge>
                ))}
              </div>
              {availableTagsToAdd.length > 0 ? (
                <Select
                  key={`add-tag-${tx.id}-${tx.tags.map((t) => t.id).join("-")}`}
                  onValueChange={(v) => onAddTag(Number(v))}
                >
                  <SelectTrigger
                    className="h-7 w-[120px] text-xs"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <SelectValue placeholder="+ Tag" />
                  </SelectTrigger>
                  <SelectContent onClick={(e) => e.stopPropagation()}>
                    {availableTagsToAdd.map((t) => (
                      <SelectItem key={t.id} value={String(t.id)}>
                        {t.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
            </div>
            {/* Category / splits — mobile only */}
            <div className="md:hidden">
              {hasSplits ? (
                <SplitBreakdown splits={tx.splits} categoryById={categoryById} />
              ) : (
                <CategoryBadgeInline tx={tx} catLabel={catLabel} category={cat} />
              )}
            </div>
          </div>
        </TableCell>

        {/* Category / splits — desktop */}
        <TableCell className="hidden align-top md:table-cell">
          {hasSplits ? (
            <SplitBreakdown splits={tx.splits} categoryById={categoryById} />
          ) : (
            <CategoryBadgeInline tx={tx} catLabel={catLabel} category={cat} />
          )}
        </TableCell>

        <TableCell className="hidden align-middle text-muted-foreground sm:table-cell">
          {displayDate(tx)}
        </TableCell>

        {/* Amount — shows split indicator when split exists */}
        <TableCell className="text-right align-middle">
          <div className="flex flex-col items-end gap-0.5">
            <PlaidTxnAmount cents={tx.amount_cents} size="base" tone="flow" />
            {hasSplits && (
              <span className="flex items-center gap-0.5 text-[10px] font-medium text-muted-foreground">
                <Columns2 className="size-2.5" />
                {tx.splits.length} parts
              </span>
            )}
          </div>
        </TableCell>

        <TableCell className="hidden text-right align-middle sm:table-cell">
          <div className="flex flex-wrap items-center justify-end gap-1">
            {onDeleteCash ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1 text-destructive hover:bg-destructive/10 hover:text-destructive"
                title="Delete cash transaction"
                disabled={loadingList || cashDeletePending}
                onClick={onDeleteCash}
              >
                {cashDeletePending ? (
                  <Loader2 className="size-3.5 animate-spin" aria-hidden />
                ) : (
                  <Trash2 className="size-3.5" aria-hidden />
                )}
                <span className="max-sm:sr-only">Delete</span>
              </Button>
            ) : null}
            <Button
              type="button"
              variant={hasSplits ? "secondary" : "outline"}
              size="sm"
              className={cn("gap-1", hasSplits && "text-foreground")}
              disabled={loadingList}
              onClick={onOpenSplit}
            >
              <Columns2 className="size-3.5" />
              {hasSplits ? "Edit" : "Split"}
            </Button>
          </div>
        </TableCell>
      </TableRow>
    </>
  );
}

function CategoryBadgeInline({
  tx,
  catLabel,
  category,
}: {
  tx: Transaction;
  catLabel: string;
  category: Category | undefined;
}) {
  const iconUrl = category?.pfc_icon_url ?? tx.pfc_icon_url;

  return (
    <Badge variant="secondary" className="max-w-full gap-1.5 py-1 pr-2 pl-1 font-normal">
      {iconUrl ? (
        <img src={iconUrl} alt="" className="size-5 shrink-0 rounded object-contain" />
      ) : null}
      <span className="truncate">{catLabel}</span>
    </Badge>
  );
}

/** Shows split parts in place of the category badge when a transaction is split. */
function SplitBreakdown({
  splits,
  categoryById,
}: {
  splits: TransactionSplit[];
  categoryById: Map<number, Category>;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      {splits.map((s, i) => {
        const cat = s.category_id != null ? categoryById.get(s.category_id) : undefined;
        const catName = cat?.name ?? "Uncategorized";
        return (
          <div
            key={i}
            className="flex min-w-0 items-center gap-1.5 rounded-md bg-muted/60 px-2 py-0.5 text-xs"
          >
            <Columns2 className="size-3 shrink-0 text-muted-foreground/70" />
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{catName}</span>
            <PlaidTxnAmount cents={s.amount_cents} size="inherit" tone="flow" className="shrink-0 text-xs" />
          </div>
        );
      })}
    </div>
  );
}
