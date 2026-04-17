"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout/app-layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";
import { recurringApi, categoriesApi, accountsApi, ApiError } from "@/lib/api";
import { PlaidTxnAmount } from "@/components/ui/plaid-txn-amount";
import { cn } from "@/lib/utils";
import type { RecurringStream } from "@/types/v2";
import { Pencil, Check, X, Plus } from "lucide-react";

function formatFrequency(f: string | null): string {
  if (!f) return "—";
  return f.replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

const STATUS_LABELS: Record<string, string> = {
  MATURE: "Active",
  EARLY_DETECTION: "Newly Detected",
  TOMBSTONED: "Stopped",
  MANUAL: "Manual",
};

function friendlyStatus(status: string | null): string {
  if (!status) return "—";
  return STATUS_LABELS[status] ?? status;
}

function statusBadgeClass(status: string | null): string {
  switch (status) {
    case "MATURE":
      return "border-emerald-600/40 bg-emerald-600/15 text-emerald-700 dark:text-emerald-300";
    case "EARLY_DETECTION":
      return "border-amber-500/50 bg-amber-500/15 text-amber-800 dark:text-amber-200";
    case "TOMBSTONED":
      return "border-muted-foreground/30 bg-muted text-muted-foreground";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

function parsePriceChangePct(raw: string | null): number | null {
  if (raw == null || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function annualCostCents(stream: RecurringStream): number | null {
  if (stream.direction !== "outflow") return null;
  if (stream.frequency !== "MONTHLY") return null;
  if (stream.average_amount_cents == null) return null;
  return stream.average_amount_cents * 12;
}

export default function RecurringPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const streamHighlight = searchParams.get("stream");
  const [direction, setDirection] = useState<"outflow" | "inflow">("outflow");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftLabel, setDraftLabel] = useState("");
  const [draftCategoryId, setDraftCategoryId] = useState<string>("none");
  const [createOpen, setCreateOpen] = useState(false);
  const [cAccountId, setCAccountId] = useState("");
  const [cDesc, setCDesc] = useState("");
  const [cFreq, setCFreq] = useState("MONTHLY");
  const [cAmount, setCAmount] = useState("");

  const streamsQuery = useQuery({
    queryKey: ["recurring", "streams", direction, true],
    queryFn: () => recurringApi.list(direction, true),
  });

  const priceChangesQuery = useQuery({
    queryKey: ["recurring", "price-changes"],
    queryFn: () => recurringApi.getPriceChanges(),
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
  });

  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => accountsApi.list(true),
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const account_id = Number(cAccountId);
      const average_amount_cents = Math.round(Number.parseFloat(cAmount) * 100);
      if (!Number.isFinite(account_id) || account_id <= 0) {
        return Promise.reject(new Error("Choose an account."));
      }
      if (!cDesc.trim()) return Promise.reject(new Error("Enter a description."));
      if (!Number.isFinite(average_amount_cents) || average_amount_cents <= 0) {
        return Promise.reject(new Error("Enter a positive amount."));
      }
      return recurringApi.create({
        account_id,
        direction,
        description: cDesc.trim(),
        frequency: cFreq,
        average_amount_cents,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recurring"] });
      setCreateOpen(false);
      setCAccountId("");
      setCDesc("");
      setCAmount("");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: number;
      payload: { user_label?: string; category_id?: number | null };
    }) => recurringApi.update(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recurring"] });
      setEditingId(null);
    },
  });

  const streams = useMemo(() => streamsQuery.data ?? [], [streamsQuery.data]);

  useEffect(() => {
    if (!streamHighlight || streams.length === 0) return;
    const id = Number(streamHighlight);
    if (!Number.isFinite(id)) return;
    const el = document.getElementById(`recurring-row-${id}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      window.setTimeout(() => {
        if (typeof window !== "undefined" && window.history?.replaceState) {
          window.history.replaceState(null, "", "/recurring");
        }
      }, 400);
    }
  }, [streamHighlight, streams]);
  const categories = categoriesQuery.data ?? [];
  const priceAlerts = useMemo(() => priceChangesQuery.data ?? [], [priceChangesQuery.data]);

  const priceAlertIds = useMemo(
    () => new Set(priceAlerts.map((s) => s.id)),
    [priceAlerts],
  );

  const errorMessage =
    streamsQuery.error instanceof ApiError
      ? streamsQuery.error.message
      : streamsQuery.error instanceof Error
        ? streamsQuery.error.message
        : null;

  const startEdit = (row: RecurringStream) => {
    setEditingId(row.id);
    setDraftLabel(row.user_label ?? "");
    setDraftCategoryId(row.category_id != null ? String(row.category_id) : "none");
  };

  const cancelEdit = () => {
    setEditingId(null);
    updateMutation.reset();
  };

  const saveEdit = (id: number) => {
    const trimmed = draftLabel.trim();
    updateMutation.mutate({
      id,
      payload: {
        // Empty string clears label; null is omitted by FastAPI exclude_none and would not update.
        user_label: trimmed.length ? trimmed : "",
        category_id: draftCategoryId === "none" ? null : Number(draftCategoryId),
      },
    });
  };

  const renderTable = (rows: RecurringStream[]) => (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Description</TableHead>
            <TableHead>Frequency</TableHead>
            <TableHead className="text-right">Avg</TableHead>
            <TableHead className="text-right">Last</TableHead>
            <TableHead>PFC</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Annual (est.)</TableHead>
            <TableHead className="w-[140px]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={8} className="text-muted-foreground h-24 text-center">
                No recurring streams for this tab.
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => {
              const title = row.user_label?.trim() || row.description || row.merchant_name || "—";
              const pct = parsePriceChangePct(row.price_change_pct);
              const showPriceWarning = pct != null && pct > 10;
              const annual = annualCostCents(row);
              const isEditing = editingId === row.id;

                return (
                <TableRow
                  key={row.id}
                  id={`recurring-row-${row.id}`}
                  className={cn(
                    streamHighlight === String(row.id) && "ring-2 ring-primary ring-offset-2 ring-offset-background",
                  )}
                >
                  <TableCell className="max-w-[220px]">
                    {isEditing ? (
                      <div className="flex flex-col gap-2">
                        <Label className="sr-only" htmlFor={`label-${row.id}`}>
                          Label
                        </Label>
                        <Input
                          id={`label-${row.id}`}
                          value={draftLabel}
                          onChange={(e) => setDraftLabel(e.target.value)}
                          placeholder="Custom label"
                        />
                        <Label className="sr-only" htmlFor={`cat-${row.id}`}>
                          Category
                        </Label>
                        <Select value={draftCategoryId} onValueChange={setDraftCategoryId}>
                          <SelectTrigger id={`cat-${row.id}`} className="w-full min-w-[12rem]">
                            <SelectValue placeholder="Category" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">Uncategorized</SelectItem>
                            {categories.map((c) => (
                              <SelectItem key={c.id} value={String(c.id)}>
                                {c.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-1">
                        <span className="font-medium leading-tight">{title}</span>
                        {row.user_label?.trim() && row.description !== row.user_label ? (
                          <span className="text-muted-foreground text-xs">{row.description}</span>
                        ) : null}
                        <div className="flex flex-wrap gap-1">
                          {showPriceWarning ? (
                            <Badge
                              className="border-orange-500/60 bg-orange-500/15 text-orange-800 dark:text-orange-200"
                              variant="outline"
                            >
                              ⚠ Price changed {pct!.toFixed(0)}%
                            </Badge>
                          ) : null}
                          {priceAlertIds.has(row.id) && !showPriceWarning ? (
                            <Badge variant="outline" className="text-xs">
                              Price watch
                            </Badge>
                          ) : null}
                        </div>
                      </div>
                    )}
                  </TableCell>
                  <TableCell>{formatFrequency(row.frequency)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    <PlaidTxnAmount cents={row.average_amount_cents ?? 0} size="inherit" tone="flow" />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    <PlaidTxnAmount cents={row.last_amount_cents ?? 0} size="inherit" tone="flow" />
                  </TableCell>
                  <TableCell>
                    {row.pfc_primary ? (
                      <Badge variant="secondary" className="max-w-[160px] truncate font-normal">
                        {row.pfc_primary}
                      </Badge>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={statusBadgeClass(row.status)}>
                      {friendlyStatus(row.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {annual != null ? <PlaidTxnAmount cents={annual} size="inherit" tone="flow" /> : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    {isEditing ? (
                      <div className="flex justify-end gap-1">
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          onClick={() => saveEdit(row.id)}
                          disabled={updateMutation.isPending}
                          aria-label="Save"
                        >
                          <Check className="size-4" />
                        </Button>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          onClick={cancelEdit}
                          disabled={updateMutation.isPending}
                          aria-label="Cancel"
                        >
                          <X className="size-4" />
                        </Button>
                      </div>
                    ) : (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => startEdit(row)}
                        disabled={editingId != null && editingId !== row.id}
                      >
                        <Pencil className="size-3.5" />
                        Edit
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </div>
  );

  return (
    <AppLayout>
      <TooltipProvider>
        <div className="space-y-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">Recurring</h1>
              <p className="text-muted-foreground text-sm">
                Subscriptions and recurring inflows synced from your bank. Add manual bills that behave like Plaid streams.
              </p>
            </div>
            <button
              type="button"
              className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              onClick={() => {
                createMutation.reset();
                setCreateOpen(true);
              }}
            >
              <Plus className="size-4" />
              Add manual recurring
            </button>
          </div>

          {priceAlerts.length > 0 ? (
            <Card className="border-orange-500/40 bg-orange-500/5">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Price changes</CardTitle>
                <CardDescription>
                  {priceAlerts.length} stream{priceAlerts.length === 1 ? "" : "s"} from{" "}
                  <code className="text-xs">/api/recurring/price-changes</code>
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {priceAlerts.map((s) => (
                  <Tooltip key={s.id}>
                    <TooltipTrigger asChild>
                      <Badge variant="outline" className="max-w-[240px] cursor-default truncate">
                        {s.user_label?.trim() || s.description}
                        {parsePriceChangePct(s.price_change_pct) != null
                          ? ` · ${parsePriceChangePct(s.price_change_pct)!.toFixed(0)}%`
                          : ""}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent>{s.description}</TooltipContent>
                  </Tooltip>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {errorMessage ? (
            <p className="text-destructive text-sm" role="alert">
              {errorMessage}
            </p>
          ) : null}

          {updateMutation.isError ? (
            <p className="text-destructive text-sm" role="alert">
              {updateMutation.error instanceof ApiError
                ? updateMutation.error.message
                : "Failed to update stream."}
            </p>
          ) : null}

          <Tabs
            value={direction === "outflow" ? "out" : "in"}
            onValueChange={(v) => setDirection(v === "out" ? "outflow" : "inflow")}
          >
            <TabsList>
              <TabsTrigger value="out">Outflows</TabsTrigger>
              <TabsTrigger value="in">Inflows</TabsTrigger>
            </TabsList>
            <Separator className="my-4" />
            <TabsContent value="out" className="space-y-4">
              {streamsQuery.isLoading ? (
                <p className="text-muted-foreground text-sm">Loading…</p>
              ) : (
                <div className="overflow-x-auto">{renderTable(direction === "outflow" ? streams : [])}</div>
              )}
            </TabsContent>
            <TabsContent value="in" className="space-y-4">
              {streamsQuery.isLoading ? (
                <p className="text-muted-foreground text-sm">Loading…</p>
              ) : (
                <div className="overflow-x-auto">{renderTable(direction === "inflow" ? streams : [])}</div>
              )}
            </TabsContent>
          </Tabs>

          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add manual recurring</DialogTitle>
                <DialogDescription>
                  Creates a stream in the same list as Plaid data. Plaid sync will not overwrite it.
                </DialogDescription>
              </DialogHeader>
              <div className="grid gap-3 py-2">
                <div className="grid gap-2">
                  <Label>Direction (tab)</Label>
                  <p className="text-muted-foreground text-xs">Uses the current tab: {direction}.</p>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="mr-acct">Account</Label>
                  <Select value={cAccountId} onValueChange={setCAccountId}>
                    <SelectTrigger id="mr-acct">
                      <SelectValue placeholder="Select account" />
                    </SelectTrigger>
                    <SelectContent>
                      {(accountsQuery.data ?? []).map((a) => (
                        <SelectItem key={a.id} value={String(a.id)}>
                          {a.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="mr-desc">Description</Label>
                  <Input id="mr-desc" value={cDesc} onChange={(e) => setCDesc(e.target.value)} maxLength={200} />
                </div>
                <div className="grid gap-2">
                  <Label>Frequency</Label>
                  <Select value={cFreq} onValueChange={setCFreq}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {["WEEKLY", "BIWEEKLY", "SEMI_MONTHLY", "MONTHLY", "ANNUALLY", "UNKNOWN"].map((f) => (
                        <SelectItem key={f} value={f}>
                          {f.replaceAll("_", " ")}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="mr-amt">Amount (USD, per period)</Label>
                  <Input id="mr-amt" inputMode="decimal" placeholder="e.g. 49.99" value={cAmount} onChange={(e) => setCAmount(e.target.value)} />
                </div>
                {createMutation.isError ? (
                  <p className="text-destructive text-sm">
                    {createMutation.error instanceof Error ? createMutation.error.message : "Could not create."}
                  </p>
                ) : null}
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>
                  Cancel
                </Button>
                <Button type="button" disabled={createMutation.isPending} onClick={() => createMutation.mutate()}>
                  Save
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </TooltipProvider>
    </AppLayout>
  );
}
