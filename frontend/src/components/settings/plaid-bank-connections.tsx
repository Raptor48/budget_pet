"use client";

import { useState, useCallback } from "react";
import { usePlaidLink } from "react-plaid-link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Building2, RefreshCw, Trash2, CheckCircle, AlertCircle, Clock
} from "lucide-react";
import { plaidApi } from "@/lib/api";
import { PlaidCategoryMapEntry } from "@/types/api";

// ---------------------------------------------------------------
// Plaid Link button — fetches a link_token then opens Plaid UI
// ---------------------------------------------------------------
function ConnectBankButton({ onSuccess }: { onSuccess: () => void }) {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const { open, ready } = usePlaidLink({
    token: linkToken ?? "",
    onSuccess: async (publicToken, metadata) => {
      try {
        await plaidApi.exchangeToken(
          publicToken,
          metadata.institution?.name ?? undefined
        );
        onSuccess();
      } catch (e) {
        console.error("Failed to exchange Plaid token:", e);
      }
    },
  });

  const handleConnect = useCallback(async () => {
    setLoading(true);
    try {
      const { link_token } = await plaidApi.getLinkToken();
      setLinkToken(link_token);
    } catch (e) {
      console.error("Failed to get link token:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-open Plaid Link once we have a token
  if (linkToken && ready) {
    open();
    setLinkToken(null);
  }

  return (
    <Button onClick={handleConnect} disabled={loading} className="gap-2">
      <Building2 className="h-4 w-4" />
      {loading ? "Connecting..." : "Connect Bank"}
    </Button>
  );
}

// ---------------------------------------------------------------
// Category mapping editor
// ---------------------------------------------------------------
function CategoryMapEditor() {
  const queryClient = useQueryClient();
  const { data: mappings = [], isLoading } = useQuery({
    queryKey: ["plaid-category-map"],
    queryFn: plaidApi.getCategoryMap,
  });

  const [editedMap, setEditedMap] = useState<PlaidCategoryMapEntry[]>([]);
  const [isEditing, setIsEditing] = useState(false);

  const saveMutation = useMutation({
    mutationFn: (m: PlaidCategoryMapEntry[]) => plaidApi.updateCategoryMap(m),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plaid-category-map"] });
      setIsEditing(false);
    },
  });

  const displayMap = isEditing ? editedMap : mappings;

  const addRow = () => {
    setEditedMap([...editedMap, { plaid_category: "", budget_category: "" }]);
  };

  const removeRow = (i: number) => {
    setEditedMap(editedMap.filter((_, idx) => idx !== i));
  };

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading mappings...</p>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Map Plaid categories to your budget categories. Transactions without a mapping
          go to <strong>Uncategorized</strong>.
          {!isEditing && mappings.length === 0 && (
            <span className="block mt-1 italic">
              No mappings yet. Run a sync first — Plaid categories will be discovered automatically.
            </span>
          )}
        </p>
        {!isEditing ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => { setEditedMap([...mappings]); setIsEditing(true); }}
          >
            Edit
          </Button>
        ) : (
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setIsEditing(false)}>Cancel</Button>
            <Button size="sm" onClick={() => saveMutation.mutate(editedMap)} disabled={saveMutation.isPending}>
              Save
            </Button>
          </div>
        )}
      </div>

      {displayMap.length === 0 && !isEditing ? null : (
        <div className="rounded-md border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Plaid Category</th>
                <th className="text-left px-3 py-2 font-medium">Budget Category</th>
                {isEditing && <th className="w-8" />}
              </tr>
            </thead>
            <tbody>
              {displayMap.map((m, i) => (
                <tr key={i} className="border-t">
                  <td className="px-3 py-2 text-muted-foreground">
                    {isEditing ? (
                      <input
                        className="w-full bg-background border rounded px-2 py-1 text-sm"
                        value={editedMap[i]?.plaid_category ?? ""}
                        onChange={(e) => {
                          const updated = [...editedMap];
                          updated[i] = { ...updated[i], plaid_category: e.target.value };
                          setEditedMap(updated);
                        }}
                      />
                    ) : (
                      m.plaid_category
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {isEditing ? (
                      <input
                        className="w-full bg-background border rounded px-2 py-1 text-sm"
                        value={editedMap[i]?.budget_category ?? ""}
                        onChange={(e) => {
                          const updated = [...editedMap];
                          updated[i] = { ...updated[i], budget_category: e.target.value };
                          setEditedMap(updated);
                        }}
                      />
                    ) : (
                      m.budget_category
                    )}
                  </td>
                  {isEditing && (
                    <td className="px-2 py-2">
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-destructive transition-colors text-xs"
                        onClick={() => removeRow(i)}
                        title="Remove row"
                      >
                        ✕
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {isEditing && (
            <div className="border-t px-3 py-2">
              <Button size="sm" variant="ghost" onClick={addRow} className="text-xs h-7">
                + Add row
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// Main component
// ---------------------------------------------------------------
export function PlaidBankConnections() {
  const queryClient = useQueryClient();

  const { data: items = [], isLoading: itemsLoading } = useQuery({
    queryKey: ["plaid-items"],
    queryFn: plaidApi.getItems,
  });

  const { data: syncLog = [] } = useQuery({
    queryKey: ["plaid-sync-log"],
    queryFn: plaidApi.getSyncLog,
  });

  const syncMutation = useMutation({
    mutationFn: plaidApi.syncNow,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plaid-items"] });
      queryClient.invalidateQueries({ queryKey: ["plaid-sync-log"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: plaidApi.deleteItem,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plaid-items"] }),
  });

  const lastSync = syncLog[0];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Building2 className="h-5 w-5" />
          Bank Connections
        </CardTitle>
        <CardDescription>
          Connect your bank via Plaid to automatically import transactions and sync balances.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">

        {/* Connected banks */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Connected Accounts</span>
            <ConnectBankButton onSuccess={() => queryClient.invalidateQueries({ queryKey: ["plaid-items"] })} />
          </div>

          {itemsLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : items.length === 0 ? (
            <Alert>
              <Building2 className="h-4 w-4" />
              <AlertDescription>
                No banks connected yet. Click Connect Bank to link your Chase account.
              </AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-2">
              {items.map((item) => (
                <div key={item.item_id} className="flex items-center justify-between rounded-lg border px-4 py-3">
                  <div className="space-y-0.5">
                    <p className="text-sm font-medium">{item.institution_name ?? "Unknown Bank"}</p>
                    <p className="text-xs text-muted-foreground flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {item.last_synced_at
                        ? `Last synced: ${new Date(item.last_synced_at).toLocaleString()}`
                        : "Never synced"}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive"
                    onClick={() => deleteMutation.mutate(item.item_id)}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>

        <Separator />

        {/* Manual sync */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <p className="text-sm font-medium">Sync Now</p>
            <p className="text-sm text-muted-foreground">
              Manually pull latest transactions, update balances and discover new categories.
              Balance sync matches accounts by name — make sure your card/loan names in Finances match the account name in your bank.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending || items.length === 0}
            className="gap-2"
          >
            <RefreshCw className={`h-4 w-4 ${syncMutation.isPending ? "animate-spin" : ""}`} />
            {syncMutation.isPending ? "Syncing..." : "Sync"}
          </Button>
        </div>

        {/* Last sync result */}
        {syncMutation.data && (
          <div className="space-y-1">
            {syncMutation.data.map((r) => (
              <Alert key={r.item_id} variant={r.status === "ok" ? "default" : "destructive"}>
                {r.status === "ok"
                  ? <CheckCircle className="h-4 w-4" />
                  : <AlertCircle className="h-4 w-4" />}
                <AlertDescription>
                  {r.status === "ok"
                    ? `Synced: +${r.transactions_added} transactions, ${r.balances_updated} balances updated`
                    : `Error: ${r.error_msg}`}
                </AlertDescription>
              </Alert>
            ))}
          </div>
        )}

        {/* Last sync from log */}
        {!syncMutation.data && lastSync && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Badge variant={lastSync.status === "ok" ? "default" : "destructive"} className="text-xs">
              {lastSync.status}
            </Badge>
            Last auto-sync: {new Date(lastSync.synced_at).toLocaleString()} —
            +{lastSync.transactions_added} txn, {lastSync.balances_updated} balances
          </div>
        )}

        <Separator />

        {/* Category mapping */}
        <div className="space-y-3">
          <p className="text-sm font-medium">Category Mapping</p>
          <CategoryMapEditor />
        </div>

      </CardContent>
    </Card>
  );
}
