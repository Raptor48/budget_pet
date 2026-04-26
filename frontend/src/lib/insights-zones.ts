/**
 * Split insight groups into the layout zones used by the page:
 *
 *   ``hero``   — full-width card (currently only ``financial_health``)
 *   ``warn``   — actionable alerts (severity === "warn"); rendered first
 *   ``info``   — heads-up cards (severity === "info"); rendered after warns
 *
 * The grouping logic in ``insights-grouping.ts`` already collapses
 * sibling cards of the same type into a single ``InsightGroup``; this
 * file is just the next layer of presentation routing.
 */
import type { InsightGroup } from "@/lib/insights-grouping";

export type InsightZone = "hero" | "warn" | "info";

const HERO_TYPES = new Set<string>(["financial_health"]);

export interface ZonedInsights {
  hero: InsightGroup[];
  warn: InsightGroup[];
  info: InsightGroup[];
}

export function zoneInsightGroups(groups: InsightGroup[]): ZonedInsights {
  const hero: InsightGroup[] = [];
  const warn: InsightGroup[] = [];
  const info: InsightGroup[] = [];
  for (const g of groups) {
    if (HERO_TYPES.has(g.type)) {
      hero.push(g);
      continue;
    }
    if (g.severity === "warn") {
      warn.push(g);
      continue;
    }
    info.push(g);
  }
  return { hero, warn, info };
}

/**
 * Single-fact info cards (one underlying card, ``info`` severity, no
 * detail body) render as compact tiles to balance card density. Multi-
 * card groups always use the full standard card so the listed items have
 * room to breathe.
 */
export function isCompactTileGroup(group: InsightGroup): boolean {
  if (group.severity !== "info") return false;
  if (group.cards.length !== 1) return false;
  // Heuristic: a card with no detail body is one-fact and looks great as
  // a tile; a card with a paragraph of detail (cash_flow_mom) reads
  // better at full width.
  const onlyCard = group.cards[0];
  return !onlyCard.detail || onlyCard.detail.length < 80;
}
