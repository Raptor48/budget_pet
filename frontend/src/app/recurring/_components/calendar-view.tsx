"use client";

import { useMemo, useState } from "react";
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  startOfMonth,
  startOfWeek,
  subMonths,
} from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { formatMoney } from "@/components/accounts/helpers";
import { recurringOccurrencesInRange } from "@/lib/recurring-dates";
import { cn } from "@/lib/utils";
import type { RecurringStream } from "@/types/v2";

import {
  StreamAvatar,
  effectiveUserStatus,
  streamTitle,
} from "./recurring-helpers";

type Occurrence = { date: Date; stream: RecurringStream };

export function CalendarView({
  rows,
  onJumpToRow,
}: {
  rows: RecurringStream[];
  /** Switch the parent into List view + scroll to a row. */
  onJumpToRow: (id: number) => void;
}) {
  const [cursor, setCursor] = useState<Date>(() => startOfMonth(new Date()));

  const monthStart = startOfMonth(cursor);
  const monthEnd = endOfMonth(cursor);
  // Week-aligned grid (always 6 rows × 7 cols = 42 cells, dependable layout).
  const gridStart = startOfWeek(monthStart, { weekStartsOn: 0 });
  const gridEnd = endOfWeek(monthEnd, { weekStartsOn: 0 });

  // Project every active stream into the grid window. Cancelled rows pass
  // through (visible in the calendar with a muted style) so the user can
  // still verify *why* the bill is gone, but they don't add to month totals.
  const occurrences = useMemo<Occurrence[]>(() => {
    const out: Occurrence[] = [];
    for (const stream of rows) {
      const dates = recurringOccurrencesInRange(
        stream.last_date,
        stream.frequency,
        gridStart,
        gridEnd,
      );
      for (const d of dates) out.push({ date: d, stream });
    }
    return out;
  }, [rows, gridStart, gridEnd]);

  const occurrencesByDay = useMemo(() => {
    const map = new Map<string, Occurrence[]>();
    for (const occ of occurrences) {
      const key = format(occ.date, "yyyy-MM-dd");
      const list = map.get(key) ?? [];
      list.push(occ);
      map.set(key, list);
    }
    return map;
  }, [occurrences]);

  const monthTotalCents = useMemo(() => {
    let total = 0;
    for (const occ of occurrences) {
      if (!isSameMonth(occ.date, cursor)) continue;
      if (effectiveUserStatus(occ.stream) !== "active") continue;
      // last_amount preferred over avg — calendar = "what will hit", not
      // "what's typical". For inflows Plaid stores negative cents; we sum
      // absolute so the displayed total is always positive currency.
      const cents = Math.abs(
        occ.stream.last_amount_cents ?? occ.stream.average_amount_cents ?? 0,
      );
      total += cents;
    }
    return total;
  }, [occurrences, cursor]);

  // `eachDayOfInterval` is DST-safe; manual `+ 86_400_000` is not (the
  // March / November transitions in US zones produce 23/25-hour days).
  const days = eachDayOfInterval({ start: gridStart, end: gridEnd });

  const weekHeaders = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const today = new Date();

  return (
    <Card className="border-border/70">
      <CardContent className="flex flex-col gap-3 p-4">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-8"
              aria-label="Previous month"
              onClick={() => setCursor((c) => subMonths(c, 1))}
            >
              <ChevronLeft className="size-4" />
            </Button>
            <div className="text-base font-semibold tracking-tight">
              {format(cursor, "MMMM yyyy")}
            </div>
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-8"
              aria-label="Next month"
              onClick={() => setCursor((c) => addMonths(c, 1))}
            >
              <ChevronRight className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8"
              onClick={() => setCursor(startOfMonth(new Date()))}
            >
              Today
            </Button>
          </div>
          <div className="text-muted-foreground text-xs">
            {format(cursor, "MMM")} expected total{" "}
            <span className="text-foreground tabular-nums font-medium">
              {formatMoney(monthTotalCents)}
            </span>
          </div>
        </div>

        {/* Week header row */}
        <div className="grid grid-cols-7 gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          {weekHeaders.map((d) => (
            <div key={d} className="px-2 py-1">
              {d}
            </div>
          ))}
        </div>

        {/* Day grid */}
        <div className="grid grid-cols-7 gap-1">
          {days.map((day) => {
            const key = format(day, "yyyy-MM-dd");
            const dayOccs = occurrencesByDay.get(key) ?? [];
            const inMonth = isSameMonth(day, cursor);
            const isToday = isSameDay(day, today);
            const dayTotalCents = dayOccs.reduce(
              (acc, o) =>
                effectiveUserStatus(o.stream) === "active"
                  ? acc +
                    Math.abs(
                      o.stream.last_amount_cents ?? o.stream.average_amount_cents ?? 0,
                    )
                  : acc,
              0,
            );
            return (
              <DayCell
                key={key}
                day={day}
                inMonth={inMonth}
                isToday={isToday}
                occurrences={dayOccs}
                dayTotalCents={dayTotalCents}
                onJumpToRow={onJumpToRow}
              />
            );
          })}
        </div>

        <p className="text-muted-foreground text-[11px]">
          Calendar is a forecast based on Plaid&rsquo;s detected cadence. Real charge
          dates can drift ±1–3 days; we don&rsquo;t hit Plaid for predictions.
        </p>
      </CardContent>
    </Card>
  );
}

