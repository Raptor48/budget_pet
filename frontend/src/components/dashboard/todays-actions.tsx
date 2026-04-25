"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  Lightbulb,
  Target,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { InsightCard } from "@/lib/api";
import type {
  BudgetProgress,
  ForecastEntry,
  PlaidItem,
} from "@/types/v2";

type Tone = "amber" | "rose" | "primary" | "muted";

interface ActionItem {
  key: string;
  href: string;
  icon: LucideIcon;
  title: string;
  detail: string;
  tone: Tone;
}

function formatUsd(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function daysUntil(iso: string): number {
  const target = new Date(iso).getTime();
  const now = Date.now();
  return Math.ceil((target - now) / 86_400_000);
}

/**
 * Aggregate every "you should look at this" signal we already have on the
 * Dashboard into a compact, scannable action grid. Pulls only from queries
 * that are already running for other Dashboard widgets, so this section
 * costs zero additional network traffic — it's pure UI composition.
 *
 * Hides itself entirely when there's nothing to act on: the empty state
 * here would be more noise than signal.
 */
export function TodaysActionsSection({
  plaidItems,
  budgets,
  forecast,
  insightCards,
}: {
  plaidItems: PlaidItem[];
  budgets: BudgetProgress[];
  forecast: ForecastEntry[];
  insightCards: InsightCard[];
}) {
  const actions: ActionItem[] = [];

  // 1. Plaid items needing reauth — most urgent because data stops syncing.
  const stuckBanks = plaidItems.filter((i) => i.item_login_required);
  if (stuckBanks.length > 0) {
    const names = stuckBanks
      .map((i) => i.institution_name)
      .filter((n): n is string => Boolean(n))
      .slice(0, 2);
    actions.push({
      key: "plaid-attention",
      href: "/settings#settings-bank-connections",
      icon: AlertTriangle,
      title:
        stuckBanks.length === 1
          ? "1 bank needs reconnect"
          : `${stuckBanks.length} banks need reconnect`,
      detail: names.length > 0 ? names.join(" · ") : "Open Plaid Link to refresh",
      tone: "amber",
    });
  }

  // 2. Budgets over their cap. Lists up to 2 by name with their %.
  const overBudgets = budgets.filter((b) => b.percent_used > 100);
  if (overBudgets.length > 0) {
    const sample = [...overBudgets]
      .sort((a, b) => b.percent_used - a.percent_used)
      .slice(0, 2)
      .map((b) => `${b.category_name} ${Math.round(b.percent_used)}%`);
    actions.push({
      key: "budgets-over",
      href: "/settings/budgets",
      icon: Target,
      title:
        overBudgets.length === 1
          ? "1 budget over limit"
          : `${overBudgets.length} budgets over limit`,
      detail: sample.join(" · "),
      tone: "rose",
    });
  }

  // 3. Bills due in the next 7 days. Sum the magnitude so the user knows
  //    the cash impact at a glance.
  const dueSoon = forecast.filter((f) => {
    const d = daysUntil(f.date);
    return d >= 0 && d <= 7;
  });
  if (dueSoon.length > 0) {
    const total = dueSoon.reduce((s, f) => s + Math.abs(f.amount_cents), 0);
    actions.push({
      key: "bills-due",
      href: "/recurring",
      icon: CalendarClock,
      title:
        dueSoon.length === 1
          ? "1 bill due in 7 days"
          : `${dueSoon.length} bills due in 7 days`,
      detail: `${formatUsd(total)} total`,
      tone: "primary",
    });
  }

  // 4. Insight cards flagged warn — already surfaced as the lone teaser in
  //    the KPI row, but power users with multiple alerts deserve a count
  //    here too. The detail line teases the most-severe summary.
  const warnInsights = insightCards.filter((c) => c.severity === "warn");
  if (warnInsights.length > 0) {
    const top = warnInsights[0];
    actions.push({
      key: "insights-warn",
      href: "/insights",
      icon: Lightbulb,
      title:
        warnInsights.length === 1
          ? "1 insight needs attention"
          : `${warnInsights.length} insights need attention`,
      detail: top?.title ?? top?.summary ?? "Open the feed",
      tone: "amber",
    });
  }

  if (actions.length === 0) {
    return null;
  }

  return (
    <section
      aria-labelledby="todays-actions-heading"
      className="space-y-3 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300"
    >
      <div className="flex items-baseline justify-between">
        <h2
          id="todays-actions-heading"
          className="text-sm font-semibold tracking-tight"
        >
          Today&rsquo;s actions
        </h2>
        <span className="text-xs text-muted-foreground">
          {actions.length} {actions.length === 1 ? "item" : "items"}
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {actions.map((action, i) => (
          <ActionCard key={action.key} action={action} delayMs={i * 40} />
        ))}
      </div>
    </section>
  );
}

function ActionCard({ action, delayMs }: { action: ActionItem; delayMs: number }) {
  const Icon = action.icon;
  const toneBorder =
    action.tone === "amber"
      ? "border-amber-500/40 hover:border-amber-500/70"
      : action.tone === "rose"
        ? "border-rose-500/40 hover:border-rose-500/70"
        : action.tone === "primary"
          ? "border-primary/30 hover:border-primary/60"
          : "border-border/60 hover:border-border";
  const toneIcon =
    action.tone === "amber"
      ? "text-amber-600 dark:text-amber-400"
      : action.tone === "rose"
        ? "text-rose-600 dark:text-rose-400"
        : action.tone === "primary"
          ? "text-primary"
          : "text-muted-foreground";
  const toneBg =
    action.tone === "amber"
      ? "bg-amber-500/10"
      : action.tone === "rose"
        ? "bg-rose-500/10"
        : action.tone === "primary"
          ? "bg-primary/10"
          : "bg-muted/40";
  return (
    <Link
      href={action.href}
      className="group block outline-none focus-visible:ring-2 focus-visible:ring-ring/40 rounded-xl"
      style={{ animationDelay: `${delayMs}ms` }}
    >
      <div
        className={cn(
          "flex items-center gap-3 rounded-xl border bg-card px-3 py-2.5 transition-[border-color,transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-md motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300",
          toneBorder,
        )}
        style={{ animationDelay: `${delayMs}ms` }}
      >
        <span
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-lg",
            toneBg,
          )}
        >
          <Icon className={cn("size-4", toneIcon)} aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="truncate text-sm font-semibold leading-tight">
            {action.title}
          </p>
          <p className="truncate text-xs text-muted-foreground">{action.detail}</p>
        </div>
        <ArrowRight
          className="size-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground"
          aria-hidden
        />
      </div>
    </Link>
  );
}
