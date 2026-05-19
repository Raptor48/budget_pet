"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/contexts/auth-context";
import { configureSyncMutationDefaults } from "@/lib/sync-mutation-defaults";

interface ProvidersProps {
  children: React.ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  // ``useState(() => ...)`` so the QueryClient is created exactly once per
  // component instance instead of on every Providers re-render. Without
  // this guard, any future re-render of Providers (e.g. from an outer
  // context flipping) would throw away every cached query + every
  // in-flight mutation. The pattern is the canonical react-query
  // boilerplate for the App Router; ours had `new QueryClient(...)` in
  // the render body, a real timebomb if Providers ever became reactive.
  //
  // We also register mutation defaults for the global Plaid sync so its
  // success/error toasts fire even when SyncButton unmounts mid-flight
  // (which it does on every cross-page navigation today). See
  // ``lib/sync-mutation-defaults.ts`` for the why.
  const [queryClient] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 1000 * 60 * 5, // 5 minutes
          retry: 1,
        },
      },
    });
    configureSyncMutationDefaults(qc);
    return qc;
  });

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        {children}
      </AuthProvider>
    </QueryClientProvider>
  );
}