function DayCell({
  day,
  inMonth,
  isToday,
  occurrences,
  dayTotalCents,
  onJumpToRow,
}: {
  day: Date;
  inMonth: boolean;
  isToday: boolean;
  occurrences: Occurrence[];
  dayTotalCents: number;
  onJumpToRow: (id: number) => void;
}) {
  const visible = occurrences.slice(0, 2);
  const overflow = occurrences.length - visible.length;

  return (
    <div
      className={cn(
        "relative flex min-h-[88px] flex-col gap-1 rounded-md border p-1.5 text-xs",
        "transition-colors",
        inMonth
          ? "bg-background hover:bg-muted/40"
          : "bg-muted/20 text-muted-foreground",
        isToday && "ring-1 ring-primary/60",
      )}
    >
      <div className="flex items-baseline justify-between">
        <span
          className={cn(
            "tabular-nums font-medium",
            isToday && "text-primary",
          )}
        >
          {format(day, "d")}
        </span>
        {dayTotalCents > 0 && inMonth ? (
          <span className="text-muted-foreground tabular-nums text-[10px]">
            {formatMoney(dayTotalCents)}
          </span>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-0.5">
        {visible.map((occ, i) => (
          <DayChip key={`${occ.stream.id}-${i}`} occ={occ} onClick={onJumpToRow} />
        ))}
        {overflow > 0 ? (
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground self-start text-[10px] underline-offset-2 hover:underline"
              >
                +{overflow} more
              </button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-72 p-2">
              <div className="text-muted-foreground mb-2 text-[11px] uppercase tracking-wide">
                {format(day, "EEEE, MMM d")}
              </div>
              <div className="flex flex-col gap-1">
                {occurrences.map((occ, i) => (
                  <DayPopoverRow
                    key={`${occ.stream.id}-${i}`}
                    occ={occ}
                    onClick={onJumpToRow}
                  />
                ))}
              </div>
            </PopoverContent>
          </Popover>
        ) : null}
      </div>
    </div>
  );
}

function DayChip({
  occ,
  onClick,
}: {
  occ: Occurrence;
  onClick: (id: number) => void;
}) {
  const { stream } = occ;
  const isOutflow = stream.direction === "outflow";
  const muted = effectiveUserStatus(stream) !== "active";
  const cents = Math.abs(stream.last_amount_cents ?? stream.average_amount_cents ?? 0);
  const tone = muted
    ? "border-border/40 bg-muted/30 text-muted-foreground"
    : isOutflow
      ? "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300"
      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  return (
    <button
      type="button"
      onClick={() => onClick(stream.id)}
      title={`${streamTitle(stream)} · ${formatMoney(cents)}`}
      className={cn(
        "inline-flex w-full items-center gap-1 truncate rounded-sm border px-1 py-0.5 text-[10px] leading-tight transition-colors hover:opacity-80",
        tone,
      )}
    >
      <span className="truncate">{streamTitle(stream)}</span>
      <span className="tabular-nums shrink-0 ml-auto">
        {formatMoney(cents).replace(".00", "")}
      </span>
    </button>
  );
}

function DayPopoverRow({
  occ,
  onClick,
}: {
  occ: Occurrence;
  onClick: (id: number) => void;
}) {
  const { stream } = occ;
  const cents = Math.abs(stream.last_amount_cents ?? stream.average_amount_cents ?? 0);
  return (
    <button
      type="button"
      onClick={() => onClick(stream.id)}
      className="hover:bg-muted/60 flex items-center gap-2 rounded-sm px-1.5 py-1 text-left text-xs"
    >
      <StreamAvatar stream={stream} size={20} />
      <span className="min-w-0 flex-1 truncate">{streamTitle(stream)}</span>
      <span className="tabular-nums">{formatMoney(cents)}</span>
    </button>
  );
}
