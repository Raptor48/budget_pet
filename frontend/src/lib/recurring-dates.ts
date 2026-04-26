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

/**
 * Project a stream's recurrence into a window `[start, end]`. Returns every
 * date the stream is *expected* to charge inside the window, derived from
 * `last_date` advanced by the cadence delta. Useful for the calendar view.
 *
 * Past stride: we may need to advance from a `last_date` that's months
 * before `start`, so we step forward without bound until we cross `end`.
 * The total step count is at most `(end - last_date) / minStride` with a
 * generous safety cap to avoid pathological loops on bad data.
 */
export function recurringOccurrencesInRange(
  lastDate: string | null | undefined,
  frequency: string | null | undefined,
  start: Date,
  end: Date,
): Date[] {
  if (!lastDate || !frequency) return [];
  const base = safeParseDate(lastDate);
  if (!base || Number.isNaN(base.getTime())) return [];
  const freq = frequency.toUpperCase();

  // Per-step advance helper. SEMI_MONTHLY in the backend is documented as
  // "approx every 15 days" — we mirror that here so calendar projections
  // never disagree with `formatNextRecurringDate`.
  const advance = (d: Date): Date | null => {
    if (freq === "MONTHLY") return addMonths(d, 1);
    if (freq === "SEMI_MONTHLY") return addDays(d, 15);
    if (freq === "ANNUALLY") return addYears(d, 1);
    const delta = FREQUENCY_DELTA_DAYS[freq];
    if (delta) return addDays(d, delta);
    return null;
  };

  const out: Date[] = [];
  let cursor: Date | null = base;
  let steps = 0;
  // Hard cap: even WEEKLY over a 10-year window is < 600 steps. 5000
  // covers any reasonable case while preventing an infinite loop on bad
  // data (e.g. ANNUALLY with last_date 100 years ago + 5000-year window).
  const HARD_CAP = 5000;

  // Past `last_date` itself counts only when it falls in the window.
  while (cursor && cursor.getTime() <= end.getTime() && steps < HARD_CAP) {
    if (cursor.getTime() >= start.getTime()) {
      out.push(cursor);
    }
    const next = advance(cursor);
    if (!next || next.getTime() <= cursor.getTime()) break;
    cursor = next;
    steps += 1;
  }
  return out;
}
