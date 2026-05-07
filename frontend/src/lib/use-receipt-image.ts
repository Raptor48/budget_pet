"use client";

/**
 * Auth-aware receipt-image fetcher.
 *
 * The naive ``<img src="/api/bot/receipts/:id/image">`` works only when
 * the frontend and backend share an origin. Once they don't (Railway
 * production has them on different hosts), the session cookie isn't sent
 * and the Bearer-token fallback in :func:`apiRequest` can't ride along
 * on an ``<img>`` tag — there's no way to attach custom headers to it.
 *
 * This hook fetches the bytes through the regular auth path and exposes
 * a blob URL the caller can drop into ``<img src>``. The blob is freed
 * on unmount or when the receipt id changes so a few hundred kilobytes
 * don't pile up per receipt the user previewed.
 *
 * Used by both the receipts gallery (Bot → Receipts modal) and the
 * transaction detail modal (Transactions page → expanded receipt
 * breakdown). Keeping the hook here means a single owner of the blob
 * lifecycle — duplicating it in two components would risk leaks if one
 * forgot to revoke.
 */
import { useEffect, useState } from "react";

import { botApi } from "@/lib/api";

export function useAuthedReceiptImage(
  receiptId: number | null,
  hasImage: boolean,
) {
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
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [receiptId, hasImage]);

  return { src, error, loading };
}
