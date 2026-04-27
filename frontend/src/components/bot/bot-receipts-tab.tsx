"use client";

/**
 * Receipts tab — gallery of OCR'd photos linked to cash transactions.
 *
 * The receipt's image bytes live in Postgres (BYTEA). The frontend just
 * issues a GET /api/bot/receipts/:id/image which authenticates against
 * the session cookie before streaming the bytes back. If the image fails
 * to load (404, network) we surface a placeholder rather than an empty
 * frame so the user can still see the line items + totals.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Camera,
  ImageOff,
  Loader2,
  Receipt as ReceiptIcon,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { botApi, type ReceiptRow } from "@/lib/api";
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
        deleting={drop.isPending}
      />
    </div>
  );
}

function ReceiptDetail({
  id,
  onClose,
  onDelete,
  deleting,
}: {
  id: number | null;
  onClose: () => void;
  onDelete: (name: string | null | undefined) => void;
  deleting: boolean;
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
