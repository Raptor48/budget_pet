"use client";

import {
  useIsMutating,
  useMutation,
  useMutationState,
  useQuery,
} from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { Loader2, RefreshCw } from "lucide-react";
import { plaidApi } from "@/lib/api";
import { SYNC_MUTATION_KEY } from "@/lib/sync-mutation-defaults";

/**
 * Global Plaid-sync control. Lives in AppLayout (rendered per page),
 * so the component itself unmounts on cross-page navigation — but the
 * mutation state lives at the QueryClient level via
 * ``setMutationDefaults`` (see ``lib/sync-mutation-defaults.ts``), so
 * the in-flight sync survives the unmount, its result toast still
 * fires on the new page, and a fresh SyncButton instance immediately
 * reflects the in-progress state via ``useIsMutating``.
 *
 * The local ``useMutation`` here exists only to expose ``mutate()`` —
 * its callbacks are deliberately empty because the defaults already
 * handle invalidation + toasts.
 */
export function SyncButton() {
  const plaidItemsQuery = useQuery({
    queryKey: ["plaid-items"],
    queryFn: plaidApi.listItems,
    staleTime: 60_000,
  });

  // No mutationFn or callbacks here — both come from the defaults
  // registered in Providers, so we don't risk drift between the
  // "trigger" surface and the "what happens" surface.
  const mutation = useMutation({ mutationKey: [...SYNC_MUTATION_KEY] });

  // Reflects the GLOBAL state of any sync mutation in flight, including
  // one fired from a previous (now-unmounted) SyncButton instance.
  // ``useIsMutating`` walks the QueryClient cache, not local state, so
  // remounting after navigation sees the same value.
  const inFlight = useIsMutating({ mutationKey: [...SYNC_MUTATION_KEY] }) > 0;

  // Suppress double-click while pending — useIsMutating is the source of
  // truth, mutation.isPending is per-instance and may be stale on remount.
  const handleClick = () => {
    if (inFlight) return;
    mutation.mutate();
  };

  // Defensive: subscribe to the mutation status so React re-renders this
  // component when the global state flips. useIsMutating already does this
  // for the count, but useMutationState makes the dependency explicit and
  // future-proofs against the count-only API ever being optimized away.
  useMutationState({ filters: { mutationKey: [...SYNC_MUTATION_KEY] } });

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
        onClick={handleClick}
        disabled={inFlight}
        aria-label="Sync now"
        className="inline-flex h-7 items-center gap-1 rounded-md border border-border/60 bg-card px-2 text-xs font-medium text-foreground transition-colors hover:border-border hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
      >
        {inFlight ? (
          <Loader2 className="size-3 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="size-3" aria-hidden />
        )}
        <span className="hidden sm:inline">
          {inFlight ? "Syncing…" : "Sync now"}
        </span>
      </button>
    </div>
  );
}
