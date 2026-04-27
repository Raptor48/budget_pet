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
import { useEffect, useMemo, useState } from "react";
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
import { Switch } from "@/components/ui/switch";
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
        referenceAmountCents={
          pickerForId
            ? list.data?.find((r) => r.id === pickerForId)?.total_cents ?? null
            : null
        }
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

/**
 * Fetch + cache a receipt image as an in-memory blob URL. The naive
 * ``<img src="…/image">`` works only same-origin — once frontend and
 * backend deploy to different hosts (Railway in production), the
 * session cookie isn't sent and the Bearer-token fallback in
 * :func:`apiRequest` can't ride along on an ``<img>`` tag (no custom
 * headers). Fetching here and using ``URL.createObjectURL`` solves both.
 */
function useAuthedReceiptImage(receiptId: number | null, hasImage: boolean) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setSrc(null);
    setError(false);
    if (!receiptId || !hasImage) {
      setLoading(false);
      return;
    }
    setLoading(true);
    let cancelled = false;
    let blobUrl: string | null = null;
    botApi
      .fetchReceiptImageBlob(receiptId)
      .then((blob) => {
        if (cancelled) return;
        blobUrl = URL.createObjectURL(blob);
        setSrc(blobUrl);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError(true);
        setLoading(false);
      });
    return () => {
      cancelled = true;
      // Free the blob even if the user closes the modal mid-fetch — we
      // don't want a few hundred KB hanging on per receipt opened.
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [receiptId, hasImage]);

  return { src, error, loading };
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
  const image = useAuthedReceiptImage(id, !!r?.has_image);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      {/*
        max-h + flex column lets the body scroll while the header and the
        action footer stay anchored. Without this the image (often a tall
        portrait shot of a paper receipt) would push the Delete / Attach
        buttons below the viewport and the user couldn't reach them
        without zooming the browser out.
      */}
      <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 p-0">
        <DialogHeader className="flex-row items-center justify-between gap-3 border-b px-5 py-3">
          <DialogTitle className="flex min-w-0 items-center gap-2 truncate">
            <ReceiptIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="truncate">{r?.merchant_name || "Receipt"}</span>
          </DialogTitle>
          {/*
            Delete moved into the header so it's always reachable, even on
            tall receipts where the body scrolls. The dialog's close button
            sits to the right of this via Radix's built-in.
          */}
          {r ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(r.merchant_name)}
              disabled={deleting}
              className="mr-6 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
              title="Delete receipt"
            >
              {deleting ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="mr-1 h-4 w-4" />
              )}
              Delete
            </Button>
          ) : null}
        </DialogHeader>

        {!r ? (
          <div className="grid gap-4 p-5 sm:grid-cols-[1fr,1fr]">
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
          <div className="grid flex-1 gap-4 overflow-y-auto p-5 sm:grid-cols-[minmax(0,1fr),minmax(0,1fr)]">
            <div className="flex items-start justify-center overflow-hidden rounded-md border bg-muted/30">
              {r.has_image && !image.error ? (
                image.loading || !image.src ? (
                  <div className="grid aspect-[3/4] w-full place-items-center text-sm text-muted-foreground">
                    <Loader2
                      className="h-5 w-5 animate-spin text-muted-foreground"
                      aria-label="Loading image"
                    />
                  </div>
                ) : (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={image.src}
                    alt="Receipt"
                    /*
                      object-contain + capped height keeps tall portrait
                      receipts inside the viewport and never crops their
                      content; the user can still see the whole photo.
                      Width is full-card so landscape receipts also fit.
                    */
                    className="max-h-[60vh] w-full object-contain"
                  />
                )
              ) : (
                <div className="grid aspect-[3/4] w-full place-items-center text-sm text-muted-foreground">
                  <div className="flex flex-col items-center gap-1.5">
                    <ImageOff className="h-6 w-6" aria-hidden />
                    {image.error ? "Image couldn't load." : "No image stored."}
                  </div>
                </div>
              )}
            </div>
            <div className="flex min-w-0 flex-col gap-3">
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
            </div>
          </div>
        )}

        {/*
          Sticky footer for the link/unlink/log-as-cash actions. Always
          visible regardless of body scroll position so the primary action
          on an unlinked receipt ("Attach" / "Log as cash") is one tap
          away.
        */}
        {r ? (
          <div className="border-t bg-muted/20 px-5 py-3 text-sm">
            {r.transaction_id ? (
              <div className="flex flex-wrap items-center justify-between gap-2">
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
        ) : null}
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
  referenceAmountCents,
  onClose,
  onPick,
}: {
  receiptId: number | null;
  /** Total of the receipt being attached, used by the ±$1 filter. */
  referenceAmountCents: number | null;
  onClose: () => void;
  onPick: (transactionId: number) => void;
}) {
  const [search, setSearch] = useState("");
  // ±$1 default-ON when we know the receipt amount — that's exactly the
  // shortcut the user asked for. Toggling it off falls back to the full
  // search list.
  const [matchAmount, setMatchAmount] = useState(true);
  const open = receiptId != null;
  const transactions = useQuery({
    queryKey: ["transactions", "picker", search],
    queryFn: () =>
      transactionsApi.list({
        search: search.trim() || undefined,
        exclude_internal_transfers: true,
        limit: 100,
      }),
    enabled: open,
    staleTime: 10_000,
  });

  // ±$1 = 100 cents, applied client-side because there's no backend
  // amount-range filter on /api/transactions today. With limit=100 most
  // households' last few weeks are covered without paging.
  const filtered = useMemo(() => {
    const all = transactions.data ?? [];
    if (!matchAmount || referenceAmountCents == null) return all;
    return all.filter(
      (t: Transaction) =>
        Math.abs(t.amount_cents - referenceAmountCents) <= 100,
    );
  }, [transactions.data, matchAmount, referenceAmountCents]);

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setSearch("");
          setMatchAmount(true);
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
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
              autoFocus
            />
          </div>
          {referenceAmountCents != null ? (
            <label className="flex cursor-pointer items-center justify-between rounded-md border bg-muted/20 px-3 py-2 text-sm">
              <span className="flex items-center gap-2">
                <Switch
                  checked={matchAmount}
                  onCheckedChange={setMatchAmount}
                  aria-label="Toggle amount match"
                />
                <span className="font-medium">
                  Match amount ±$1
                </span>
              </span>
              <span className="text-xs text-muted-foreground">
                Receipt total: {formatCents(referenceAmountCents)}
              </span>
            </label>
          ) : null}
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
          ) : !filtered.length ? (
            <p className="rounded-md border border-dashed py-6 text-center text-sm text-muted-foreground">
              {matchAmount && referenceAmountCents != null
                ? `No transaction within ±$1 of ${formatCents(referenceAmountCents)}. Disable the match toggle to see everything.`
                : "No transactions match. Try a different search."}
            </p>
          ) : (
            <ul className="max-h-[55vh] divide-y overflow-y-auto rounded-md border">
              {filtered.map((t: Transaction) => (
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
