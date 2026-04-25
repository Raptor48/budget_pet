"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { plaidApi } from "@/lib/api";

/**
 * Compact inline plate that replaces the previous full-width amber banner.
 *
 * The full-width banner was loud and rendered on every authenticated page,
 * which trained users to scroll past it. The new contract: a Settings-icon
 * dot signals the issue globally (lives in the sidebar), and this plate is
 * rendered inline on the Dashboard so users still see actionable copy on
 * the surface where they triage. It auto-hides when nothing's broken.
 */
export function PlaidAttentionPlate() {
  const { data: items = [] } = useQuery({
    queryKey: ["plaid-items"],
    queryFn: plaidApi.listItems,
    staleTime: 60_000,
  });

  if (!items.some((i) => i.item_login_required)) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-500/40 bg-amber-500/[0.06] px-3 py-2 text-sm motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-top-1 motion-safe:duration-300 dark:border-amber-400/30 dark:bg-amber-400/[0.04]">
      <AlertTriangle
        className="size-4 shrink-0 text-amber-600 dark:text-amber-400"
        aria-hidden
      />
      <p className="flex-1 leading-snug text-foreground/90">
        <span className="font-medium">A bank connection needs attention</span>
        <span className="hidden text-muted-foreground sm:inline">
          {" — sync cannot complete until you reconnect."}
        </span>
      </p>
      <Button
        asChild
        size="sm"
        variant="ghost"
        className="h-7 shrink-0 gap-1 px-2 text-xs text-amber-700 hover:bg-amber-500/15 hover:text-amber-700 dark:text-amber-300 dark:hover:bg-amber-400/15 dark:hover:text-amber-200"
      >
        <Link href="/settings#settings-bank-connections">
          Fix in Settings
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      </Button>
    </div>
  );
}
