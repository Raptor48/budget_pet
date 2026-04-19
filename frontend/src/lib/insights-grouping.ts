import type { InsightCard, InsightSeverity } from "@/lib/api";

/**
 * A cluster of insight cards that belong together for display purposes.
 * Clusters are formed by {@link InsightCard.type} so that multiple
 * "Recurring charge missing" or "X up N%" alerts render as a single
 * collapsible block instead of flooding the feed.
 *
 * Each item inside a group remains an independent alert — it keeps its
 * own `dedupe_key`, user state (dismissed/snoozed) and action controls.
 */
export interface InsightGroup {
  key: string;
  type: string;
  title: string;
  severity: InsightSeverity;
  cards: InsightCard[];
  hasNew: boolean;
  allHidden: boolean;
  visibleCount: number;
}

/**
 * Human-friendly block titles per card type. A single, canonical label
 * per group avoids the "Services up 53% / AI Apps up 238%" repetition —
 * the individual numbers move into the list of items.
 */
const GROUP_TITLES: Record<string, string> = {
  budget_risk: "Budgets at risk",
  category_trend: "Category spending up",
  missed_recurring: "Recurring charges missing",
  duplicate_subscription: "Possible duplicate subscriptions",
  overdue_account: "Overdue accounts",
  high_utilization: "Credit-card utilization",
};

/** Fallback label uses the first card's title so unknown types still render. */
function resolveGroupTitle(type: string, fallback: string): string {
  return GROUP_TITLES[type] ?? fallback;
}

/** Warn dominates info when computing a group's aggregate severity. */
function mergeSeverity(
  current: InsightSeverity,
  next: InsightSeverity,
): InsightSeverity {
  if (current === "warn" || next === "warn") return "warn";
  return next;
}

function isCardHidden(card: InsightCard, now: Date): boolean {
  const s = card.user_state;
  if (!s) return false;
  if (s.dismissed) return true;
  if (s.snoozed_until && new Date(s.snoozed_until) > now) return true;
  return false;
}

/**
 * Group cards by `type`, preserving the server ordering:
 * the position of the first card of each type determines the group's
 * position in the list. This keeps warn-first ordering from the API.
 */
export function groupInsightCards(
  cards: InsightCard[] | undefined,
  now: Date = new Date(),
): InsightGroup[] {
  if (!cards?.length) return [];
  const index = new Map<string, InsightGroup>();
  const order: string[] = [];

  for (const card of cards) {
    const type = card.type || "other";
    let group = index.get(type);
    if (!group) {
      group = {
        key: type,
        type,
        title: resolveGroupTitle(type, card.title),
        severity: card.severity,
        cards: [],
        hasNew: false,
        allHidden: true,
        visibleCount: 0,
      };
      index.set(type, group);
      order.push(type);
    }
    group.cards.push(card);
    group.severity = mergeSeverity(group.severity, card.severity);
    if (card.is_new) group.hasNew = true;
    const hidden = isCardHidden(card, now);
    if (!hidden) {
      group.allHidden = false;
      group.visibleCount += 1;
    }
  }

  return order.map((type) => index.get(type)!);
}
