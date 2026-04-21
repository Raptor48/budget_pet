"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { plaidApi } from "@/lib/api";

/**
 * Global notice when any Plaid Item needs re-auth (same flag as Settings → Bank connections).
 * Hidden on the main Settings page where the in-card alert already appears.
 */
export function PlaidAttentionBanner() {
  const pathname = usePathname();
  const { data: items = [] } = useQuery({
    queryKey: ["plaid-items"],
    queryFn: plaidApi.listItems,
    staleTime: 60_000,
  });

  if (pathname === "/settings") {
    return null;
  }

  if (!items.some((i) => i.item_login_required)) {
    return null;
  }

  return (
    <div className="mb-6">
      <Alert
        role="status"
        className="border-amber-500/70 bg-gradient-to-r from-amber-500/15 via-amber-500/10 to-transparent text-amber-950 shadow-sm dark:border-amber-400/50 dark:from-amber-950/50 dark:via-amber-950/30 dark:to-transparent dark:text-amber-50"
      >
        <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
        <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <div className="space-y-1 text-sm leading-snug">
            <p className="font-semibold text-foreground dark:text-amber-50">
              A bank connection needs attention
            </p>
            <p className="text-muted-foreground dark:text-amber-100/85">
              Open Plaid Link from Settings to refresh credentials — sync cannot complete until you do.
            </p>
          </div>
          <Button
            asChild
            size="sm"
            className="shrink-0 border-amber-600/40 bg-amber-600/15 text-amber-950 hover:bg-amber-600/25 dark:border-amber-400/40 dark:bg-amber-400/10 dark:text-amber-50 dark:hover:bg-amber-400/20"
          >
            <Link href="/settings#settings-bank-connections">Fix in Settings</Link>
          </Button>
        </AlertDescription>
      </Alert>
    </div>
  );
}
