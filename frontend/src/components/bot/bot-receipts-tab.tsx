"use client";

/**
 * Receipts tab — gallery of OCR'd photos that the user can attach to any
 * existing transaction (or "log as cash" for receipts that Plaid will
 * never see). Receipts arrive unlinked by default; the bot now waits for
 * the user to either run the cash flow or attach to an imported tx.
 *
 * The receipt's image bytes live in Postgres (BYTEA). Images are fetched
 * via the auth-aware ``botApi.fetchReceiptImageBlob`` helper which carries
 * the same Bearer/cookie that every other ``/api/bot/*`` call uses — a
 * naïve ``<img src="…">`` would fail cross-origin on Railway because the
 * session cookie isn't sent and ``<img>`` can't add custom headers.
 *
 * Edit mode (V2.3) lets the user fix anything OCR got wrong — merchant
 * name, date, total, tax, currency, and the line items. Replaces the
 * whole lines array on save (see web/bot_api/repo.py replace_receipt_lines
 * for why "PATCH per line" was rejected).
 *
 * Smart delete/detach: when the receipt is attached to a manual cash
 * transaction we created via "Log as cash", the confirm dialog offers to
 * delete that cash row in the same operation. Prevents the
 * "log as cash → re-attach to Plaid → cash row stuck in wallet → spend
 * double-counted" trap. Plaid-imported transactions are never offered for
 * deletion through this surface — Plaid is the source of truth.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Camera,
  Check,
  CircleDashed,
  ImageOff,
  Link2,
  Link2Off,
  Loader2,
  Pencil,
  Plus,
  Receipt as ReceiptIcon,
  Search,
  Trash2,
  Wallet,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
import { useAuthedReceiptImage } from "@/lib/use-receipt-image";

import { formatCents, formatDate } from "./bot-helpers";

interface DeleteRequest {
  receipt: ReceiptRow;
}

interface DetachRequest {
  receipt: ReceiptRow;
}

export function BotReceiptsTab() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["bot", "receipts"],
    queryFn: () => botApi.listReceipts(40),
  });
  const [openId, setOpenId] = useState<number | null>(null);

  // Smart confirm dialogs sit at the parent level so they survive when
  // the detail modal closes after a successful mutation. Each holds a
  // snapshot of the receipt — we never read mutation.variables to derive
  // labels (that's stale after settle).
  const [deleteRequest, setDeleteRequest] = useState<DeleteRequest | null>(null);
  const [detachRequest, setDetachRequest] = useState<DetachRequest | null>(null);

  const drop = useMutation({
    mutationFn: ({ id, deleteLinkedCash }: { id: number; deleteLinkedCash: boolean }) =>
      botApi.deleteReceipt(id, { deleteLinkedCash }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["bot", "receipts"] });
      // Cash-tx deletion ripples into the transactions list + reports.
      if (vars.deleteLinkedCash) {
        qc.invalidateQueries({ queryKey: ["transactions"] });
        qc.invalidateQueries({ queryKey: ["reports"] });
      }
      setOpenId(null);
      setDeleteRequest(null);
      notify.success(
        vars.deleteLinkedCash
          ? "Receipt and linked cash transaction deleted."
          : "Receipt deleted.",
      );
    },
    onError: onMutationError("Couldn't delete that receipt."),
  });

  const link = useMutation({
    mutationFn: ({ id, txnId }: { id: number; txnId: number | null }) =>
      botApi.linkReceipt(id, txnId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "receipts"] });
      qc.invalidateQueries({ queryKey: ["bot", "receipt"] });
      qc.invalidateQueries({ queryKey: ["transaction"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
      notify.success("Receipt linked.");
    },
    onError: onMutationError("Couldn't link the receipt."),
  });

  const unlink = useMutation({
    mutationFn: ({
      id,
      deleteLinkedCash,
    }: {
      id: number;
      deleteLinkedCash: boolean;
    }) => botApi.linkReceipt(id, null, { deleteLinkedCash }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["bot", "receipts"] });
      qc.invalidateQueries({ queryKey: ["bot", "receipt"] });
      qc.invalidateQueries({ queryKey: ["transaction"] });
      if (vars.deleteLinkedCash) {
        qc.invalidateQueries({ queryKey: ["transactions"] });
        qc.invalidateQueries({ queryKey: ["reports"] });
      }
      setDetachRequest(null);
      notify.success(
        vars.deleteLinkedCash
          ? "Receipt detached and cash transaction deleted."
          : "Receipt detached.",
      );
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

  // Delete entry-point — receipt is the in-memory snapshot from the
  // detail modal so we know whether linked_is_manual_cash is true and
  // can render the smart confirm with the cash-tx amount inline.
  const requestDelete = (receipt: ReceiptRow) => {
    if (receipt.linked_is_manual_cash) {
      setDeleteRequest({ receipt });
      return;
    }
    // Non-cash linked or fully unlinked → normal one-shot confirm.
    void (async () => {
      const ok = await confirm({
        title: "Delete receipt?",
        description: receipt.merchant_name
          ? `${receipt.merchant_name} — only the photo + parsed lines are removed.`
          : "Only the photo + parsed lines are removed.",
        destructive: true,
        confirmLabel: "Delete",
      });
      if (ok) drop.mutate({ id: receipt.id, deleteLinkedCash: false });
    })();
  };

  const requestDetach = (receipt: ReceiptRow) => {
    if (receipt.linked_is_manual_cash) {
      setDetachRequest({ receipt });
      return;
    }
    // Plaid-imported tx — just detach. The Plaid row stays untouched.
    unlink.mutate({ id: receipt.id, deleteLinkedCash: false });
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Send a photo of any receipt to the Telegram bot — it gets parsed via
        OCR and saved as a cash transaction. Receipts are shared
        household-wide; each card carries an <em>@username</em> tag so you
        can spot who uploaded it. Tap a row to see the photo and line items.
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
                  <div className="flex items-center gap-1.5 font-medium">
                    {r.merchant_name || "Receipt"}
                    {r.created_by_username ? (
                      <Badge
                        variant="outline"
                        className="text-[10px] font-normal text-muted-foreground"
                      >
                        @{r.created_by_username}
                      </Badge>
                    ) : null}
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
        onDelete={requestDelete}
        onDetach={requestDetach}
        onLogAsCash={() => openId && logAsCash.mutate(openId)}
        onAttachClick={() => openId && setPickerForId(openId)}
        deleting={drop.isPending || deleteRequest != null}
        unlinking={unlink.isPending || detachRequest != null}
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

      <DeleteReceiptDialog
        request={deleteRequest}
        onCancel={() => setDeleteRequest(null)}
        onConfirm={(deleteLinkedCash) =>
          deleteRequest &&
          drop.mutate({ id: deleteRequest.receipt.id, deleteLinkedCash })
        }
        pending={drop.isPending}
      />

      <DetachReceiptDialog
        request={detachRequest}
        onCancel={() => setDetachRequest(null)}
        onConfirm={(deleteLinkedCash) =>
          detachRequest &&
          unlink.mutate({ id: detachRequest.receipt.id, deleteLinkedCash })
        }
        pending={unlink.isPending}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Smart confirm dialogs — used when the receipt is attached to a manual
// cash transaction we created via "Log as cash". Both follow the same
// shape: a checkbox lets the user co-delete the orphan cash row in the
// same operation, defaulted ON because that's almost always what they
// want (avoiding the double-counting trap).
// ---------------------------------------------------------------------------

function DeleteReceiptDialog({
  request,
  onCancel,
  onConfirm,
  pending,
}: {
  request: DeleteRequest | null;
  onCancel: () => void;
  onConfirm: (deleteLinkedCash: boolean) => void;
  pending: boolean;
}) {
  const [alsoDelete, setAlsoDelete] = useState(true);
  // Reset the toggle each time a new dialog opens so the user's previous
  // choice doesn't sneakily carry over to a different receipt.
  useEffect(() => {
    if (request) setAlsoDelete(true);
  }, [request]);

  if (!request) return null;
  const r = request.receipt;
  const amount = r.total_cents != null ? formatCents(r.total_cents) : "the cash";

  return (
    <Dialog open onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Delete receipt?</DialogTitle>
          <DialogDescription>
            {r.merchant_name
              ? `${r.merchant_name} — the photo and parsed lines will be removed.`
              : "The photo and parsed lines will be removed."}
          </DialogDescription>
        </DialogHeader>
        <label className="flex items-start gap-2.5 rounded-md border bg-muted/30 p-3 text-sm">
          <Switch
            checked={alsoDelete}
            onCheckedChange={setAlsoDelete}
            aria-label="Also delete the linked cash transaction"
            className="mt-0.5"
          />
          <span className="flex flex-col gap-0.5">
            <span className="font-medium">
              Also delete the linked {amount} cash transaction
            </span>
            <span className="text-xs text-muted-foreground">
              You logged this receipt as cash — leaving it standing would
              keep the spend in your wallet without any photo to back it up.
            </span>
          </span>
        </label>
        <DialogFooter className="gap-2 sm:gap-2">
          <Button variant="outline" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => onConfirm(alsoDelete)}
            disabled={pending}
          >
            {pending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="mr-1 h-4 w-4" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DetachReceiptDialog({
  request,
  onCancel,
  onConfirm,
  pending,
}: {
  request: DetachRequest | null;
  onCancel: () => void;
  onConfirm: (deleteLinkedCash: boolean) => void;
  pending: boolean;
}) {
  const [alsoDelete, setAlsoDelete] = useState(true);
  useEffect(() => {
    if (request) setAlsoDelete(true);
  }, [request]);

  if (!request) return null;
  const r = request.receipt;
  const amount = r.total_cents != null ? formatCents(r.total_cents) : "the cash";

  return (
    <Dialog open onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Detach receipt?</DialogTitle>
          <DialogDescription>
            The receipt becomes unlinked. You can re-attach it to any
            transaction later.
          </DialogDescription>
        </DialogHeader>
        <label className="flex items-start gap-2.5 rounded-md border bg-muted/30 p-3 text-sm">
          <Switch
            checked={alsoDelete}
            onCheckedChange={setAlsoDelete}
            aria-label="Also delete the linked cash transaction"
            className="mt-0.5"
          />
          <span className="flex flex-col gap-0.5">
            <span className="font-medium">
              Also delete the linked {amount} cash transaction
            </span>
            <span className="text-xs text-muted-foreground">
              Re-attaching this receipt to a real bank transaction without
              removing the cash row would count the same spend twice.
            </span>
          </span>
        </label>
        <DialogFooter className="gap-2 sm:gap-2">
          <Button variant="outline" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button onClick={() => onConfirm(alsoDelete)} disabled={pending}>
            {pending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Link2Off className="mr-1 h-4 w-4" />
            )}
            Detach
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Edit-mode form state. We model lines as plain objects with a stable
// ``localKey`` so React keys stay sensible even after add/remove (DB id
// would be undefined for newly-added rows).
// ---------------------------------------------------------------------------

interface EditLineDraft {
  localKey: string;
  description: string;
  quantity: string;
  unit_price: string;
  total: string;
}

interface EditFormState {
  merchant_name: string;
  receipt_date: string;
  total: string;
  tax: string;
  currency: string;
  lines: EditLineDraft[];
}

function buildInitialEditForm(r: ReceiptRow): EditFormState {
  return {
    merchant_name: r.merchant_name ?? "",
    receipt_date: r.receipt_date ?? "",
    total: r.total_cents != null ? (r.total_cents / 100).toFixed(2) : "",
    tax: r.tax_cents != null ? (r.tax_cents / 100).toFixed(2) : "",
    currency: r.currency || "USD",
    lines: r.lines.map((l, i) => ({
      localKey: `db-${l.id}-${i}`,
      description: l.description,
      quantity: l.quantity != null ? String(l.quantity) : "",
      unit_price:
        l.unit_price_cents != null
          ? (l.unit_price_cents / 100).toFixed(2)
          : "",
      total: (l.total_cents / 100).toFixed(2),
    })),
  };
}

// Centralise the dollars→cents parse so empty / garbage input becomes
// ``null`` predictably (the API treats missing fields as "no change",
// so we only send keys the user actually touched).
function parseDollars(value: string): number | null {
  const trimmed = value.replace(/[$,\s]/g, "");
  if (!trimmed) return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n)) return null;
  return Math.round(n * 100);
}

function parseQuantity(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0) return null;
  return n;
}

function ReceiptDetail({
  id,
  onClose,
  onDelete,
  onDetach,
  onLogAsCash,
  onAttachClick,
  deleting,
  unlinking,
  loggingCash,
}: {
  id: number | null;
  onClose: () => void;
  onDelete: (receipt: ReceiptRow) => void;
  onDetach: (receipt: ReceiptRow) => void;
  onLogAsCash: () => void;
  onAttachClick: () => void;
  deleting: boolean;
  unlinking: boolean;
  loggingCash: boolean;
}) {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["bot", "receipt", id],
    queryFn: () => (id ? botApi.getReceipt(id) : Promise.resolve(null)),
    enabled: id != null,
  });
  const r: ReceiptRow | null = detail.data ?? null;
  const open = id != null;
  const image = useAuthedReceiptImage(id, !!r?.has_image);

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EditFormState | null>(null);

  // Reset edit state whenever the open receipt changes — closing one
  // modal and immediately opening another should never leak the old
  // draft across rows.
  useEffect(() => {
    setEditing(false);
    setForm(null);
  }, [id]);

  const startEdit = () => {
    if (!r) return;
    setForm(buildInitialEditForm(r));
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setForm(null);
  };

  const saveHeader = useMutation({
    mutationFn: (patch: Parameters<typeof botApi.updateReceipt>[1]) =>
      botApi.updateReceipt(id!, patch),
    onError: onMutationError("Couldn't save those changes."),
  });

  const saveLines = useMutation({
    mutationFn: (lines: Parameters<typeof botApi.replaceReceiptLines>[1]) =>
      botApi.replaceReceiptLines(id!, lines),
    onError: onMutationError("Couldn't save the line items."),
  });

  // Composite save — header first, then lines, then a single toast.
  // Sequencing on the FE keeps the API simple (no bulk endpoint needed)
  // and lets us roll back the dialog state only when both succeeded.
  const submitEdit = async () => {
    if (!form || !id || !r) return;

    const headerPatch: Parameters<typeof botApi.updateReceipt>[1] = {};
    const merchant = form.merchant_name.trim();
    if (merchant !== (r.merchant_name ?? "")) {
      headerPatch.merchant_name = merchant || null;
    }
    if (form.receipt_date && form.receipt_date !== (r.receipt_date ?? "")) {
      headerPatch.receipt_date = form.receipt_date;
    }
    const totalCents = parseDollars(form.total);
    if (totalCents != null && totalCents !== r.total_cents) {
      headerPatch.total_cents = totalCents;
    }
    const taxCents = parseDollars(form.tax);
    if (taxCents !== (r.tax_cents ?? null) && form.tax.trim() !== "") {
      headerPatch.tax_cents = taxCents ?? undefined;
    }
    const currency = form.currency.trim().toUpperCase().slice(0, 3);
    if (currency && currency !== r.currency) {
      headerPatch.currency = currency;
    }

    // Lines are always shipped as a full replacement when the user opens
    // edit mode — the diff isn't worth it for short lists, and the
    // backend's PUT endpoint expects the canonical array anyway.
    const linesPayload = form.lines
      .map((line) => {
        const desc = line.description.trim();
        const totalCentsLine = parseDollars(line.total);
        if (!desc || totalCentsLine == null) return null;
        return {
          description: desc,
          quantity: parseQuantity(line.quantity),
          unit_price_cents: parseDollars(line.unit_price),
          total_cents: totalCentsLine,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);

    if (Object.keys(headerPatch).length > 0) {
      await saveHeader.mutateAsync(headerPatch);
    }
    // Detect whether lines actually changed — avoids a noop write that
    // bumps timestamps for nothing.
    const linesChanged = (() => {
      if (linesPayload.length !== r.lines.length) return true;
      for (let i = 0; i < linesPayload.length; i++) {
        const a = linesPayload[i];
        const b = r.lines[i];
        if (a.description !== b.description) return true;
        if (a.total_cents !== b.total_cents) return true;
        if ((a.quantity ?? null) !== (b.quantity ?? null)) return true;
        if ((a.unit_price_cents ?? null) !== (b.unit_price_cents ?? null))
          return true;
      }
      return false;
    })();
    if (linesChanged) {
      await saveLines.mutateAsync(linesPayload);
    }

    qc.invalidateQueries({ queryKey: ["bot", "receipt", id] });
    qc.invalidateQueries({ queryKey: ["bot", "receipts"] });
    qc.invalidateQueries({ queryKey: ["transaction"] });
    notify.success("Receipt updated.");
    setEditing(false);
    setForm(null);
  };

  const isSaving = saveHeader.isPending || saveLines.isPending;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      {/*
        max-h + flex column: body scrolls, header + footer pinned. Without
        this a tall portrait receipt would push the action footer (and
        therefore Delete) below the viewport.
      */}
      <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 p-0">
        <DialogHeader className="flex-row items-center justify-between gap-3 border-b px-5 py-3">
          <DialogTitle className="flex min-w-0 items-center gap-2 truncate">
            <ReceiptIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="truncate">{r?.merchant_name || "Receipt"}</span>
          </DialogTitle>
          {/*
            Edit / Cancel sits next to the title. mr-6 keeps it clear of
            Radix's built-in close button (top-right). Delete moved to the
            footer where it can't be mis-tapped on the way to closing.
          */}
          {r ? (
            editing ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={cancelEdit}
                disabled={isSaving}
                className="mr-6 shrink-0"
              >
                <X className="mr-1 h-4 w-4" />
                Cancel
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={startEdit}
                className="mr-6 shrink-0"
              >
                <Pencil className="mr-1 h-4 w-4" />
                Edit
              </Button>
            )
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
              {editing && form ? (
                <ReceiptEditPanel
                  form={form}
                  setForm={setForm}
                  saving={isSaving}
                />
              ) : (
                <ReceiptViewPanel receipt={r} />
              )}
            </div>
          </div>
        )}

        {r ? (
          <div className="flex flex-col gap-2 border-t bg-muted/20 px-5 py-3 text-sm">
            {editing ? (
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={cancelEdit}
                  disabled={isSaving}
                >
                  Cancel
                </Button>
                <Button onClick={submitEdit} disabled={isSaving}>
                  {isSaving ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="mr-1 h-4 w-4" />
                  )}
                  Save changes
                </Button>
              </div>
            ) : (
              <>
                {/* Link / detach / log-as-cash row */}
                {r.transaction_id ? (
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Link2 className="h-3.5 w-3.5 text-emerald-500" />
                      <span>
                        Linked to transaction #{r.transaction_id}
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onDetach(r)}
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
                {/*
                  Delete in its own row, far from the Radix close button
                  in the header — earlier feedback called the previous
                  placement "dangerously close" to dismiss.
                */}
                <div className="flex justify-end border-t pt-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onDelete(r)}
                    disabled={deleting}
                    className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                  >
                    {deleting ? (
                      <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="mr-1 h-4 w-4" />
                    )}
                    Delete receipt
                  </Button>
                </div>
              </>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ReceiptViewPanel({ receipt }: { receipt: ReceiptRow }) {
  return (
    <>
      <dl className="grid grid-cols-2 gap-y-1.5 text-sm">
        <dt className="text-muted-foreground">Total</dt>
        <dd className="text-right font-mono font-medium">
          {receipt.total_cents != null
            ? formatCents(receipt.total_cents)
            : "—"}
        </dd>
        {receipt.tax_cents != null ? (
          <>
            <dt className="text-muted-foreground">Tax</dt>
            <dd className="text-right font-mono">
              {formatCents(receipt.tax_cents)}
            </dd>
          </>
        ) : null}
        <dt className="text-muted-foreground">Date</dt>
        <dd className="text-right">{formatDate(receipt.receipt_date)}</dd>
        <dt className="text-muted-foreground">Currency</dt>
        <dd className="text-right font-mono text-xs">{receipt.currency}</dd>
      </dl>
      <div>
        <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Lines
        </h3>
        {receipt.lines.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No line items captured.
          </p>
        ) : (
          <ul className="space-y-1 rounded-md border bg-muted/20 p-2 text-sm">
            {receipt.lines.map((l) => (
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
    </>
  );
}

function ReceiptEditPanel({
  form,
  setForm,
  saving,
}: {
  form: EditFormState;
  setForm: (next: EditFormState | null | ((prev: EditFormState | null) => EditFormState | null)) => void;
  saving: boolean;
}) {
  const updateLine = (idx: number, patch: Partial<EditLineDraft>) =>
    setForm((prev) =>
      prev
        ? {
            ...prev,
            lines: prev.lines.map((l, i) => (i === idx ? { ...l, ...patch } : l)),
          }
        : prev,
    );
  const removeLine = (idx: number) =>
    setForm((prev) =>
      prev ? { ...prev, lines: prev.lines.filter((_, i) => i !== idx) } : prev,
    );
  const addLine = () =>
    setForm((prev) =>
      prev
        ? {
            ...prev,
            lines: [
              ...prev.lines,
              {
                localKey: `new-${Date.now()}-${prev.lines.length}`,
                description: "",
                quantity: "",
                unit_price: "",
                total: "",
              },
            ],
          }
        : prev,
    );

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="col-span-2 grid gap-1">
          <Label htmlFor="r-merchant" className="text-xs">
            Merchant
          </Label>
          <Input
            id="r-merchant"
            value={form.merchant_name}
            disabled={saving}
            onChange={(e) =>
              setForm((p) => (p ? { ...p, merchant_name: e.target.value } : p))
            }
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="r-date" className="text-xs">
            Date
          </Label>
          <Input
            id="r-date"
            type="date"
            value={form.receipt_date}
            disabled={saving}
            onChange={(e) =>
              setForm((p) => (p ? { ...p, receipt_date: e.target.value } : p))
            }
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="r-currency" className="text-xs">
            Currency
          </Label>
          <Input
            id="r-currency"
            value={form.currency}
            maxLength={3}
            disabled={saving}
            onChange={(e) =>
              setForm((p) =>
                p ? { ...p, currency: e.target.value.toUpperCase() } : p,
              )
            }
            className="font-mono uppercase"
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="r-total" className="text-xs">
            Total
          </Label>
          <Input
            id="r-total"
            inputMode="decimal"
            value={form.total}
            disabled={saving}
            onChange={(e) =>
              setForm((p) => (p ? { ...p, total: e.target.value } : p))
            }
            className="text-right font-mono"
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="r-tax" className="text-xs">
            Tax
          </Label>
          <Input
            id="r-tax"
            inputMode="decimal"
            value={form.tax}
            disabled={saving}
            onChange={(e) =>
              setForm((p) => (p ? { ...p, tax: e.target.value } : p))
            }
            className="text-right font-mono"
          />
        </div>
      </div>
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Lines
          </h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={addLine}
            disabled={saving}
            className="h-7 px-2 text-xs"
          >
            <Plus className="mr-1 h-3.5 w-3.5" />
            Add line
          </Button>
        </div>
        {form.lines.length === 0 ? (
          <p className="rounded-md border border-dashed py-4 text-center text-xs text-muted-foreground">
            No line items. Add one to itemise the receipt.
          </p>
        ) : (
          <ul className="space-y-2 rounded-md border bg-muted/20 p-2">
            {form.lines.map((l, idx) => (
              <li
                key={l.localKey}
                className="grid grid-cols-[1fr,80px,40px] items-center gap-1.5 text-sm"
              >
                <Input
                  value={l.description}
                  placeholder="Description"
                  disabled={saving}
                  onChange={(e) =>
                    updateLine(idx, { description: e.target.value })
                  }
                  className="h-8 text-sm"
                />
                <Input
                  value={l.total}
                  placeholder="0.00"
                  inputMode="decimal"
                  disabled={saving}
                  onChange={(e) => updateLine(idx, { total: e.target.value })}
                  className="h-8 text-right font-mono text-xs"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => removeLine(idx)}
                  disabled={saving}
                  className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  title="Remove line"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  <span className="sr-only">Remove</span>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
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
