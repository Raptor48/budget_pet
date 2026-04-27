"use client";

/**
 * Audit tab — current Sunday session + last 26 weeks of history.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleCheck, CircleDashed, Coffee, Cookie, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { botApi, type AuditSession } from "@/lib/api";
import { notify, onMutationError } from "@/lib/notify";

import { formatDate } from "./bot-helpers";

type AuditPatch = Partial<AuditSession> & { completed?: boolean };

export function BotAuditTab() {
  const qc = useQueryClient();
  const current = useQuery({
    queryKey: ["bot", "audit-current"],
    queryFn: botApi.currentAudit,
  });
  const history = useQuery({
    queryKey: ["bot", "audit-history"],
    queryFn: () => botApi.listAudit(26),
  });

  const update = useMutation({
    mutationFn: ({ weekStart, patch }: { weekStart: string; patch: AuditPatch }) =>
      botApi.updateAudit(weekStart, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "audit-current"] });
      qc.invalidateQueries({ queryKey: ["bot", "audit-history"] });
    },
    onError: onMutationError("Couldn't save the audit session."),
  });

  const [snack, setSnack] = useState("");
  const [tea, setTea] = useState("");
  const [notes, setNotes] = useState("");

  // Hydrate the form once per audit week (re-hydrate only when week_start
  // changes, i.e. the user navigates to a different session). Driving
  // setState from render body deadlocks when the source field is null —
  // null !== "" stays true forever and React #301 fires.
  const weekKey = current.data?.week_start ?? null;
  useEffect(() => {
    if (!current.data) return;
    setSnack(current.data.snack ?? "");
    setTea(current.data.tea_choice ?? "");
    setNotes(current.data.notes ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weekKey]);

  // "Dirty" = the form differs from what's on the server. Drives the Save
  // button enable state so we don't wake the API up for noop writes.
  const dirty = useMemo(() => {
    if (!current.data) return false;
    return (
      (current.data.snack ?? "") !== snack ||
      (current.data.tea_choice ?? "") !== tea ||
      (current.data.notes ?? "") !== notes
    );
  }, [current.data, snack, tea, notes]);

  const submitDraft = async (alsoComplete?: boolean) => {
    if (!current.data) return;
    const patch: AuditPatch = {
      snack,
      tea_choice: tea,
      notes,
    };
    if (alsoComplete !== undefined) patch.completed = alsoComplete;
    await update.mutateAsync({
      weekStart: current.data.week_start,
      patch,
    });
    notify.success(
      alsoComplete === true
        ? "Marked completed."
        : alsoComplete === false
          ? "Marked pending."
          : "Saved.",
    );
  };

  const completed = !!current.data?.completed_at;

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-2 text-base font-semibold">This week</h2>
        {current.isLoading || !current.data ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Week starting {formatDate(current.data.week_start)}</span>
              <span aria-hidden>·</span>
              {completed ? (
                <Badge variant="secondary" className="gap-1">
                  <CircleCheck className="h-3 w-3" />
                  Completed
                </Badge>
              ) : (
                <Badge variant="outline" className="gap-1">
                  <CircleDashed className="h-3 w-3" />
                  Pending
                </Badge>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="snack" className="flex items-center gap-1.5">
                  <Cookie className="h-3.5 w-3.5 text-muted-foreground" />
                  Snack
                </Label>
                <Input
                  id="snack"
                  placeholder="Cheese plate"
                  value={snack}
                  onChange={(e) => setSnack(e.target.value)}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="tea" className="flex items-center gap-1.5">
                  <Coffee className="h-3.5 w-3.5 text-muted-foreground" />
                  Tea
                </Label>
                <Input
                  id="tea"
                  placeholder="Earl Grey"
                  value={tea}
                  onChange={(e) => setTea(e.target.value)}
                />
              </div>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="notes">Notes</Label>
              <textarea
                id="notes"
                rows={3}
                className="w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder="What stood out this week?"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => submitDraft(!completed)}
                disabled={update.isPending}
              >
                {update.isPending && update.variables?.patch.completed !== undefined ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : completed ? (
                  <CircleDashed className="mr-1 h-4 w-4" />
                ) : (
                  <CircleCheck className="mr-1 h-4 w-4" />
                )}
                {completed ? "Mark pending" : "Mark completed"}
              </Button>
              <Button
                onClick={() => submitDraft()}
                disabled={!dirty || update.isPending}
              >
                {update.isPending && update.variables?.patch.completed === undefined ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : (
                  <Check className="mr-1 h-4 w-4" />
                )}
                Save
              </Button>
            </div>
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-base font-semibold">History</h2>
        {history.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : !history.data?.length ? (
          <p className="text-sm text-muted-foreground">No past sessions yet.</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {history.data.map((session) => (
              <li
                key={session.id}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm"
              >
                <div className="min-w-0">
                  <div className="font-medium">
                    {formatDate(session.week_start)}
                    {session.host_username ? ` · ${session.host_username}` : ""}
                  </div>
                  {session.notes ? (
                    <div className="truncate text-xs text-muted-foreground">
                      {session.notes}
                    </div>
                  ) : null}
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  {session.tea_choice ? (
                    <span className="inline-flex items-center gap-1">
                      <Coffee className="h-3.5 w-3.5" />
                      {session.tea_choice}
                    </span>
                  ) : null}
                  {session.snack ? (
                    <span className="inline-flex items-center gap-1">
                      <Cookie className="h-3.5 w-3.5" />
                      {session.snack}
                    </span>
                  ) : null}
                  {session.completed_at ? (
                    <Badge variant="secondary">Completed</Badge>
                  ) : (
                    <Badge variant="outline">Pending</Badge>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
