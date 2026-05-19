"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { Loader2, RefreshCw } from "lucide-react";
import { plaidApi } from "@/lib/api";
import { notify } from "@/lib/notify";

/**
 * Global Plaid-sync control. Lives in AppLayout so the mutation state
 * (Syncing… spinner) survives page navigation — historically the button
 * was scoped to the Dashboard component and the spinner vanished the
 * moment the user clicked away to Transactions, leaving them with no
 * feedback while the request was still in flight.
 *
 * Queries to invalidate match what every page's react-query cache uses;
 * coarse keys are fine here because a Plaid sync touches every surface.
 */
export function SyncButton() {
  const queryClient = useQueryClient();

  const plaidItemsQuery = useQuery({
    queryKey: ["plaid-items"],
    queryFn: plaidApi.listItems,
    staleTime: 60_000,
  });

  const syncMutation = useMutation({
    mutationFn: () => plaidApi.sync(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      queryClient.invalidateQueries({ queryKey: ["budgets"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["recurring"] });
      queryClient.invalidateQueries({ queryKey: ["plaid-items"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["insights"] });
      notify.success("Sync complete.");
    },
    onError: (err) =>
      notify.error(err instanceof Error ? err.message : "Sync failed."),
  });

  const plaidItems = plaidItemsQuery.data ?? [];
  const lastSyncedAt = plaidItems
    .map((i) => i.last_synced_at)
    .filter((d): d is string => Boolean(d))
    .sort()
    .pop();
  const lastSyncedRelative = lastSyncedAt
    ? formatDistanceToNow(new Date(lastSyncedAt), { addSuffix: true })
    : null;

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      {lastSyncedRelative ? (
        <span className="hidden leading-none sm:inline">
          Last synced{" "}
          <span className="font-medium text-foreground">{lastSyncedRelative}</span>
        </span>
      ) : (
        <span className="hidden leading-none italic sm:inline">Not synced yet</span>
      )}
      <button
        type="button"
        onClick={() => syncMutation.mutate()}
        disabled={syncMutation.isPending}
        aria-label="Sync now"
        className="inline-flex h-7 items-center gap-1 rounded-md border border-border/60 bg-card px-2 text-xs font-medium text-foreground transition-colors hover:border-border hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
      >
        {syncMutation.isPending ? (
          <Loader2 className="size-3 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="size-3" aria-hidden />
        )}
        <span className="hidden sm:inline">
          {syncMutation.isPending ? "Syncing…" : "Sync now"}
        </span>
      </button>
    </div>
  );
}
