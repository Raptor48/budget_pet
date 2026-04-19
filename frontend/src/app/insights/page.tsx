"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout/app-layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { insightsApi, type InsightCard as InsightCardModel } from "@/lib/api";
import { onMutationError } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { ArrowLeft, BellOff, EyeOff, Sparkles, Undo2 } from "lucide-react";

function severityStyles(sev: string) {
  if (sev === "warn")
    return "border-amber-500/40 bg-amber-500/5";
  return "border-border/80 bg-card";
}

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
            {data?.cards?.map((card, i) => {
              const isHidden =
                card.user_state?.dismissed === true ||
                (!!card.user_state?.snoozed_until &&
                  new Date(card.user_state.snoozed_until) > new Date());
              return (
                <Card
                  key={card.dedupe_key ?? `${card.type}-${i}`}
                  className={cn(
                    "overflow-hidden transition-shadow duration-300 hover:shadow-md",
                    severityStyles(card.severity),
                    isHidden && "opacity-60",
                  )}
                >
                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between gap-2">
                      <CardTitle className="flex items-center gap-2 text-base">
                        <Sparkles className="size-4 shrink-0 text-primary" />
                        {card.title}
                        {card.is_new && !isHidden && (
                          <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                            NEW
                          </Badge>
                        )}
                      </CardTitle>
                      <Badge
                        variant={card.severity === "warn" ? "destructive" : "secondary"}
                        className="shrink-0 capitalize"
                      >
                        {card.severity}
                      </Badge>
                    </div>
                    <CardDescription className="text-foreground/90 font-medium">
                      {card.summary}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {card.detail && (
                      <p className="text-muted-foreground text-sm leading-relaxed">
                        {card.detail}
                      </p>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                      {card.action_url && card.action_label && (
                        <Button asChild size="sm" variant="outline">
                          <Link href={card.action_url}>{card.action_label}</Link>
                        </Button>
                      )}
                      {isHidden ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => unhideMutation.mutate(card.dedupe_key)}
                          disabled={unhideMutation.isPending}
                        >
                          <Undo2 className="mr-1 size-3.5" />
                          Unhide
                        </Button>
                      ) : (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleSnooze(card, 7)}
                            disabled={snoozeMutation.isPending}
                            title="Hide for 7 days"
                          >
                            <BellOff className="mr-1 size-3.5" />
                            Snooze 7d
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => dismissMutation.mutate(card.dedupe_key)}
                            disabled={dismissMutation.isPending}
                            title="Dismiss this alert"
                          >
                            <EyeOff className="mr-1 size-3.5" />
                            Dismiss
                          </Button>
                        </>
                      )}
                    </div>
                    {card.user_state?.snoozed_until && !card.user_state?.dismissed && (
                      <p className="text-muted-foreground text-xs">
                        Snoozed until {new Date(card.user_state.snoozed_until).toLocaleDateString()}
                      </p>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
