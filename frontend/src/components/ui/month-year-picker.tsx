"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTransactionsDateRange } from "@/lib/hooks/use-transactions-date-range";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

interface MonthBound {
  year: number;
  month: number;
}

function parseMonth(value: string | null | undefined): MonthBound | null {
  if (!value) return null;
  const match = value.match(/^(\d{4})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (!Number.isFinite(year) || month < 1 || month > 12) return null;
  return { year, month };
}

function currentBound(): MonthBound {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() + 1 };
}

/**
 * Shared month/year selector used on every page with a per-month view.
 *
 * Bounds come from the `useTransactionsDateRange` hook so all pickers in the
 * app show the same range: oldest available transaction → newest. Months
 * outside the range on boundary years are disabled (not hidden) to keep the
 * layout stable and the available data obvious.
 *
 * Callers can still pass explicit `minMonth` / `maxMonth` (YYYY-MM) to force
 * a range — useful for forecasts or report pages that need wider bounds than
 * the raw transaction history.
 */
export function MonthYearPicker({
  value,
  onChange,
  minMonth,
  maxMonth,
}: {
  value: string;
  onChange: (v: string) => void;
  minMonth?: string;
  maxMonth?: string;
}) {
  const { data: range, isLoading } = useTransactionsDateRange();

  const current = currentBound();
  const selected = parseMonth(value) ?? current;

  const minBound =
    parseMonth(minMonth) ??
    parseMonth(range?.min_month) ??
    { year: current.year, month: 1 };
  const maxBoundRaw =
    parseMonth(maxMonth) ??
    parseMonth(range?.max_month) ??
    current;
  // Ensure min never exceeds max (guard against unexpected data).
  const maxBound =
    compareBounds(maxBoundRaw, minBound) < 0 ? { ...minBound } : maxBoundRaw;

  const years: number[] = [];
  for (let y = minBound.year; y <= maxBound.year; y += 1) {
    years.push(y);
  }
  if (years.length === 0) {
    years.push(current.year);
  }

  const isMonthDisabled = (year: number, month: number): boolean => {
    if (year === minBound.year && month < minBound.month) return true;
    if (year === maxBound.year && month > maxBound.month) return true;
    return false;
  };

  const handleMonthChange = (m: string) => {
    onChange(`${selected.year}-${String(m).padStart(2, "0")}`);
  };

  const handleYearChange = (y: string) => {
    const newYear = Number(y);
    // When switching years, clamp the month into the new year's allowed range.
    let newMonth = selected.month;
    if (newYear === minBound.year && newMonth < minBound.month) {
      newMonth = minBound.month;
    }
    if (newYear === maxBound.year && newMonth > maxBound.month) {
      newMonth = maxBound.month;
    }
    onChange(`${newYear}-${String(newMonth).padStart(2, "0")}`);
  };

  return (
    <div className="flex gap-2" aria-busy={isLoading}>
      <Select value={String(selected.month)} onValueChange={handleMonthChange}>
        <SelectTrigger className="w-[130px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {MONTH_NAMES.map((name, i) => {
            const monthNum = i + 1;
            return (
              <SelectItem
                key={monthNum}
                value={String(monthNum)}
                disabled={isMonthDisabled(selected.year, monthNum)}
              >
                {name}
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>
      <Select value={String(selected.year)} onValueChange={handleYearChange}>
        <SelectTrigger className="w-[90px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {years.map((y) => (
            <SelectItem key={y} value={String(y)}>
              {y}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function compareBounds(a: MonthBound, b: MonthBound): number {
  if (a.year !== b.year) return a.year - b.year;
  return a.month - b.month;
}
