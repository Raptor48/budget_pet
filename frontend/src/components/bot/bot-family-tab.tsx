"use client";

/**
 * Family tab — anniversary tracker + this week's leaderboard.
 *
 * Anniversary is technically also editable from Overview, but here we add
 * the countdown + reminder context that's most useful as a family ritual.
 */
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { botApi } from "@/lib/api";

import { formatCents, formatDate } from "./bot-helpers";

function daysUntil(target: string | null | undefined): number | null {
  if (!target) return null;
  const next = new Date(target);
  if (Number.isNaN(next.getTime())) return null;
  const today = new Date();
  // Bump to this year's anniversary, then next year if already passed.
  next.setFullYear(today.getFullYear());
  if (next < today) next.setFullYear(today.getFullYear() + 1);
  const ms = next.getTime() - today.getTime();
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
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

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-2 text-base font-semibold">Anniversary</h2>
        {!settings.data?.anniversary_date ? (
          <p className="text-sm text-muted-foreground">
            Set the date in <strong>Overview → Anniversary</strong>. The bot
            will quietly DM the gifting partner one week before each year.
          </p>
        ) : (
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-semibold tracking-tight">
              {days ?? "—"}
            </span>
            <span className="text-sm text-muted-foreground">
              days until next anniversary ·{" "}
              {formatDate(settings.data.anniversary_date)}
            </span>
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-base font-semibold">This week — top spenders</h2>
        {leaderboard.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : !leaderboard.data?.entries.length ? (
          <p className="text-sm text-muted-foreground">
            No data yet — sync banks first.
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {leaderboard.data.entries.map((e) => (
              <li
                key={`${e.user_id}-${e.category_id}`}
                className="flex items-center justify-between gap-3 px-4 py-3 text-sm"
              >
                <div className="flex items-center gap-2">
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
