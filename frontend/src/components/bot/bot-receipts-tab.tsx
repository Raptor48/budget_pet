"use client";

/**
 * Receipts tab — gallery of OCR'd photos that the user can attach to any
 * existing transaction (or "log as cash" for receipts that Plaid will
 * never see). Receipts arrive unlinked by default; the bot now waits for
 * the user to either run the cash flow or attach to an imported tx.
 *
 * The receipt's image bytes live in Postgres (BYTEA). The frontend just
 * issues a GET /api/bot/receipts/:id/image which authenticates against
 * the session cookie before streaming the bytes back. If the image fails
 * to load (404, network) we surface a placeholder rather than an empty
 * frame so the user can still see the line items + totals.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Camera,
  CircleDashed,
  ImageOff,
  Link2,
  Link2Off,
  Loader2,
  Receipt as ReceiptIcon,
  Search,
  Trash2,
  Wallet,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  botApi,
  transactionsApi,
  type ReceiptRow,
} from "@/lib/api";
import type { Transaction } from "@/types/v2";
import { confirm, notify, onMutationError } from "@/lib/notify";

import { formatCents, formatDate } from "./bot-helpers";

export function BotReceiptsTab() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["bot", "receipts"],
    queryFn: () => botApi.listReceipts(40),
  });
  const [openId, setOpenId] = useState<number | null>(null);

  const drop = useMutation({
    mutationFn: (id: number) => botApi.deleteReceipt(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "receipts"] });
      setOpenId(null);
      notify.success("Receipt deleted.");
    },
    onError: onMutationError("Couldn't delete that receipt."),
  });

  const link = useMutation({
    mutationFn: ({ id, txnId }: { id: number; txnId: number | null }) =>
      botApi.linkReceipt(id, txnId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "receipts"] });
      qc.invalidateQueries({ queryKey: ["bot", "receipt"] });
      notify.success("Receipt linked.");
    },
    onError: onMutationError("Couldn't link the receipt."),
  });

  const unlink = useMutation({
    mutationFn: (id: number) => botApi.linkReceipt(id, null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "receipts"] });
      qc.invalidateQueries({ queryKey: ["bot", "receipt"] });
      notify.success("Receipt detached.");
    },
    onError: onMutationError("Couldn't detach the receipt."),
  });

  const logAsCash = useMutation({
    mutationFn: (id: number) => botApi.logReceiptAsCash(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "receipts"] });
      qc.invalidateQueries({ queryKey: ["bot", "receipt"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
      notify.success("Logged as cash.");
    },
    onError: onMutationError("Couldn't log as cash."),
  });

  const [pickerForId, setPickerForId] = useState<number | null>(null);

  const requestDelete = async (id: number, name: string | null | undefined) => {
    const ok = await confirm({
      title: "Delete receipt?",
      description: name
        ? `${name} — the linked cash transaction stays put; only the photo + lines are removed.`
        : "The linked cash transaction stays put; only the photo + lines are removed.",
      destructive: true,
      confirmLabel: "Delete",
    });
    if (ok) drop.mutate(id);
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Send a photo of any receipt to the Telegram bot — it gets parsed via
        OCR and saved as a cash transaction. Tap a row to see the photo and
        line items.
      </p>

      {list.isLoading ? (
        <ul className="divide-y rounded-md border">
          {Array.from({ length: 4 }).map((_, i) => (
            <li key={i} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="flex items-center gap-3">
                <Skeleton className="h-8 w-8 rounded-md" />
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-48" />
                </div>
              </div>
              <Skeleton className="h-4 w-16" />
            </li>
          ))}
        </ul>
      ) : !list.data?.length ? (
        <div className="grid place-items-center rounded-md border border-dashed py-12 text-center">
          <Camera className="mb-2 h-7 w-7 text-muted-foreground" aria-hidden />
          <p className="mb-1 text-sm font-medium">No receipts yet</p>
          <p className="text-xs text-muted-foreground">
            Send a photo to the Telegram bot to get started.
          </p>
        </div>
      ) : (
        <ul className="divide-y rounded-md border">
          {list.data.map((r) => (
            <li
              key={r.id}
              role="button"
              tabIndex={0}
              onClick={() => setOpenId(r.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setOpenId(r.id);
                }
              }}
              className={cn(
                "flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm transition-colors",
                "hover:bg-muted/40 focus-visible:bg-muted/40 cursor-pointer outline-none",
              )}
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
                  <ReceiptIcon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <div className="font-medium">
                    {r.merchant_name || "Receipt"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {formatDate(r.receipt_date)} · captured{" "}
                    {formatDate(r.created_at)}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs">
                {r.parse_status === "failed" ? (
                  <Badge variant="outline" className="gap-1 border-destructive/40 text-destructive">
                    <AlertCircle className="h-3 w-3" />
                    failed
                  </Badge>
                ) : r.parse_status !== "parsed" ? (
                  <Badge variant="outline">{r.parse_status}</Badge>
                ) : null}
                {r.transaction_id ? (
                  <Badge variant="secondary" className="gap-1">
                    <Link2 className="h-3 w-3" />
                    linked
                  </Badge>
                ) : (
                  <Badge variant="outline" className="gap-1 border-amber-500/40 text-amber-600 dark:text-amber-400">
                    <CircleDashed className="h-3 w-3" />
                    unlinked
                  </Badge>
                )}
                <span className="font-mono text-sm">
                  {r.total_cents != null ? formatCents(r.total_cents) : "—"}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      <ReceiptDetail
        id={openId}
        onClose={() => setOpenId(null)}
        onDelete={(name) => openId && requestDelete(openId, name)}
        onUnlink={() => openId && unlink.mutate(openId)}
        onLogAsCash={() => openId && logAsCash.mutate(openId)}
        onAttachClick={() => openId && setPickerForId(openId)}
        deleting={drop.isPending}
        unlinking={unlink.isPending}
        loggingCash={logAsCash.isPending}
      />

      <TransactionPicker
        receiptId={pickerForId}
        onClose={() => setPickerForId(null)}
        onPick={(txnId) => {
          if (pickerForId) {
            link.mutate(
              { id: pickerForId, txnId },
              { onSettled: () => setPickerForId(null) },
            );
          }
        }}
      />
    </div>
  );
}

function ReceiptDetail({
  id,
  onClose,
  onDelete,
  onUnlink,
  onLogAsCash,
  onAttachClick,
  deleting,
  unlinking,
  loggingCash,
}: {
  id: number | null;
  onClose: () => void;
  onDelete: (name: string | null | undefined) => void;
  onUnlink: () => void;
  onLogAsCash: () => void;
  onAttachClick: () => void;
  deleting: boolean;
  unlinking: boolean;
  loggingCash: boolean;
}) {
  const detail = useQuery({
    queryKey: ["bot", "receipt", id],
    queryFn: () => (id ? botApi.getReceipt(id) : Promise.resolve(null)),
    enabled: id != null,
  });
  const r: ReceiptRow | null = detail.data ?? null;
  const open = id != null;
  const [imgFailed, setImgFailed] = useState(false);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ReceiptIcon className="h-4 w-4 text-muted-foreground" />
            {r?.merchant_name || "Receipt"}
          </DialogTitle>
        </DialogHeader>
        {!r ? (
          <div className="grid gap-4 sm:grid-cols-[1fr,1fr]">
            <Skeleton className="aspect-[3/4] w-full" />
            <div className="space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="mt-3 h-3 w-20" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-full" />
            </div>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-[1fr,1fr]">
            <div className="overflow-hidden rounded-md border bg-muted/30">
              {r.has_image && id && !imgFailed ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={botApi.receiptImageUrl(id)}
                  alt="Receipt"
                  className="w-full object-cover transition-opacity duration-300"
                  onError={() => setImgFailed(true)}
                  onLoad={(e) => e.currentTarget.classList.remove("opacity-0")}
                />
              ) : (
                <div className="grid aspect-[3/4] place-items-center text-sm text-muted-foreground">
                  <div className="flex flex-col items-center gap-1.5">
                    <ImageOff className="h-6 w-6" aria-hidden />
                    {imgFailed ? "Image couldn't load." : "No image stored."}
                  </div>
                </div>
              )}
            </div>
            <div className="flex flex-col gap-3">
              <dl className="grid grid-cols-2 gap-y-1.5 text-sm">
                <dt className="text-muted-foreground">Total</dt>
                <dd className="text-right font-mono font-medium">
                  {r.total_cents != null ? formatCents(r.total_cents) : "—"}
                </dd>
                {r.tax_cents != null ? (
                  <>
                    <dt className="text-muted-foreground">Tax</dt>
                    <dd className="text-right font-mono">
                      {formatCents(r.tax_cents)}
                    </dd>
                  </>
                ) : null}
                <dt className="text-muted-foreground">Date</dt>
                <dd className="text-right">{formatDate(r.receipt_date)}</dd>
              </dl>
              <div>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Lines
                </h3>
                {r.lines.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No line items captured.
                  </p>
                ) : (
                  <ul className="space-y-1 rounded-md border bg-muted/20 p-2 text-sm">
                    {r.lines.map((l) => (
                      <li
                        key={l.id}
                        className="flex items-baseline justify-between gap-2"
                      >
                        <span className="truncate">{l.description}</span>
                        <span className="font-mono text-xs">
                          {formatCents(l.total_cents)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="rounded-md border bg-muted/20 p-2.5 text-sm">
                {r.transaction_id ? (
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Link2 className="h-3.5 w-3.5 text-emerald-500" />
                      <span>Linked to transaction #{r.transaction_id}</span>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={onUnlink}
                      disabled={unlinking}
                    >
                      {unlinking ? (
                        <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Link2Off className="mr-1 h-3.5 w-3.5" />
                      )}
                      Detach
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-amber-600 dark:text-amber-400">
                      Not linked to a transaction yet.
                    </span>
                    <div className="flex gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={onAttachClick}
                      >
                        <Link2 className="mr-1 h-3.5 w-3.5" />
                        Attach…
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={onLogAsCash}
                        disabled={loggingCash}
                      >
                        {loggingCash ? (
                          <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Wallet className="mr-1 h-3.5 w-3.5" />
                        )}
                        Log as cash
                      </Button>
                    </div>
                  </div>
                )}
              </div>
              <div className="mt-auto flex justify-end">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onDelete(r.merchant_name)}
                  disabled={deleting}
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                >
                  {deleting ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="mr-1 h-4 w-4" />
                  )}
                  Delete
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Transaction picker — opens when the user taps "Attach…" on an unlinked
 * receipt. Loads recent transactions, allows free-text search, and on row
 * click resolves with the picked transaction id.
 *
 * Sorting: most-recent date first, deduplicated by id. We don't filter to
 * "matching amount" automatically because Plaid amounts often differ by a
 * cent or two from the receipt due to rounding/tipping discrepancies — the
 * user knows which transaction they meant.
 */
