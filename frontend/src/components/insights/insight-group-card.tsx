"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import {
  ArrowUpRight,
  BellOff,
  ChevronDown,
  ChevronUp,
  Loader2,
  MoreHorizontal,
  Undo2,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { InsightCard as InsightCardModel } from "@/lib/api";
import type { InsightGroup } from "@/lib/insights-grouping";
import { visualFor } from "@/lib/insights-icons";
import { cn } from "@/lib/utils";

/**
 * How many list items render before the user expands a grouped card.
 * Caps multi-alert clusters (e.g. category_trend × 5) so they don't
 * dwarf a sibling tile in the same row.
 */
const COLLAPSED_ITEM_LIMIT = 3;

const SNOOZE_PRESETS: { days: number; label: string }[] = [
  { days: 1, label: "1 day" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "Until next quarter" },
];

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
  /** Compact tile mode renders a single-fact info card as a slim row. */
  compact?: boolean;
}

function isHidden(card: InsightCardModel): boolean {
  const s = card.user_state;
  if (!s) return false;
  if (s.dismissed) return true;
  if (s.snoozed_until && new Date(s.snoozed_until) > new Date()) return true;
  return false;
}

/** Severity-aware shell so warn cards visually pop without an explicit badge. */
function severityShell(severity: string, hidden: boolean): string {
  const base = "group/insight relative overflow-hidden transition-all duration-300 hover:shadow-md";
  const sev =
    severity === "warn"
      ? "border-l-4 border-l-amber-500 border-amber-500/25 bg-amber-500/[0.04]"
      : "border-border/70 bg-card";
  return cn(base, sev, hidden && "opacity-60");
}

function formatSince(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: false });
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Action cluster — icon-only, lives in the corner of every card
// ---------------------------------------------------------------------------

