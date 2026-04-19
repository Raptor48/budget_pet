import type { InsightCard, InsightsFeed } from "@/lib/api";

/**
 * Pick the card that should power the Dashboard teaser.
 *
 * Rule: prefer the first `warn` card, falling back to the first `info`
 * card. The old behaviour of always showing `cards[0]` always surfaced
 * `financial_health` (info), so users never saw actionable alerts in
 * the teaser.
 */
export function pickTeaser(feed: InsightsFeed | undefined): InsightCard | null {
  if (!feed?.cards?.length) return null;
  return feed.cards.find((c) => c.severity === "warn") ?? feed.cards[0] ?? null;
}

/**
 * Compose the badge label for the Dashboard + sidebar.
 * - `new_count > 0` → "N new • M alerts" (or just "N new" when no other warns)
 * - otherwise → "M alerts" / "—"
 */
export function composeInsightsBadge(feed: InsightsFeed | undefined): string {
  if (!feed) return "—";
  const actionable = feed.actionable_count ?? 0;
  const fresh = feed.new_count ?? 0;
  if (fresh > 0 && actionable > 0 && fresh !== actionable) {
    return `${fresh} new • ${actionable} alerts`;
  }
  if (fresh > 0) return `${fresh} new`;
  return `${actionable} alerts`;
}
