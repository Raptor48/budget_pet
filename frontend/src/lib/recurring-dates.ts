/**
 * Utilities for recurring-stream payment dates.
 *
 * Mirrors the backend `next_occurrence` logic in `web/reports/calculations.py`
 * so the UI can show "Next payment" without a round-trip. The server is the
 * authoritative source for forecast math; this module is a display-only
 * convenience that intentionally covers the same frequencies.
 */

import { addDays, addMonths, addYears, format } from "date-fns";

import { safeParseDate } from "@/lib/date-utils";

/**
 * Plaid recurring frequencies we understand. `UNKNOWN` and anything else
 * returns `null` so callers can fall back to showing just the last payment.
 */
const FREQUENCY_DELTA_DAYS: Record<string, number> = {
  WEEKLY: 7,
  BIWEEKLY: 14,
};

export function nextRecurringDate(
  lastDate: string | null | undefined,
  frequency: string | null | undefined,
): Date | null {
  if (!lastDate || !frequency) return null;
  const base = safeParseDate(lastDate);
  if (!base || Number.isNaN(base.getTime())) return null;

  const freq = frequency.toUpperCase();
  if (freq === "MONTHLY") return addMonths(base, 1);
  if (freq === "SEMI_MONTHLY") return addDays(base, 15);
  if (freq === "ANNUALLY") return addYears(base, 1);

  const days = FREQUENCY_DELTA_DAYS[freq];
  if (days) return addDays(base, days);

  return null;
}

/**
 * Format a recurring date for the table/card. Returns "—" for missing or
 * unparseable values so the UI never shows a blank cell.
 */
export function formatRecurringDate(
  date: string | null | undefined,
  formatString: string = "MMM d",
): string {
  if (!date) return "—";
  const parsed = safeParseDate(date);
  if (!parsed || Number.isNaN(parsed.getTime())) return "—";
  return format(parsed, formatString);
}

export function formatNextRecurringDate(
  lastDate: string | null | undefined,
  frequency: string | null | undefined,
  formatString: string = "MMM d",
): string {
  const next = nextRecurringDate(lastDate, frequency);
  if (!next) return "—";
  return format(next, formatString);
}
