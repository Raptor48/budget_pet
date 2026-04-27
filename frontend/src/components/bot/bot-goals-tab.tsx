"use client";

/**
 * Goals tab — net-worth milestones + active streaks.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  CheckCircle2,
  Flame,
  Loader2,
  Plus,
  Target,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { botApi } from "@/lib/api";
import { confirm, notify, onMutationError } from "@/lib/notify";

import { formatCents, formatDate } from "./bot-helpers";

export function BotGoalsTab() {
  const qc = useQueryClient();
  const milestones = useQuery({
    queryKey: ["bot", "milestones"],
    queryFn: botApi.listMilestones,
  });
  const streaks = useQuery({
    queryKey: ["bot", "streaks"],
    queryFn: botApi.listStreaks,
  });

  const add = useMutation({
    mutationFn: ({ amount, label }: { amount: number; label?: string | null }) =>
      botApi.addMilestone(amount, label),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "milestones"] });
      notify.success("Milestone added.");
    },
    onError: onMutationError("Couldn't add that milestone."),
  });
  const drop = useMutation({
    mutationFn: (id: number) => botApi.deleteMilestone(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "milestones"] });
      notify.success("Milestone removed.");
    },
    onError: onMutationError("Couldn't remove that milestone."),
  });

  const [draft, setDraft] = useState({ amount: "", label: "" });

  // Validate the amount client-side so the Add button doesn't pretend to
  // accept "abc" then silently swallow the click.
  const parsedCents = useMemo(() => {
    const n = Number(draft.amount.replace(/[$,\s]/g, ""));
    if (!Number.isFinite(n) || n <= 0) return null;
    return Math.round(n * 100);
  }, [draft.amount]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (parsedCents == null) return;
    add.mutate({ amount: parsedCents, label: draft.label.trim() || null });
    setDraft({ amount: "", label: "" });
  };

  const requestDrop = async (id: number, label: string | null | undefined, amount: number) => {
    const ok = await confirm({
      title: "Remove milestone?",
      description: `${label || formatCents(amount)} — past celebrations stay in your history.`,
      destructive: true,
      confirmLabel: "Remove",
    });
    if (ok) drop.mutate(id);
  };

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-1 flex items-center gap-2 text-base font-semibold">
          <Target className="h-4 w-4 text-muted-foreground" />
          Net-worth milestones
        </h2>
        <p className="mb-3 text-sm text-muted-foreground">
          The bot pings you in the morning brief the first time net worth crosses
          each threshold. Reached milestones stay listed for posterity.
        </p>

        {milestones.isLoading ? (
          <ul className="mb-3 divide-y rounded-md border">
            {Array.from({ length: 3 }).map((_, i) => (
              <li key={i} className="flex items-center justify-between px-4 py-3">
                <Skeleton className="h-4 w-44" />
                <Skeleton className="h-7 w-16" />
              </li>
            ))}
          </ul>
        ) : !milestones.data?.length ? (
          <div className="mb-3 grid place-items-center rounded-md border border-dashed py-8 text-center">
            <Target className="mb-2 h-6 w-6 text-muted-foreground" aria-hidden />
            <p className="text-sm text-muted-foreground">
              No milestones yet — add your first one below.
            </p>
          </div>
        ) : (
          <ul className="mb-3 divide-y rounded-md border">
            {milestones.data.map((m) => {
              const isPending = drop.isPending && drop.variables === m.id;
              return (
                <li
                  key={m.id}
                  className={cn(
                    "flex items-center justify-between gap-3 px-4 py-3 text-sm transition-colors",
                    "hover:bg-muted/40",
                    m.reached_at &&
                      "bg-gradient-to-r from-emerald-500/5 to-transparent",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "grid h-7 w-7 place-items-center rounded-md",
                        m.reached_at
                          ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                          : "bg-muted text-muted-foreground",
                      )}
                    >
                      {m.reached_at ? (
                        <CheckCircle2 className="h-3.5 w-3.5" />
                      ) : (
                        <Target className="h-3.5 w-3.5" />
                      )}
                    </span>
                    <span className="font-medium">{formatCents(m.threshold_cents)}</span>
                    {m.label ? (
                      <span className="text-muted-foreground">— {m.label}</span>
                    ) : null}
                    {m.reached_at ? (
                      <Badge variant="secondary" className="ml-1">
                        Reached {formatDate(m.reached_at)}
                      </Badge>
                    ) : null}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      requestDrop(m.id, m.label, m.threshold_cents)
                    }
                    disabled={isPending}
                    title="Remove milestone"
                  >
                    {isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin text-destructive" />
                    ) : (
                      <Trash2 className="h-4 w-4 text-destructive" />
                    )}
                    <span className="sr-only">Remove</span>
                  </Button>
                </li>
              );
            })}
          </ul>
        )}

        <form
          onSubmit={submit}
          className="grid gap-3 rounded-md border p-4 sm:grid-cols-[140px,1fr,auto]"
        >
          <div className="grid gap-1">
            <Label htmlFor="amount">Amount ($)</Label>
            <Input
              id="amount"
              inputMode="numeric"
              placeholder="100000"
              value={draft.amount}
              onChange={(e) => setDraft((d) => ({ ...d, amount: e.target.value }))}
              aria-invalid={draft.amount !== "" && parsedCents == null}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="label">Label (optional)</Label>
            <Input
              id="label"
              placeholder="Six-figure milestone"
              value={draft.label}
              onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))}
            />
          </div>
          <Button
            type="submit"
            disabled={add.isPending || parsedCents == null}
            className="self-end transition-transform active:scale-95"
          >
            {add.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-1 h-4 w-4" />
            )}
            Add milestone
          </Button>
        </form>
      </section>

      <Separator />

      <section>
        <h2 className="mb-3 flex items-center gap-2 text-base font-semibold">
          <Flame className="h-4 w-4 text-muted-foreground" />
          Streaks
        </h2>
        {streaks.isLoading ? (
          <ul className="divide-y rounded-md border">
            {Array.from({ length: 2 }).map((_, i) => (
              <li key={i} className="flex items-center justify-between px-4 py-3">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-24" />
              </li>
            ))}
          </ul>
        ) : !streaks.data?.length ? (
          <div className="grid place-items-center rounded-md border border-dashed py-8 text-center">
            <Activity className="mb-2 h-6 w-6 text-muted-foreground" aria-hidden />
            <p className="text-sm text-muted-foreground">
              No streaks yet — finish an audit ritual to start one.
            </p>
          </div>
        ) : (
          <ul className="divide-y rounded-md border">
            {streaks.data.map((s) => {
              const active = s.current_count > 0;
              return (
                <li
                  key={s.streak_type}
                  className="flex items-center justify-between gap-2 px-4 py-3 text-sm transition-colors hover:bg-muted/40"
                >
                  <div className="flex items-center gap-2">
                    <Flame
                      className={cn(
                        "h-4 w-4 transition-colors",
                        active ? "text-orange-500" : "text-muted-foreground/50",
                      )}
                    />
                    <span className="font-medium">{s.label}</span>
                  </div>
                  <span className="text-muted-foreground">
                    <span
                      className={cn(
                        "font-semibold",
                        active ? "text-foreground" : "text-muted-foreground",
                      )}
                    >
                      {s.current_count}
                    </span>{" "}
                    now · best {s.longest_count}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
