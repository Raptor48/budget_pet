"use client";

import Link from "next/link";
import { BellOff, EyeOff, Sparkles, Undo2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { InsightCard as InsightCardModel } from "@/lib/api";
import type { InsightGroup } from "@/lib/insights-grouping";
import { cn } from "@/lib/utils";

export interface InsightActionHandlers {
  onSnooze: (card: InsightCardModel, days: number) => void;
  onDismiss: (card: InsightCardModel) => void;
  onUnhide: (card: InsightCardModel) => void;
  isSnoozing?: boolean;
  isDismissing?: boolean;
  isUnhiding?: boolean;
}

interface InsightGroupCardProps {
  group: InsightGroup;
  handlers: InsightActionHandlers;
}

function severityStyles(sev: string) {
  if (sev === "warn") return "border-amber-500/40 bg-amber-500/5";
  return "border-border/80 bg-card";
}

function isHidden(card: InsightCardModel): boolean {
  const s = card.user_state;
  if (!s) return false;
  if (s.dismissed) return true;
  if (s.snoozed_until && new Date(s.snoozed_until) > new Date()) return true;
  return false;
}

/**
 * A single-card group falls back to the flat card layout — grouping only
 * helps when there are siblings to collapse, and the flat layout is
 * already well-tuned for standalone alerts.
 */
function SingleCard({ group, handlers }: InsightGroupCardProps) {
  const card = group.cards[0];
  const hidden = isHidden(card);
  return (
    <Card
      className={cn(
        "overflow-hidden transition-shadow duration-300 hover:shadow-md",
        severityStyles(card.severity),
        hidden && "opacity-60",
      )}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="size-4 shrink-0 text-primary" />
            {card.title}
            {card.is_new && !hidden && (
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
        <InsightItemActions card={card} hidden={hidden} handlers={handlers} />
        {card.user_state?.snoozed_until && !card.user_state?.dismissed && (
          <p className="text-muted-foreground text-xs">
            Snoozed until {new Date(card.user_state.snoozed_until).toLocaleDateString()}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function InsightItemActions({
  card,
  hidden,
  handlers,
}: {
  card: InsightCardModel;
  hidden: boolean;
  handlers: InsightActionHandlers;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {card.action_url && card.action_label && (
        <Button asChild size="sm" variant="outline">
          <Link href={card.action_url}>{card.action_label}</Link>
        </Button>
      )}
      {hidden ? (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => handlers.onUnhide(card)}
          disabled={handlers.isUnhiding}
        >
          <Undo2 className="mr-1 size-3.5" />
          Unhide
        </Button>
      ) : (
        <>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => handlers.onSnooze(card, 7)}
            disabled={handlers.isSnoozing}
            title="Hide for 7 days"
          >
            <BellOff className="mr-1 size-3.5" />
            Snooze 7d
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => handlers.onDismiss(card)}
            disabled={handlers.isDismissing}
            title="Dismiss this alert"
          >
            <EyeOff className="mr-1 size-3.5" />
            Dismiss
          </Button>
        </>
      )}
    </div>
  );
}

/**
 * Multi-item group: one card-sized block that lists every underlying
 * alert. Items keep their own snooze/dismiss affordances so the existing
 * "1 alert = 1 dismissable unit" contract is preserved.
 */
function GroupedCard({ group, handlers }: InsightGroupCardProps) {
  return (
    <Card
      className={cn(
        "overflow-hidden transition-shadow duration-300 hover:shadow-md md:col-span-2",
        severityStyles(group.severity),
        group.allHidden && "opacity-60",
      )}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="size-4 shrink-0 text-primary" />
            {group.title}
            <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
              {group.cards.length}
            </Badge>
            {group.hasNew && !group.allHidden && (
              <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                NEW
              </Badge>
            )}
          </CardTitle>
          <Badge
            variant={group.severity === "warn" ? "destructive" : "secondary"}
            className="shrink-0 capitalize"
          >
            {group.severity}
          </Badge>
        </div>
        <CardDescription className="text-foreground/90 text-sm">
          {group.visibleCount > 0
            ? `${group.visibleCount} active alert${group.visibleCount === 1 ? "" : "s"}`
            : "All alerts in this group are hidden"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-0 divide-y divide-border/60 p-0">
        {group.cards.map((card) => {
          const hidden = isHidden(card);
          return (
            <div
              key={card.dedupe_key}
              className={cn(
                "space-y-2 px-6 py-3 first:pt-4 last:pb-4",
                hidden && "opacity-60",
              )}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 space-y-1">
                  <p className="text-foreground/90 text-sm font-medium leading-snug">
                    {card.summary}
                  </p>
                  {card.detail && (
                    <p className="text-muted-foreground text-xs leading-relaxed">
                      {card.detail}
                    </p>
                  )}
                </div>
                {card.is_new && !hidden && (
                  <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                    NEW
                  </Badge>
                )}
              </div>
              <InsightItemActions
                card={card}
                hidden={hidden}
                handlers={handlers}
              />
              {card.user_state?.snoozed_until && !card.user_state?.dismissed && (
                <p className="text-muted-foreground text-xs">
                  Snoozed until {new Date(card.user_state.snoozed_until).toLocaleDateString()}
                </p>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

export function InsightGroupCard(props: InsightGroupCardProps) {
  if (props.group.cards.length <= 1) return <SingleCard {...props} />;
  return <GroupedCard {...props} />;
}
