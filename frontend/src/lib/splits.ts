/**
 * Per-bucket effective-amount helper for split transactions.
 *
 * Reports drill-downs (By Category, By Person → Expenses, By Person →
 * Income) all fetch transactions by the bucket they're focused on. The
 * backend filters correctly via split-aware UNION ALL aggregations, so
 * the BUCKET TOTAL is right — but each row in the drill-down used to
 * render ``tx.amount_cents`` (the parent's full amount), so a $135
 * Travel that was split as $45 yours + $90 Shared showed up as $135
 * under Travel even though only $45 actually counted.
 *
 * This helper picks the right per-row number for display: sum splits
 * that roll up to this bucket, or fall back to the parent amount when
 * the transaction has no splits.
 */
import type { Category, Transaction } from "@/types/v2";

/**
 * Return the amount that ``tx`` actually contributed to the given
 * bucket. Used to label rows in Reports drill-downs.
 *
 * - ``mode = "detailed"``: a split matches only when its
 *   ``category_id`` equals ``bucketCategoryId``.
 * - ``mode = "primary"``: also counts splits whose category's
 *   ``parent_id`` equals ``bucketCategoryId`` (mirrors the COALESCE
 *   parent-rollup rule used by the backend's ``by-category`` SQL).
 *
 * Fallback: returns the parent amount when ``bucketCategoryId`` is
 * null OR when the transaction has no splits, so a half-loaded
 * categories map never blanks out the column.
 */
export function effectiveAmountForBucket(
  tx: Transaction,
  bucketCategoryId: number | null,
  mode: "primary" | "detailed",
  categoryById: Map<number, Category>,
): number {
  const splits = tx.splits ?? [];
  if (splits.length === 0 || bucketCategoryId == null) return tx.amount_cents;
  let total = 0;
  let matched = false;
  for (const s of splits) {
    if (s.category_id == null) continue;
    const matchesDirect = s.category_id === bucketCategoryId;
    const matchesViaParent =
      mode === "primary" &&
      categoryById.get(s.category_id)?.parent_id === bucketCategoryId;
    if (matchesDirect || matchesViaParent) {
      total += s.amount_cents;
      matched = true;
    }
  }
  return matched ? total : tx.amount_cents;
}

/**
 * True when ``effectiveAmountForBucket`` would diverge from the
 * parent's amount — i.e. the transaction has splits and at least one
 * of them lives in another bucket. Use this to gate a "split · $X"
 * chip in the UI so the user knows the displayed amount is their
 * share, not the parent total.
 */
export function hasShareCarveOut(
  tx: Transaction,
  bucketCategoryId: number | null,
  mode: "primary" | "detailed",
  categoryById: Map<number, Category>,
): boolean {
  if ((tx.splits?.length ?? 0) === 0) return false;
  return (
    effectiveAmountForBucket(tx, bucketCategoryId, mode, categoryById) !==
    tx.amount_cents
  );
}