function ActionCluster({
  card,
  hidden,
  handlers,
  variant = "corner",
}: {
  card: InsightCardModel;
  hidden: boolean;
  handlers: InsightActionHandlers;
  /**
   * ``corner`` floats the cluster top-right (used by Card, Hero, Tile).
   * ``inline`` keeps it inline with text (used inside grouped lists where
   * each item is a row, not a card). The visual treatment is the same;
   * only positioning differs.
   */
  variant?: "corner" | "inline";
}) {
  const wrapperClass =
    variant === "corner"
      ? "absolute right-3 top-3 flex items-center gap-0.5 opacity-100 sm:opacity-0 sm:group-hover/insight:opacity-100 transition-opacity"
      : "flex items-center gap-0.5";

  if (hidden) {
    return (
      <div className={wrapperClass}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="size-7"
              onClick={() => handlers.onUnhide(card)}
              disabled={handlers.isUnhiding}
              aria-label="Unhide alert"
            >
              {handlers.isUnhiding ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Undo2 className="size-3.5" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>Unhide</TooltipContent>
        </Tooltip>
      </div>
    );
  }

  return (
    <div className={wrapperClass}>
      <Popover>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="size-7"
                aria-label="Snooze alert"
                disabled={handlers.isSnoozing}
              >
                {handlers.isSnoozing ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <BellOff className="size-3.5" />
                )}
              </Button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent>Snooze</TooltipContent>
        </Tooltip>
        <PopoverContent className="w-44 p-1.5" align="end">
          <p className="px-2 pb-1.5 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Snooze for
          </p>
          {SNOOZE_PRESETS.map((p) => (
            <button
              key={p.days}
              type="button"
              onClick={() => handlers.onSnooze(card, p.days)}
              className="hover:bg-muted flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-sm transition-colors"
            >
              <span>{p.label}</span>
              <span className="text-muted-foreground text-xs">{p.days}d</span>
            </button>
          ))}
        </PopoverContent>
      </Popover>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            size="icon"
            variant="ghost"
            className="size-7"
            onClick={() => handlers.onDismiss(card)}
            disabled={handlers.isDismissing}
            aria-label="Dismiss alert"
          >
            {handlers.isDismissing ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <X className="size-3.5" />
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent>Dismiss</TooltipContent>
      </Tooltip>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact tile — for one-line info cards (top_category, forecast)
// ---------------------------------------------------------------------------

function CompactTile({ group, handlers }: InsightGroupCardProps) {
  const card = group.cards[0];
  const hidden = isHidden(card);
  const visual = visualFor(card.type);
  const Icon = visual.icon;
  const since = formatSince(card.first_seen_at);
  return (
    <Card className={severityShell(card.severity, hidden)}>
      <CardContent className="flex items-center gap-3 px-4 py-3.5">
        <div
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-lg",
            "bg-muted/60",
          )}
        >
          <Icon className="size-4 text-foreground/80" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-xs font-medium text-muted-foreground">
              {card.title}
            </p>
            {card.is_new && (
              <Badge variant="outline" className="h-4 shrink-0 px-1 text-[9px]">
                NEW
              </Badge>
            )}
          </div>
          <p className="truncate text-sm font-semibold leading-tight">
            {card.summary}
          </p>
          {(card.detail || since) && (
            <p className="text-muted-foreground mt-0.5 truncate text-xs">
              {card.detail ?? `Surfaced ${since} ago`}
            </p>
          )}
        </div>
        {card.action_url && (
          <Button asChild size="icon" variant="ghost" className="size-7 shrink-0">
            <Link href={card.action_url} aria-label={card.action_label ?? "Open"}>
              <ArrowUpRight className="size-4" />
            </Link>
          </Button>
        )}
        <TooltipProvider>
          <ActionCluster
            card={card}
            hidden={hidden}
            handlers={handlers}
            variant="inline"
          />
        </TooltipProvider>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Standard card — single alert
// ---------------------------------------------------------------------------

function SingleCard({ group, handlers }: InsightGroupCardProps) {
  const card = group.cards[0];
  const hidden = isHidden(card);
  const visual = visualFor(card.type);
  const Icon = visual.icon;
  const since = formatSince(card.first_seen_at);
  const snoozedUntilNice = useMemo(() => {
    const s = card.user_state?.snoozed_until;
    if (!s || card.user_state?.dismissed) return null;
    try {
      return new Date(s).toLocaleDateString();
    } catch {
      return null;
    }
  }, [card.user_state]);
  return (
    <TooltipProvider>
      <Card className={severityShell(card.severity, hidden)}>
        <ActionCluster card={card} hidden={hidden} handlers={handlers} />
        <CardHeader className="pb-2 pr-20">
          <div className="flex items-start gap-2.5">
            <span
              className={cn(
                "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md",
                card.severity === "warn"
                  ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                  : "bg-muted/70 text-foreground/70",
              )}
              aria-hidden
            >
              <Icon className="size-4" />
            </span>
            <div className="min-w-0 flex-1 space-y-0.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <CardTitle className="text-sm font-semibold tracking-tight">
                  {card.title}
                </CardTitle>
                {card.is_new && !hidden && (
                  <Badge
                    variant="outline"
                    className="h-4 px-1 text-[9px] uppercase tracking-wide"
                  >
                    New
                  </Badge>
                )}
              </div>
              <p className="text-sm font-medium leading-snug text-foreground/90">
                {card.summary}
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          {card.detail && (
            <p className="text-muted-foreground text-xs leading-relaxed">
              {card.detail}
            </p>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <div className="flex items-center gap-2">
              {card.action_url && card.action_label && (
                <Button asChild size="sm" variant="outline" className="h-7 text-xs">
                  <Link href={card.action_url}>
                    {card.action_label}
                    <ArrowUpRight className="size-3" aria-hidden />
                  </Link>
                </Button>
              )}
              {snoozedUntilNice && (
                <span className="text-muted-foreground text-[11px]">
                  Snoozed · {snoozedUntilNice}
                </span>
              )}
            </div>
            {since && (
              <span className="text-muted-foreground text-[11px]">
                {since} ago
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Grouped card — multiple alerts of the same type
// ---------------------------------------------------------------------------

function GroupedCard({ group, handlers }: InsightGroupCardProps) {
  const [expanded, setExpanded] = useState(false);
  const overflow = Math.max(0, group.cards.length - COLLAPSED_ITEM_LIMIT);
  const visibleCards = expanded
    ? group.cards
    : group.cards.slice(0, COLLAPSED_ITEM_LIMIT);
  const visual = visualFor(group.type);
  const Icon = visual.icon;
  return (
    <TooltipProvider>
      <Card className={severityShell(group.severity, group.allHidden)}>
        <CardHeader className="pb-2">
          <div className="flex items-start gap-2.5">
            <span
              className={cn(
                "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md",
                group.severity === "warn"
                  ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                  : "bg-muted/70 text-foreground/70",
              )}
              aria-hidden
            >
              <Icon className="size-4" />
            </span>
            <div className="min-w-0 flex-1 space-y-0.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <CardTitle className="text-sm font-semibold tracking-tight">
                  {group.title}
                </CardTitle>
                <Badge
                  variant="secondary"
                  className="h-4 px-1.5 text-[10px] tabular-nums"
                >
                  {group.cards.length}
                </Badge>
                {group.hasNew && !group.allHidden && (
                  <Badge
                    variant="outline"
                    className="h-4 px-1 text-[9px] uppercase tracking-wide"
                  >
                    New
                  </Badge>
                )}
              </div>
              <p className="text-muted-foreground text-xs leading-snug">
                {group.visibleCount > 0
                  ? `${group.visibleCount} active alert${group.visibleCount === 1 ? "" : "s"}`
                  : "All alerts in this group are hidden"}
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-0 divide-y divide-border/40 p-0">
          {visibleCards.map((card) => {
            const hidden = isHidden(card);
            return (
              <div
                key={card.dedupe_key}
                className={cn(
                  "group/row relative flex items-start gap-3 px-5 py-3",
                  hidden && "opacity-60",
                )}
              >
                <div className="min-w-0 flex-1 space-y-0.5">
                  <div className="flex items-center gap-1.5">
                    <p className="text-sm font-medium leading-snug">
                      {card.summary}
                    </p>
                    {card.is_new && !hidden && (
                      <Badge
                        variant="outline"
                        className="h-4 px-1 text-[9px] uppercase tracking-wide"
                      >
                        New
                      </Badge>
                    )}
                  </div>
                  {card.detail && (
                    <p className="text-muted-foreground text-xs leading-relaxed">
                      {card.detail}
                    </p>
                  )}
                  <div className="flex items-center gap-2 pt-1">
                    {card.action_url && card.action_label && (
                      <Button
                        asChild
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-[11px]"
                      >
                        <Link href={card.action_url}>
                          {card.action_label}
                          <ArrowUpRight className="size-3" aria-hidden />
                        </Link>
                      </Button>
                    )}
                    {card.user_state?.snoozed_until &&
                      !card.user_state?.dismissed && (
                        <span className="text-muted-foreground text-[10px]">
                          Snoozed ·{" "}
                          {new Date(card.user_state.snoozed_until).toLocaleDateString()}
                        </span>
                      )}
                  </div>
                </div>
                <RowActions
                  card={card}
                  hidden={hidden}
                  handlers={handlers}
                />
              </div>
            );
          })}
          {overflow > 0 ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="text-muted-foreground hover:bg-muted/40 hover:text-foreground flex w-full items-center justify-center gap-1 px-6 py-2.5 text-xs transition-colors"
            >
              {expanded ? (
                <>
                  <ChevronUp className="size-3.5" />
                  Show less
                </>
              ) : (
                <>
                  <ChevronDown className="size-3.5" />
                  Show {overflow} more
                </>
              )}
            </button>
          ) : null}
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}

/**
 * Per-row action cluster inside a grouped list. We use an overflow menu
 * (popover) instead of three inline buttons so a 5-alert group doesn't
 * cram 15 buttons onto the screen.
 */
function RowActions({
  card,
  hidden,
  handlers,
}: {
  card: InsightCardModel;
  hidden: boolean;
  handlers: InsightActionHandlers;
}) {
  if (hidden) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            size="icon"
            variant="ghost"
            className="size-7 shrink-0 opacity-100 sm:opacity-0 sm:group-hover/row:opacity-100"
            onClick={() => handlers.onUnhide(card)}
            disabled={handlers.isUnhiding}
            aria-label="Unhide alert"
          >
            {handlers.isUnhiding ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Undo2 className="size-3.5" />
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent>Unhide</TooltipContent>
      </Tooltip>
    );
  }
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          size="icon"
          variant="ghost"
          className="size-7 shrink-0 opacity-100 sm:opacity-0 sm:group-hover/row:opacity-100"
          aria-label="More actions"
        >
          <MoreHorizontal className="size-3.5" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-48 p-1.5" align="end">
        <p className="px-2 pb-1.5 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Snooze for
        </p>
        {SNOOZE_PRESETS.map((p) => (
          <button
            key={p.days}
            type="button"
            onClick={() => handlers.onSnooze(card, p.days)}
            className="hover:bg-muted flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-sm transition-colors"
          >
            <span>{p.label}</span>
            <span className="text-muted-foreground text-xs">{p.days}d</span>
          </button>
        ))}
        <div className="my-1 border-t border-border/60" />
        <button
          type="button"
          onClick={() => handlers.onDismiss(card)}
          className="hover:bg-destructive/10 hover:text-destructive flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm transition-colors"
        >
          <X className="size-3.5" />
          Dismiss
        </button>
      </PopoverContent>
    </Popover>
  );
}

export function InsightGroupCard(props: InsightGroupCardProps) {
  if (props.compact && props.group.cards.length === 1) {
    return <CompactTile {...props} />;
  }
  if (props.group.cards.length <= 1) return <SingleCard {...props} />;
  return <GroupedCard {...props} />;
}
