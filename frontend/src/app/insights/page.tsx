"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout/app-layout";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { insightsApi, type InsightCard as InsightCardModel } from "@/lib/api";
import { groupInsightCards } from "@/lib/insights-grouping";
import {
  InsightGroupCard,
  type InsightActionHandlers,
} from "@/components/insights/insight-group-card";
import { onMutationError } from "@/lib/notify";
import { ArrowLeft, Sparkles } from "lucide-react";

export default function InsightsPage() {
  const queryClient = useQueryClient();
  const [showHidden, setShowHidden] = useState(false);
  const feedQuery = useQuery({
    queryKey: ["insights", "feed", { includeHidden: showHidden }],
    queryFn: () => insightsApi.getFeed(showHidden),
  });

  const markMutation = useMutation({
    mutationFn: insightsApi.markViewed,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights", "feed"] });
    },
    onError: onMutationError("Could not mark insights as seen."),
  });

  const dismissMutation = useMutation({
    mutationFn: (dedupeKey: string) => insightsApi.dismiss(dedupeKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights", "feed"] });
    },
    onError: onMutationError("Could not dismiss insight."),
  });

  const snoozeMutation = useMutation({
    mutationFn: ({ dedupeKey, until }: { dedupeKey: string; until: Date }) =>
      insightsApi.snooze(dedupeKey, until),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights", "feed"] });
    },
    onError: onMutationError("Could not snooze insight."),
  });

  const unhideMutation = useMutation({
    mutationFn: (dedupeKey: string) => insightsApi.unhide(dedupeKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights", "feed"] });
    },
    onError: onMutationError("Could not unhide insight."),
  });

  const handleSnooze = (card: InsightCardModel, days: number) => {
    const until = new Date();
    until.setDate(until.getDate() + days);
    snoozeMutation.mutate({ dedupeKey: card.dedupe_key, until });
  };

  // Auto mark-as-seen on first mount so the Dashboard/sidebar "new" badge
  // clears immediately when the user navigates here. The explicit button
  // is kept for users who want to re-trigger it (rare, but low-cost).
  const autoSeenFired = useRef(false);
  useEffect(() => {
    if (autoSeenFired.current) return;
    if (feedQuery.isLoading || feedQuery.isError) return;
    autoSeenFired.current = true;
    markMutation.mutate();
    // We only want this effect to run once the feed is ready, not on every
    // mutation state change — depending on mutation here would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feedQuery.isLoading, feedQuery.isError]);

  const data = feedQuery.data;
  const groups = groupInsightCards(data?.cards);
  const handlers: InsightActionHandlers = {
    onSnooze: handleSnooze,
    onDismiss: (card) => dismissMutation.mutate(card.dedupe_key),
    onUnhide: (card) => unhideMutation.mutate(card.dedupe_key),
    isSnoozing: snoozeMutation.isPending,
    isDismissing: dismissMutation.isPending,
    isUnhiding: unhideMutation.isPending,
  };

  return (
    <AppLayout>
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <Link
              href="/"
              className="text-muted-foreground mb-2 inline-flex items-center gap-1 text-sm hover:text-foreground"
            >
              <ArrowLeft className="size-4" />
              Dashboard
            </Link>
            <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
            <p className="text-muted-foreground text-sm">
              Stories from your synced data — no separate Plaid “behavior” feed.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setShowHidden((v) => !v)}
            >
              {showHidden ? "Hide dismissed" : "Show dismissed"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => markMutation.mutate()}
              disabled={markMutation.isPending}
            >
              Mark as seen
            </Button>
          </div>
        </div>

        {feedQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : feedQuery.isError ? (
          <p className="text-destructive text-sm">Could not load insights.</p>
        ) : !data?.cards || data.cards.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
              <div className="flex size-12 items-center justify-center rounded-full bg-primary/10">
                <Sparkles className="size-6 text-primary" />
              </div>
              <div className="space-y-1">
                <p className="font-medium">Nothing to show yet</p>
                <p className="text-muted-foreground max-w-xs text-sm">
                  Insights appear once you have synced transactions or logged cash spending.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2 pt-2">
                <Button asChild size="sm" variant="outline">
                  <Link href="/settings">Connect a bank</Link>
                </Button>
                <Button asChild size="sm">
                  <Link href="/transactions">Add cash transaction</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {groups.map((group) => (
              <InsightGroupCard
                key={group.key}
                group={group}
                handlers={handlers}
              />
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
