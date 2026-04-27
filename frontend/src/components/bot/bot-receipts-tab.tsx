"use client";

/**
 * Receipts tab — gallery of OCR'd photos linked to cash transactions.
 *
 * The receipt's image bytes live in Postgres (BYTEA). The frontend just
 * issues a GET /api/bot/receipts/:id/image which authenticates against
 * the session cookie before streaming the bytes back.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { botApi, type ReceiptRow } from "@/lib/api";

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
    },
  });

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Send a photo of any receipt to the Telegram bot — it gets parsed via
        OCR and saved as a cash transaction. Tap a row to see the photo and
        line items.
      </p>

      {list.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !list.data?.length ? (
        <p className="text-sm text-muted-foreground">
          No receipts yet. Send one in Telegram to get started.
        </p>
      ) : (
        <ul className="divide-y rounded-md border">
          {list.data.map((r) => (
            <li
              key={r.id}
              role="button"
              tabIndex={0}
              onClick={() => setOpenId(r.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") setOpenId(r.id);
              }}
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-muted/40 cursor-pointer"
            >
              <div className="min-w-0">
                <div className="font-medium">
                  {r.merchant_name || "Receipt"}
                </div>
                <div className="text-xs text-muted-foreground">
                  {formatDate(r.receipt_date)} · captured{" "}
                  {formatDate(r.created_at)}
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs">
                {r.parse_status !== "parsed" ? (
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
        onDelete={() => openId && drop.mutate(openId)}
      />
    </div>
  );
}

function ReceiptDetail({
  id,
  onClose,
  onDelete,
}: {
  id: number | null;
  onClose: () => void;
  onDelete: () => void;
}) {
  const detail = useQuery({
    queryKey: ["bot", "receipt", id],
    queryFn: () => (id ? botApi.getReceipt(id) : Promise.resolve(null)),
    enabled: id != null,
  });
  const r: ReceiptRow | null = detail.data ?? null;
  const open = id != null;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{r?.merchant_name || "Receipt"}</DialogTitle>
        </DialogHeader>
        {!r ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-[1fr,1fr]">
            <div>
              {r.has_image && id ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={botApi.receiptImageUrl(id)}
                  alt="Receipt"
                  className="w-full rounded-md border"
                />
              ) : (
                <p className="text-sm text-muted-foreground">No image stored.</p>
              )}
            </div>
            <div className="space-y-3">
              <div className="text-sm">
                <div>
                  <span className="text-muted-foreground">Total</span>{" "}
                  <span className="font-mono">
                    {r.total_cents != null ? formatCents(r.total_cents) : "—"}
                  </span>
                </div>
                {r.tax_cents != null ? (
                  <div>
                    <span className="text-muted-foreground">Tax</span>{" "}
                    <span className="font-mono">{formatCents(r.tax_cents)}</span>
                  </div>
                ) : null}
                <div>
                  <span className="text-muted-foreground">Date</span>{" "}
                  {formatDate(r.receipt_date)}
                </div>
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Lines
                </h3>
                {r.lines.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No line items captured.
                  </p>
                ) : (
                  <ul className="space-y-1 text-sm">
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
              <div className="flex justify-end">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onDelete}
                >
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
