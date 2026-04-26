"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout/app-layout";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  insightsApi,
  reportsApi,
  type InsightCard as InsightCardModel,
} from "@/lib/api";
import { groupInsightCards } from "@/lib/insights-grouping";
import {
  isCompactTileGroup,
  zoneInsightGroups,
} from "@/lib/insights-zones";
import {
  InsightGroupCard,
  type InsightActionHandlers,
} from "@/components/insights/insight-group-card";
import { InsightsHeroCard } from "@/components/insights/insights-hero-card";
import { onMutationError } from "@/lib/notify";
import { ArrowLeft, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

type ZoneFilter = "all" | "action" | "heads-up" | "hidden";

export default function InsightsPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ZoneFilter>("all");
  const includeHidden = filter === "hidden";
  const feedQuery = useQuery({
    queryKey: ["insights", "feed", { includeHidden }],
    queryFn: () => insightsApi.getFeed(includeHidden),
  });
  const healthQuery = useQuery({
    queryKey: ["reports", "financial-health"],
    queryFn: () => reportsApi.getFinancialHealth(),
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

  // Auto mark-as-seen on first mount so the Dashboard / sidebar "new"
  // badge clears immediately when the user navigates here.
  const autoSeenFired = useRef(false);
  useEffect(() => {
    if (autoSeenFired.current) return;
    if (feedQuery.isLoading || feedQuery.isError) return;
    autoSeenFired.current = true;
    markMutation.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feedQuery.isLoading, feedQuery.isError]);

  const data = feedQuery.data;
  const allGroups = useMemo(
    () => groupInsightCards(data?.cards),
    [data?.cards],
  );
  const zones = useMemo(() => zoneInsightGroups(allGroups), [allGroups]);

  // Severity counts ignore the hero (it's not a warn / info card per se).
  const counts = useMemo(() => {
    let warn = 0;
    let info = 0;
    let hidden = 0;
    for (const g of allGroups) {
      if (g.severity === "warn") warn += g.visibleCount;
      else info += g.visibleCount;
      if (g.allHidden) hidden += g.cards.length;
    }
    return { warn, info, hidden };
  }, [allGroups]);

  const handlers: InsightActionHandlers = {
    onSnooze: handleSnooze,
    onDismiss: (card) => dismissMutation.mutate(card.dedupe_key),
    onUnhide: (card) => unhideMutation.mutate(card.dedupe_key),
    isSnoozing: snoozeMutation.isPending,
    isDismissing: dismissMutation.isPending,
    isUnhiding: unhideMutation.isPending,
  };

  const showWarn = filter === "all" || filter === "action" || filter === "hidden";
  const showInfo = filter === "all" || filter === "heads-up" || filter === "hidden";
  const showHero = filter === "all" || filter === "hidden";

  // Compact tiles vs full cards split for the Heads-up zone.
  const { compactGroups, standardInfoGroups } = useMemo(() => {
    const compact: typeof zones.info = [];
    const standard: typeof zones.info = [];
    for (const g of zones.info) {
      if (isCompactTileGroup(g)) compact.push(g);
      else standard.push(g);
    }
    return { compactGroups: compact, standardInfoGroups: standard };
    // ``zones`` itself is the runtime reference (the destructured ``info``
    // is just a TS type assertion above); listing the parent is what
    // exhaustive-deps insists on and what's actually correct here.
  }, [zones]);

  return (
    <AppLayout>
      <div className="space-y-6">
        <PageHeader
          filter={filter}
          onFilter={setFilter}
          warnCount={counts.warn}
          infoCount={counts.info}
          hiddenCount={counts.hidden}
        />

        {feedQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : feedQuery.isError ? (
          <p className="text-destructive text-sm">Could not load insights.</p>
        ) : !data?.cards || data.cards.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="space-y-8">
            {showHero && zones.hero.length > 0 && (
              <InsightsHeroCard
                score={healthQuery.data}
                isLoading={healthQuery.isLoading}
                isError={healthQuery.isError}
              />
            )}

            {showWarn && zones.warn.length > 0 && (
              <ZoneSection
                eyebrow="Needs action"
                tone="warn"
                count={zones.warn.length}
              >
                {/* Masonry-ish: dense grid lets short cards fill gaps next to
                    tall ones, killing the "giant void next to busy card"
                    problem from the old layout. */}
                <div className="grid gap-3 md:grid-cols-2 md:[grid-auto-flow:row_dense]">
                  {zones.warn.map((group) => (
                    <InsightGroupCard
                      key={group.key}
                      group={group}
                      handlers={handlers}
                    />
                  ))}
                </div>
              </ZoneSection>
            )}

            {showInfo && (compactGroups.length > 0 || standardInfoGroups.length > 0) && (
              <ZoneSection
                eyebrow="Heads up"
                tone="info"
                count={compactGroups.length + standardInfoGroups.length}
              >
                <div className="space-y-3">
                  {compactGroups.length > 0 && (
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                      {compactGroups.map((group) => (
                        <InsightGroupCard
                          key={group.key}
                          group={group}
                          handlers={handlers}
                          compact
                        />
                      ))}
                    </div>
                  )}
                  {standardInfoGroups.length > 0 && (
                    <div className="grid gap-3 md:grid-cols-2 md:[grid-auto-flow:row_dense]">
                      {standardInfoGroups.map((group) => (
                        <InsightGroupCard
                          key={group.key}
                          group={group}
                          handlers={handlers}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </ZoneSection>
            )}

            {/* If a filter excludes everything we'd otherwise show, surface it. */}
            {((filter === "action" && zones.warn.length === 0) ||
              (filter === "heads-up" &&
                compactGroups.length + standardInfoGroups.length === 0) ||
              (filter === "hidden" && counts.hidden === 0)) && (
              <p className="text-muted-foreground py-12 text-center text-sm">
                Nothing here right now.
              </p>
            )}
          </div>
        )}
      </div>
    </AppLayout>
  );
}

// ---------------------------------------------------------------------------
// Header with filter chips
// ---------------------------------------------------------------------------

function PageHeader({
  filter,
  onFilter,
  warnCount,
  infoCount,
  hiddenCount,
}: {
  filter: ZoneFilter;
  onFilter: (f: ZoneFilter) => void;
  warnCount: number;
  infoCount: number;
  hiddenCount: number;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="space-y-1">
        <Link
          href="/"
          className="text-muted-foreground inline-flex items-center gap-1 text-xs hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          Dashboard
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
        <p className="text-muted-foreground text-sm">
          Personalized alerts and trends across all your accounts.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-1 rounded-full border border-border/60 bg-muted/30 p-1">
        <FilterChip active={filter === "all"} onClick={() => onFilter("all")}>
          All
        </FilterChip>
        <FilterChip
          active={filter === "action"}
          onClick={() => onFilter("action")}
          tone="warn"
        >
          Action
          {warnCount > 0 && <span className="tabular-nums">· {warnCount}</span>}
        </FilterChip>
        <FilterChip
          active={filter === "heads-up"}
          onClick={() => onFilter("heads-up")}
        >
          Heads up
          {infoCount > 0 && <span className="tabular-nums">· {infoCount}</span>}
        </FilterChip>
        <FilterChip
          active={filter === "hidden"}
          onClick={() => onFilter("hidden")}
        >
          Hidden
          {hiddenCount > 0 && (
            <span className="tabular-nums">· {hiddenCount}</span>
          )}
        </FilterChip>
      </div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
  tone,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  tone?: "warn";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-colors",
        active
          ? tone === "warn"
            ? "bg-amber-500/15 text-amber-600 dark:text-amber-300"
            : "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Zone section header
// ---------------------------------------------------------------------------

function ZoneSection({
  eyebrow,
  tone,
  count,
  children,
}: {
  eyebrow: string;
  tone: "warn" | "info";
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-flex size-1.5 rounded-full",
            tone === "warn" ? "bg-amber-500" : "bg-muted-foreground/40",
          )}
          aria-hidden
        />
        <h2 className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
          {eyebrow}
        </h2>
        <span className="text-muted-foreground text-xs tabular-nums">
          {count}
        </span>
      </div>
      {children}
    </section>
  );
}

function EmptyState() {
  return (
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
  );
}
