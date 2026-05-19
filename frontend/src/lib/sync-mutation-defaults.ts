/**
 * QueryClient-level defaults for the global Plaid Sync mutation.
 *
 * Why this lives outside SyncButton:
 *
 * `useMutation` callbacks (``onSuccess``/``onError``) only fire while
 * the hook instance is mounted. SyncButton lives inside AppLayout, and
 * AppLayout is rendered per page (not as a Next route layout) — so
 * navigating mid-sync unmounts the hook, the mutation Promise resolves
 * onto nothing, and the user never sees the result toast. Worse: under
 * some unmount/cleanup paths react-query surfaces a stray rejection as
 * the standard onError path which then fires a "Sync failed." toast on
 * the new page, making it look like every cross-page sync errored.
 *
 * ``setMutationDefaults`` attaches the handlers to the QueryClient
 * itself, not a hook instance. They fire on the mutation result
 * regardless of which component is currently mounted (or whether any
 * is). SyncButton then becomes a thin observer via ``useIsMutating``
 * + the same mutationKey — no local state to lose, no toasts to drop.
 */

import { QueryClient } from "@tanstack/react-query";

import { plaidApi } from "@/lib/api";
import { notify } from "@/lib/notify";

export const SYNC_MUTATION_KEY = ["plaid", "sync"] as const;

/**
 * Register the mutation defaults on the given QueryClient. Idempotent —
 * calling more than once on the same client overwrites the previous
 * registration (which is fine; the handlers are pure functions over
 * the client we already have a reference to).
 */
export function configureSyncMutationDefaults(queryClient: QueryClient): void {
  queryClient.setMutationDefaults([...SYNC_MUTATION_KEY], {
    mutationFn: () => plaidApi.sync(),
    onSuccess: () => {
      // Coarse keys are fine — a Plaid sync touches every surface, so
      // refetching anything tied to backend data is the right move.
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      queryClient.invalidateQueries({ queryKey: ["budgets"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["recurring"] });
      queryClient.invalidateQueries({ queryKey: ["plaid-items"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["insights"] });
      notify.success("Sync complete.");
    },
    onError: (err) => {
      notify.error(err instanceof Error ? err.message : "Sync failed.");
    },
  });
}
