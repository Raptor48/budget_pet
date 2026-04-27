"use client";

/**
 * Goals tab — net-worth milestones + active streaks.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { botApi } from "@/lib/api";

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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bot", "milestones"] }),
  });
  const drop = useMutation({
    mutationFn: (id: number) => botApi.deleteMilestone(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bot", "milestones"] }),
  });

  const [draft, setDraft] = useState({ amount: "", label: "" });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const cents = Math.round(Number(draft.amount.replace(/[$,]/g, "")) * 100);
    if (!Number.isFinite(cents) || cents <= 0) return;
    add.mutate({ amount: cents, label: draft.label.trim() || null });
    setDraft({ amount: "", label: "" });
  };

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-2 text-base font-semibold">Net-worth milestones</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          The bot pings you in the morning brief the first time net worth crosses
          each threshold. Reached milestones stay listed for posterity.
        </p>
        <ul className="mb-3 divide-y rounded-md border">
          {(milestones.data ?? []).map((m) => (
            <li
              key={m.id}
              className="flex items-center justify-between gap-3 px-4 py-3 text-sm"
            >
              <div className="flex items-center gap-2">
                <span className="font-medium">{formatCents(m.threshold_cents)}</span>
                {m.label ? (
                  <span className="text-muted-foreground">— {m.label}</span>
                ) : null}
                {m.reached_at ? (
                  <Badge variant="secondary">
                    Reached {formatDate(m.reached_at)}
                  </Badge>
                ) : null}
              </div>
              <Button variant="ghost" size="sm" onClick={() => drop.mutate(m.id)}>
                Remove
              </Button>
            </li>
          ))}
          {!milestones.data?.length ? (
            <li className="px-4 py-3 text-sm text-muted-foreground">
              No milestones yet — add your first one below.
            </li>
          ) : null}
        </ul>
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
          <Button type="submit" disabled={add.isPending} className="self-end">
            Add milestone
          </Button>
        </form>
      </section>

      <Separator />

      <section>
        <h2 className="mb-2 text-base font-semibold">Streaks</h2>
        {streaks.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {(streaks.data ?? []).map((s) => (
              <li
                key={s.streak_type}
                className="flex items-center justify-between px-4 py-3 text-sm"
              >
                <span className="font-medium">{s.label}</span>
                <span className="text-muted-foreground">
                  {s.current_count} now · best {s.longest_count}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
