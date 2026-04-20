"use client";

import { useMemo } from "react";
import type { Account, Member } from "@/types/v2";
import { OwnerColumn } from "./owner-column";
import { isCashWalletShape } from "./helpers";

type OwnerGroup = {
  id: number | "unassigned";
  name: string;
  accounts: Account[];
};

/**
 * Build one group per resolved owner plus an "Unassigned" group for any
 * accounts the user didn't tag. We seed groups from the members list so
 * users without accounts still render an (empty-hidden) slot in the grid.
 */
function groupAccountsByOwner(
  accounts: Account[],
  members: Member[],
): { owners: OwnerGroup[]; unassigned: Account[] } {
  const visible = accounts.filter(
    (a) => !isCashWalletShape(a) || a.is_cash_wallet,
  );

  const owners: OwnerGroup[] = members.map((m) => ({
    id: m.id,
    name: m.username,
    accounts: [],
  }));
  const byId = new Map<number, OwnerGroup>();
  for (const o of owners) if (typeof o.id === "number") byId.set(o.id, o);

  const unassigned: Account[] = [];
  for (const a of visible) {
    if (a.user_id != null && byId.has(a.user_id)) {
      byId.get(a.user_id)!.accounts.push(a);
    } else if (a.user_id == null && a.owner_username) {
      // Plaid has an owner name but no member match yet — stick it under
      // a synthesised owner row so it stays visible.
      let synthetic = owners.find(
        (o) => o.name === a.owner_username && o.id === "unassigned",
      );
      if (!synthetic) {
        synthetic = {
          id: "unassigned",
          name: a.owner_username,
          accounts: [],
        };
        owners.push(synthetic);
      }
      synthetic.accounts.push(a);
    } else {
      unassigned.push(a);
    }
  }

  return {
    owners: owners.filter((o) => o.accounts.length > 0),
    unassigned,
  };
}

/**
 * Top-level layout for the Accounts page. Renders each owner as a column
 * (cards on top → tiles below) with an "Unassigned" section underneath
 * when present. Grid column count adapts to the number of owners.
 */
export function OwnersGrid({
  accounts,
  members,
  currentUser,
}: {
  accounts: Account[];
  members: Member[];
  currentUser: { is_owner: boolean } | null;
}) {
  const { owners, unassigned } = useMemo(
    () => groupAccountsByOwner(accounts, members),
    [accounts, members],
  );

  const ownerCount = owners.length;
  // Tailwind's JIT can't see xl:grid-cols-${n} at build time, so we map
  // the known cases to static class strings.
  const gridClass =
    ownerCount <= 1
      ? "grid grid-cols-1 gap-5"
      : ownerCount === 2
        ? "grid grid-cols-1 gap-5 md:grid-cols-2"
        : ownerCount === 3
          ? "grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3"
          : "grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4";

  return (
    <div className="space-y-6">
      {ownerCount > 0 && (
        <div className={gridClass}>
          {owners.map((o) => (
            <OwnerColumn
              key={String(o.id)}
              name={o.name}
              accounts={o.accounts}
              members={members}
              currentUser={currentUser}
            />
          ))}
        </div>
      )}

      {unassigned.length > 0 && (
        <OwnerColumn
          name="Unassigned"
          accounts={unassigned}
          members={members}
          currentUser={currentUser}
          isUnassigned
        />
      )}
    </div>
  );
}
