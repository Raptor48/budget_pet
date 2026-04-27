"use client";

/**
 * Chores tab — define what needs to happen, who's on duty this week,
 * and let either partner tick a chore as completed.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { botApi, type ChoreRow } from "@/lib/api";

import { formatDate, todayMonday } from "./bot-helpers";

type Rotation = ChoreRow["rotation"];

export function BotChoresTab() {
  const qc = useQueryClient();
  const chores = useQuery({
    queryKey: ["bot", "chores"],
    queryFn: botApi.listChores,
  });
  const week = todayMonday();
  const assignments = useQuery({
    queryKey: ["bot", "chore-assignments", week],
    queryFn: () => botApi.listChoreAssignments(week),
  });

  const setCompleted = useMutation({
    mutationFn: ({
      choreId,
      weekStart,
      completed,
    }: {
      choreId: number;
      weekStart: string;
      completed: boolean;
    }) => botApi.setChoreCompleted(choreId, weekStart, completed),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["bot", "chore-assignments"] }),
  });

  const createChore = useMutation({
    mutationFn: (body: Parameters<typeof botApi.createChore>[0]) =>
      botApi.createChore(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "chores"] });
      qc.invalidateQueries({ queryKey: ["bot", "chore-assignments"] });
    },
  });

  const deleteChore = useMutation({
    mutationFn: (id: number) => botApi.deleteChore(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "chores"] });
      qc.invalidateQueries({ queryKey: ["bot", "chore-assignments"] });
    },
  });

  const updateChore = useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: number;
      patch: Parameters<typeof botApi.updateChore>[1];
    }) => botApi.updateChore(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bot", "chores"] }),
  });

  const [draft, setDraft] = useState<{
    name: string;
    icon: string;
    rotation: Rotation;
  }>({ name: "", icon: "", rotation: "weekly" });

  const submitNew = (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft.name.trim()) return;
    createChore.mutate({
      name: draft.name.trim(),
      icon: draft.icon.trim() || null,
      rotation: draft.rotation,
    });
    setDraft({ name: "", icon: "", rotation: "weekly" });
  };

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-2 text-base font-semibold">
          This week ({formatDate(week)})
        </h2>
        {assignments.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : !assignments.data?.length ? (
          <p className="text-sm text-muted-foreground">
            Add at least one chore below — assignments populate automatically.
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {assignments.data.map((a) => (
              <li
                key={a.chore_id}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="text-base">{a.chore_icon ?? "🧹"}</span>
                  <span className="font-medium">{a.chore_name}</span>
                  <Badge variant="outline">{a.username}</Badge>
                </div>
                <Button
                  size="sm"
                  variant={a.completed_at ? "secondary" : "outline"}
                  onClick={() =>
                    setCompleted.mutate({
                      choreId: a.chore_id,
                      weekStart: a.week_start,
                      completed: !a.completed_at,
                    })
                  }
                >
                  {a.completed_at ? "Done ✓" : "Mark done"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Separator />

      <section>
        <h2 className="mb-2 text-base font-semibold">Manage chores</h2>
        <ul className="mb-4 divide-y rounded-md border">
          {(chores.data ?? []).map((c) => (
            <li
              key={c.id}
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm"
            >
              <div className="flex items-center gap-2">
                <span className="text-base">{c.icon ?? "🧹"}</span>
                <span className="font-medium">{c.name}</span>
                <Badge variant="outline">{c.rotation}</Badge>
                {!c.is_active ? <Badge variant="secondary">Inactive</Badge> : null}
              </div>
              <div className="flex items-center gap-2">
                <Select
                  value={c.rotation}
                  onValueChange={(v) =>
                    updateChore.mutate({
                      id: c.id,
                      patch: { rotation: v as Rotation },
                    })
                  }
                >
                  <SelectTrigger className="h-8 w-[110px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="weekly">Weekly</SelectItem>
                    <SelectItem value="biweekly">Biweekly</SelectItem>
                    <SelectItem value="fixed">Fixed</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    updateChore.mutate({
                      id: c.id,
                      patch: { is_active: !c.is_active },
                    })
                  }
                >
                  {c.is_active ? "Disable" : "Enable"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => deleteChore.mutate(c.id)}
                >
                  Delete
                </Button>
              </div>
            </li>
          ))}
          {!chores.data?.length ? (
            <li className="px-4 py-3 text-sm text-muted-foreground">
              No chores yet — defaults seed on first run.
            </li>
          ) : null}
        </ul>

        <form
          onSubmit={submitNew}
          className="grid gap-3 rounded-md border p-4 sm:grid-cols-[1fr,80px,140px,auto]"
        >
          <div className="grid gap-1">
            <Label htmlFor="ch-name">Name</Label>
            <Input
              id="ch-name"
              placeholder="Trash & recycling"
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="ch-icon">Emoji</Label>
            <Input
              id="ch-icon"
              maxLength={4}
              placeholder="🗑️"
              value={draft.icon}
              onChange={(e) => setDraft((d) => ({ ...d, icon: e.target.value }))}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="ch-rotation">Rotation</Label>
            <Select
              value={draft.rotation}
              onValueChange={(v) =>
                setDraft((d) => ({ ...d, rotation: v as Rotation }))
              }
            >
              <SelectTrigger id="ch-rotation">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="weekly">Weekly</SelectItem>
                <SelectItem value="biweekly">Biweekly</SelectItem>
                <SelectItem value="fixed">Fixed</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button type="submit" disabled={createChore.isPending} className="self-end">
            Add
          </Button>
        </form>
      </section>
    </div>
  );
}
