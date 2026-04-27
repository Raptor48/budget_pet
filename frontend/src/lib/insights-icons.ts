/**
 * Per-card-type visual identity for the Insights feed.
 *
 * Pairing each card type with its own icon + accent color is the cheapest
 * upgrade we can make to the page's scan-ability: instead of a wall of
 * identical Sparkles icons, the eye picks up the right card by shape and
 * color before reading any text. Severity (warn vs info) still drives the
 * card's border treatment — this registry only handles the per-type
 * accent.
 *
 * Add a new card type by extending ``INSIGHT_VISUALS``; missing entries
 * fall back to the neutral Sparkles defaults so the UI never crashes.
 */
import {
  Activity,
  AlertOctagon,
  BarChart3,
  CalendarClock,
  CreditCard,
  PieChart,
  Receipt,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface InsightVisual {
  icon: LucideIcon;
  /** Tailwind color stem; resolved as ``text-${stem}-500`` etc by the consumer. */
  accent: string;
}

const FALLBACK: InsightVisual = { icon: Sparkles, accent: "primary" };

export const INSIGHT_VISUALS: Record<string, InsightVisual> = {
  financial_health: { icon: Activity, accent: "primary" },
  cash_flow_mom: { icon: TrendingUp, accent: "sky" },
  top_category: { icon: PieChart, accent: "violet" },
  category_trend: { icon: BarChart3, accent: "amber" },
  forecast: { icon: CalendarClock, accent: "indigo" },
  liquidity_buffer: { icon: Wallet, accent: "amber" },
  missed_recurring: { icon: AlertOctagon, accent: "amber" },
  duplicate_subscription: { icon: Receipt, accent: "amber" },
  overdue_account: { icon: AlertOctagon, accent: "rose" },
  high_utilization: { icon: CreditCard, accent: "amber" },
  budget_risk: { icon: Target, accent: "rose" },
  price_changes_warn: { icon: TrendingUp, accent: "amber" },
  price_changes_good: { icon: TrendingDown, accent: "emerald" },
};

export function visualFor(type: string): InsightVisual {
  return INSIGHT_VISUALS[type] ?? FALLBACK;
}
