"use client";

import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/auth-context";
import { AppLayout } from "@/components/layout/app-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { accountsApi, membersApi } from "@/lib/api";
import { NetWorthCard } from "@/components/accounts/net-worth-card";
import { OwnersGrid } from "@/components/accounts/owners-grid";

export default function AccountsPage() {
  const queryClient = useQueryClient();

  const {
    data: accounts = [],
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["v2-accounts", "all"],
    queryFn: () => accountsApi.list(false),
  });

  const hasActiveCashWallet = useMemo(
    () => accounts.some((a) => a.is_cash_wallet),
    [accounts],
  );

  // Eagerly ensure there's a cash wallet row for the current user whenever
  // they already have some accounts linked — otherwise their owner column
  // would be missing the "Cash Wallet" section entirely.
  useQuery({
    queryKey: ["accounts", "cash-wallet-ensure"],
    queryFn: async () => {
      const wallet = await accountsApi.cashWallet();
      await queryClient.invalidateQueries({ queryKey: ["v2-accounts", "all"] });
      return wallet;
    },
    enabled: !isLoading && !isError && accounts.length > 0 && !hasActiveCashWallet,
    staleTime: 60_000,
  });

  const { data: members = [] } = useQuery({
    queryKey: ["members"],
    queryFn: () => membersApi.list(),
  });

  const { user: currentUser } = useAuth();

  if (isLoading) {
    return (
      <AppLayout>
        <div className="space-y-6">
          <h1 className="text-3xl font-bold">Accounts</h1>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-32 w-full" />
            ))}
          </div>
        </div>
      </AppLayout>
    );
  }

  if (isError) {
    return (
      <AppLayout>
        <div className="space-y-6">
          <h1 className="text-3xl font-bold">Accounts</h1>
          <Card className="border-destructive/50">
            <CardHeader>
              <CardTitle className="text-destructive">
                Could not load accounts
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground mb-3 text-sm">
                {error instanceof Error ? error.message : "Unknown error"}
              </p>
              <button
                type="button"
                className="text-primary text-sm font-medium underline-offset-4 hover:underline"
                onClick={() => void refetch()}
              >
                Try again
              </button>
            </CardContent>
          </Card>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="space-y-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">Accounts</h1>
            <p className="text-muted-foreground">
              Tap any card to see full details
              {isFetching ? <span className="ml-2 text-xs">Updating…</span> : null}
            </p>
          </div>
        </div>

        {accounts.length > 0 && <NetWorthCard accounts={accounts} />}

        {accounts.length === 0 ? (
          <Card>
            <CardContent className="text-muted-foreground py-10 text-center text-sm">
              No accounts connected yet. Connect a bank in Settings → Bank
              connections.
            </CardContent>
          </Card>
        ) : (
          <OwnersGrid
            accounts={accounts}
            members={members}
            currentUser={currentUser}
          />
        )}
      </div>
    </AppLayout>
  );
}
