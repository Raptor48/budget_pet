"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/auth-context";
import { AppLayout } from "@/components/layout/app-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { accountsApi, membersApi } from "@/lib/api";
import { NetWorthCard } from "@/components/accounts/net-worth-card";
import { OwnersGrid } from "@/components/accounts/owners-grid";
import { AddAccountMenu } from "@/components/accounts/add-account-menu";

export default function AccountsPage() {
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

  // Cash wallets are now created explicitly via the "Add account" CTA. The
  // previous lazy auto-create had a nasty side effect: deleting your cash
  // wallet caused it to silently re-spawn on the next page load, so the
  // "delete" never visibly stuck.

  const { data: members = [] } = useQuery({
    queryKey: ["members"],
    queryFn: () => membersApi.list(),
  });

  const { user: currentUser } = useAuth();

  if (isLoading) {
    return (
      <AppLayout>
        <div className="space-y-6">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            Accounts
          </p>
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
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            Accounts
          </p>
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
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300">
            Accounts
            {isFetching ? (
              <span className="ml-2 normal-case tracking-normal italic">
                Updating…
              </span>
            ) : null}
          </p>
          <AddAccountMenu />
        </div>

        {accounts.length > 0 && <NetWorthCard accounts={accounts} />}

        {accounts.length === 0 ? (
          <Card className="motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300">
            <CardContent className="space-y-3 py-10 text-center">
              <p className="text-foreground font-medium">No accounts yet</p>
              <p className="text-muted-foreground text-sm">
                Add a cash wallet for manual tracking, or connect your bank to
                pull live balances.
              </p>
              <div className="flex justify-center pt-2">
                <AddAccountMenu />
              </div>
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