function TransactionPicker({
  receiptId,
  onClose,
  onPick,
}: {
  receiptId: number | null;
  onClose: () => void;
  onPick: (transactionId: number) => void;
}) {
  const [search, setSearch] = useState("");
  const open = receiptId != null;
  const transactions = useQuery({
    queryKey: ["transactions", "picker", search],
    queryFn: () =>
      transactionsApi.list({
        search: search.trim() || undefined,
        exclude_internal_transfers: true,
        limit: 50,
      }),
    enabled: open,
    staleTime: 10_000,
  });

  // Reset search when the dialog closes so reopening starts fresh.
  const memoSearch = useMemo(() => search, [search]);

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setSearch("");
          onClose();
        }
      }}
    >
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Link2 className="h-4 w-4 text-muted-foreground" />
            Attach receipt to a transaction
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search by merchant or description"
              value={memoSearch}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
              autoFocus
            />
          </div>
          {transactions.isLoading ? (
            <ul className="divide-y rounded-md border">
              {Array.from({ length: 6 }).map((_, i) => (
                <li
                  key={i}
                  className="flex items-center justify-between px-3 py-2"
                >
                  <Skeleton className="h-4 w-44" />
                  <Skeleton className="h-4 w-16" />
                </li>
              ))}
            </ul>
          ) : !transactions.data?.length ? (
            <p className="rounded-md border border-dashed py-6 text-center text-sm text-muted-foreground">
              No transactions match. Try a different search.
            </p>
          ) : (
            <ul className="max-h-[55vh] divide-y overflow-y-auto rounded-md border">
              {transactions.data.map((t: Transaction) => (
                <li
                  key={t.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => onPick(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onPick(t.id);
                    }
                  }}
                  className={cn(
                    "flex items-center justify-between gap-3 px-3 py-2 text-sm cursor-pointer outline-none",
                    "hover:bg-muted/40 focus-visible:bg-muted/40",
                  )}
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium">
                      {t.merchant_name || t.display_title || t.name}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {formatDate(t.date)}
                    </div>
                  </div>
                  <span className="font-mono text-sm">
                    {formatCents(t.amount_cents)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
