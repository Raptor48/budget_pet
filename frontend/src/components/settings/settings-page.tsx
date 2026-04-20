"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { plaidApi } from "@/lib/api";
import { PlaidBankConnections } from "./plaid-bank-connections";
import { SystemStatusBar } from "./system-status-bar";
import {
  Settings as SettingsIcon,
  Database,
  Download,
  Loader2,
  Trash2,
  AlertTriangle,
  CheckCircle,
} from "lucide-react";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [sandboxDialogOpen, setSandboxDialogOpen] = useState(false);
  const [sandboxResult, setSandboxResult] = useState<{
    transactions_deleted: number;
    accounts_deleted: number;
    recurring_streams_deleted: number;
    net_worth_snapshots_deleted: number;
    plaid_items_deleted: number;
  } | null>(null);

  const deleteSandboxMutation = useMutation({
    mutationFn: plaidApi.deleteSandboxData,
    onSuccess: (data) => {
      setSandboxDialogOpen(false);
      setSandboxResult(data);
      // Invalidate all data queries since data was deleted
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["recurring"] });
      queryClient.invalidateQueries({ queryKey: ["plaid-items"] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Settings</h1>
          <p className="text-muted-foreground">Configure your budget management preferences</p>
        </div>
        <Badge variant="secondary" className="gap-2">
          <SettingsIcon className="h-4 w-4" />
          V2.2
        </Badge>
      </div>

      {/* Compact statusbar: System Status (left) + Appearance (right) */}
      <SystemStatusBar />

      {/* Bank Connections (Plaid) — includes the autosync schedule + webhook toggle */}
      <PlaidBankConnections />

      {/* Data Management */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Data Management
          </CardTitle>
          <CardDescription>Backup and manage your budget data</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-base">Export Data</Label>
              <p className="text-sm text-muted-foreground">Download your transactions as CSV</p>
            </div>
            <Button variant="outline" size="sm" className="gap-2">
              <Download className="h-4 w-4" />
              Export
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Danger Zone */}
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-5 w-5" />
            Danger Zone
          </CardTitle>
          <CardDescription>
            Irreversible actions. Read carefully before proceeding.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Success result after deletion */}
          {sandboxResult && (
            <Alert className="border-emerald-500/40 bg-emerald-500/5">
              <CheckCircle className="h-4 w-4 text-emerald-600" />
              <AlertDescription className="space-y-1">
                <p className="font-medium text-emerald-700 dark:text-emerald-400">
                  Sandbox data deleted successfully
                </p>
                <ul className="text-xs text-muted-foreground space-y-0.5 mt-1">
                  <li>• {sandboxResult.transactions_deleted} transactions removed</li>
                  <li>• {sandboxResult.accounts_deleted} accounts removed</li>
                  <li>• {sandboxResult.recurring_streams_deleted} recurring streams removed</li>
                  <li>• {sandboxResult.net_worth_snapshots_deleted} net worth snapshots cleared</li>
                  <li>• {sandboxResult.plaid_items_deleted} Plaid connections removed</li>
                </ul>
              </AlertDescription>
            </Alert>
          )}

          <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <p className="text-sm font-medium">Delete Test Data</p>
                <p className="text-xs text-muted-foreground max-w-sm">
                  Removes all data imported from Plaid <strong>sandbox</strong> environment —
                  transactions, accounts, recurring streams, net worth history, and sandbox
                  bank connections. Manual transactions and your settings are preserved.
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="shrink-0 border-destructive/50 text-destructive hover:bg-destructive/10 hover:border-destructive gap-2"
                onClick={() => {
                  setSandboxResult(null);
                  setSandboxDialogOpen(true);
                }}
              >
                <Trash2 className="h-4 w-4" />
                Delete Test Data
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Sandbox delete confirmation dialog */}
      <Dialog open={sandboxDialogOpen} onOpenChange={setSandboxDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              Delete All Sandbox Data?
            </DialogTitle>
            <DialogDescription className="space-y-3 pt-1">
              <p>This will permanently delete:</p>
              <ul className="text-sm space-y-1 pl-4 list-disc text-foreground/80">
                <li>All transactions from Plaid <strong>sandbox</strong></li>
                <li>All accounts and cards synced from sandbox</li>
                <li>All recurring streams</li>
                <li>All net worth history snapshots</li>
                <li>All sandbox bank connections</li>
              </ul>
              <p className="text-sm font-medium text-foreground">
                What will NOT be deleted:
              </p>
              <ul className="text-sm space-y-1 pl-4 list-disc text-muted-foreground">
                <li>Manual transactions</li>
                <li>Categories, tags, budgets</li>
                <li>User accounts and settings</li>
              </ul>
              <p className="text-sm text-destructive font-medium">
                This action cannot be undone.
              </p>
            </DialogDescription>
          </DialogHeader>
          {deleteSandboxMutation.isError && (
            <Alert variant="destructive">
              <AlertDescription>
                {deleteSandboxMutation.error instanceof Error
                  ? deleteSandboxMutation.error.message
                  : "Failed to delete sandbox data. Please try again."}
              </AlertDescription>
            </Alert>
          )}
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => setSandboxDialogOpen(false)}
              disabled={deleteSandboxMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteSandboxMutation.mutate()}
              disabled={deleteSandboxMutation.isPending}
              className="gap-2"
            >
              {deleteSandboxMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Deleting…
                </>
              ) : (
                <>
                  <Trash2 className="h-4 w-4" />
                  Yes, Delete Test Data
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
