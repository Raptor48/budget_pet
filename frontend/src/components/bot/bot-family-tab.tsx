"use client";

/**
 * Family tab — anniversary tracker + this week's leaderboard.
 *
 * Anniversary is technically also editable from Overview, but here we add
 * the countdown + reminder context that's most useful as a family ritual.
 */
import { useQuery } from "@tanstack/react-query";
import { CalendarHeart, PartyPopper, Trophy, User } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { botApi } from "@/lib/api";

import { formatCents, formatDate } from "./bot-helpers";

function daysUntil(target: string | null | undefined): number | null {
  if (!target) return null;
  const next = new Date(target);
  if (Number.isNaN(next.getTime())) return null;
  const today = new Date();
  // Strip time so 0 days actually means "today" (the bot's day-precision
  // model). Otherwise crossing the hour boundary shows -1 / 365 instead
  // of "Today!".
  today.setHours(0, 0, 0, 0);
  next.setFullYear(today.getFullYear());
  next.setHours(0, 0, 0, 0);
  if (next.getTime() < today.getTime()) {
    next.setFullYear(today.getFullYear() + 1);
  }
  const ms = next.getTime() - today.getTime();
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

export function BotFamilyTab() {
  const settings = useQuery({
    queryKey: ["bot", "settings"],
    queryFn: botApi.getSettings,
  });
  const leaderboard = useQuery({
    queryKey: ["bot", "leaderboard"],
    queryFn: botApi.weeklyLeaderboard,
  });

  const days = daysUntil(settings.data?.anniversary_date);
  const isToday = days === 0;
  const isSoon = days != null && days > 0 && days <= 14;

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-3 flex items-center gap-2 text-base font-semibold">
          <CalendarHeart className="h-4 w-4 text-muted-foreground" />
          Anniversary
        </h2>
        {settings.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : !settings.data?.anniversary_date ? (
          <div className="grid place-items-center rounded-md border border-dashed py-8 text-center">
            <CalendarHeart className="mb-2 h-6 w-6 text-muted-foreground" aria-hidden />
            <p className="text-sm text-muted-foreground">
              Set the date in <strong>Overview → Anniversary</strong>. The bot
              will quietly DM the gifting partner one week before.
            </p>
          </div>
        ) : (
          <div
            className={cn(
              "rounded-md border p-4 transition-colors",
              isToday &&
                "border-rose-500/40 bg-gradient-to-br from-rose-500/10 via-pink-500/5 to-transparent",
              isSoon &&
                "border-amber-500/40 bg-gradient-to-br from-amber-500/10 to-transparent",
              !isToday && !isSoon && "bg-muted/20",
            )}
          >
            {isToday ? (
              <div className="flex items-center gap-3">
                <PartyPopper className="h-7 w-7 text-rose-500" aria-hidden />
                <div>
                  <div className="text-2xl font-semibold tracking-tight text-rose-600 dark:text-rose-400">
                    Today!
                  </div>
                  <div className="text-sm text-muted-foreground">
                    Anniversary on {formatDate(settings.data.anniversary_date)} —
                    say something nice.
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex items-baseline gap-3">
                <span
                  className={cn(
                    "text-3xl font-semibold tracking-tight tabular-nums",
                    isSoon && "text-amber-600 dark:text-amber-400",
                  )}
                >
                  {days ?? "—"}
                </span>
                <span className="text-sm text-muted-foreground">
                  {days === 1 ? "day" : "days"} until next anniversary ·{" "}
                  {formatDate(settings.data.anniversary_date)}
                </span>
              </div>
            )}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-3 flex items-center gap-2 text-base font-semibold">
          <Trophy className="h-4 w-4 text-muted-foreground" />
          This week — top spenders
        </h2>
        {leaderboard.isLoading ? (
          <ul className="divide-y rounded-md border">
            {Array.from({ length: 3 }).map((_, i) => (
              <li key={i} className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-4 w-32" />
                </div>
                <Skeleton className="h-4 w-16" />
              </li>
            ))}
          </ul>
        ) : !leaderboard.data?.entries.length ? (
          <div className="grid place-items-center rounded-md border border-dashed py-8 text-center">
            <Trophy className="mb-2 h-6 w-6 text-muted-foreground" aria-hidden />
            <p className="text-sm text-muted-foreground">
              No data yet — sync banks first.
            </p>
          </div>
        ) : (
          <ul className="divide-y rounded-md border">
            {leaderboard.data.entries.map((e, idx) => (
              <li
                key={`${e.user_id}-${e.category_id}`}
                className={cn(
                  "flex items-center justify-between gap-3 px-4 py-3 text-sm transition-colors",
                  "hover:bg-muted/40",
                  idx === 0 && "bg-gradient-to-r from-amber-500/8 to-transparent",
                )}
              >
                <div className="flex items-center gap-2">
                  {idx === 0 ? (
                    <Trophy className="h-4 w-4 text-amber-500" aria-hidden />
                  ) : (
                    <User className="h-4 w-4 text-muted-foreground" aria-hidden />
                  )}
                  <Badge variant="secondary">{e.username}</Badge>
                  <span className="font-medium">{e.category_name}</span>
                </div>
                <span className="font-mono text-sm">
                  {formatCents(e.amount_cents)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
