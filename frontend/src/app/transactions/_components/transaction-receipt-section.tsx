"use client";

/**
 * Receipt breakdown surfaced inside the Transaction details dialog.
 *
 * Driven by ``transaction.has_receipt`` (a JOIN computed in
 * ``web/transactions/repo.py`` so the row knows about its receipt without
 * an extra round-trip per list render). The actual receipt payload —
 * total, lines, image — is fetched on demand when the user expands this
 * section, keeping the list query lean. Closing the section cancels the
 * blob fetch via ``useAuthedReceiptImage``'s cleanup.
 *
 * The receipt itself stays editable from /bot → Receipts; this view is
 * read-only (a "what did I buy" reference, not a re-OCR surface).
 */
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ImageOff, Loader2, Receipt as ReceiptIcon } from "lucide-react";
import { useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { botApi } from "@/lib/api";
import { useAuthedReceiptImage } from "@/lib/use-receipt-image";

function formatCents(cents: number, currency = "USD"): string {
  const sign = cents < 0 ? "-" : "";
  const value = Math.abs(cents) / 100;
  return currency === "USD"
    ? `${sign}$${value.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`
    : `${sign}${value.toFixed(2)} ${currency}`;
}

export function TransactionReceiptSection({
  transactionId,
  hasReceipt,
}: {
  transactionId: number;
  hasReceipt: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  const receipt = useQuery({
    queryKey: ["bot", "receipt-by-transaction", transactionId],
    queryFn: () => botApi.getReceiptByTransaction(transactionId),
    // Don't fire until the user actually expands — the dialog opens
    // "instantly" thanks to placeholderData on the parent query, no
    // reason to add a hidden network call to that critical path.
    enabled: expanded && hasReceipt,
    // 30 s is short enough to pick up edits made in /bot Receipts but
    // long enough that toggling open/close in quick succession doesn't
    // re-fetch — typical user behaviour.
    staleTime: 30_000,
    retry: false,
  });

  const image = useAuthedReceiptImage(
    expanded ? receipt.data?.id ?? null : null,
    !!receipt.data?.has_image,
  );

  if (!hasReceipt) return null;

  return (
    <div className="rounded-md border bg-muted/20 text-sm">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className={cn(
          "flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors",
          "hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        )}
      >
        <span className="flex items-center gap-2">
          <ReceiptIcon className="size-4 text-muted-foreground" aria-hidden />
          <span className="font-medium">Receipt</span>
          {receipt.data?.lines.length ? (
            <span className="text-xs text-muted-foreground">
              · {receipt.data.lines.length}{" "}
              {receipt.data.lines.length === 1 ? "item" : "items"}
            </span>
          ) : null}
        </span>
        <ChevronDown
          className={cn(
            "size-4 transition-transform text-muted-foreground",
            expanded && "rotate-180",
          )}
        />
      </button>

      {expanded ? (
        <div className="border-t px-3 py-3">
          {receipt.isLoading ? (
            <ReceiptSkeleton />
          ) : receipt.isError || !receipt.data ? (
            <p className="text-sm text-muted-foreground">
              Receipt couldn&apos;t load. Try opening it from{" "}
              <strong>Bot → Receipts</strong>.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-[140px,1fr]">
              {/*
                Thumbnail-sized preview keeps the tx detail modal
                compact — full-size view + edit live in the dedicated
                Receipts modal.
              */}
              <div className="flex items-start justify-center overflow-hidden rounded-md border bg-muted/30">
                {receipt.data.has_image && !image.error ? (
                  image.loading || !image.src ? (
                    <div className="grid aspect-[3/4] w-full place-items-center">
                      <Loader2
                        className="size-4 animate-spin text-muted-foreground"
                        aria-label="Loading image"
                      />
                    </div>
                  ) : (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={image.src}
                      alt="Receipt"
                      className="max-h-48 w-full object-contain"
                    />
                  )
                ) : (
                  <div className="grid aspect-[3/4] w-full place-items-center text-xs text-muted-foreground">
                    <ImageOff className="size-5" aria-hidden />
                  </div>
                )}
              </div>
              <div className="min-w-0 space-y-2">
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="text-muted-foreground">Total</span>
                  <span className="font-mono font-medium">
                    {receipt.data.total_cents != null
                      ? formatCents(
                          receipt.data.total_cents,
                          receipt.data.currency,
                        )
                      : "—"}
                  </span>
                </div>
                {receipt.data.tax_cents != null ? (
                  <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
                    <span>Tax</span>
                    <span className="font-mono">
                      {formatCents(
                        receipt.data.tax_cents,
                        receipt.data.currency,
                      )}
                    </span>
                  </div>
                ) : null}
                {receipt.data.lines.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No line items captured.
                  </p>
                ) : (
                  <ul className="max-h-48 space-y-0.5 overflow-y-auto rounded-md border bg-background/50 p-2 text-xs">
                    {receipt.data.lines.map((l) => (
                      <li
                        key={l.id}
                        className="flex items-baseline justify-between gap-2"
                      >
                        <span className="truncate">{l.description}</span>
                        <span className="font-mono text-[11px]">
                          {formatCents(l.total_cents, receipt.data!.currency)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function ReceiptSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-[140px,1fr]">
      <Skeleton className="aspect-[3/4] w-full" />
      <div className="space-y-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-3/4" />
      </div>
    </div>
  );
}
