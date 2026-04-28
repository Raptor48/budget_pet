"use client";

/**
 * Chores tab — define what needs to happen, who's on duty this week,
 * and let either partner tick a chore as completed.
 *
 * V2.3 polish: dense single-row layout, inline editor opens in a popover
 * so the list never reflows, and the assignee dropdown uses the
 * household-members endpoint (which excludes the env ADMIN_LOGIN account
 * so the technical admin user never shows up as someone who has to do
 * the dishes).
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Pencil, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { botApi, type ChoreRow } from "@/lib/api";
import { confirm, notify, onMutationError } from "@/lib/notify";

import { formatDate, todayMonday } from "./bot-helpers";
import {
  ChoreIcon,
  ChoreIconPicker,
  DEFAULT_CHORE_ICON_KEY,
  resolveChoreIconKey,
} from "./chore-icon";

type Rotation = ChoreRow["rotation"];

interface EditDraft {
  name: string;
  icon: string;
  rotation: Rotation;
  sort_order: number;
}

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

  // Real household members only (the env ADMIN_LOGIN bootstrap account is
  // filtered out by the backend so it never shows up in the dropdown).
  const members = useQuery({
    queryKey: ["bot", "household-members"],
    queryFn: botApi.listHouseholdMembers,
    staleTime: 60_000,
  });

  const reassign = useMutation({
    mutationFn: ({
      choreId,
      weekStart,
      userId,
    }: {
      choreId: number;
      weekStart: string;
      userId: number;
    }) => botApi.reassignChore(choreId, weekStart, userId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["bot", "chore-assignments"] }),
    onError: onMutationError("Couldn't reassign that chore."),
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
    onError: onMutationError("Couldn't update that chore."),
  });

  const createChore = useMutation({
    mutationFn: (body: Parameters<typeof botApi.createChore>[0]) =>
      botApi.createChore(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "chores"] });
      qc.invalidateQueries({ queryKey: ["bot", "chore-assignments"] });
      notify.success("Chore added.");
    },
    onError: onMutationError("Couldn't add that chore."),
  });

  const deleteChore = useMutation({
    mutationFn: (id: number) => botApi.deleteChore(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "chores"] });
      qc.invalidateQueries({ queryKey: ["bot", "chore-assignments"] });
      notify.success("Chore deleted.");
    },
    onError: onMutationError("Couldn't delete that chore."),
  });

  const updateChore = useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: number;
      patch: Parameters<typeof botApi.updateChore>[1];
    }) => botApi.updateChore(id, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot", "chores"] });
      qc.invalidateQueries({ queryKey: ["bot", "chore-assignments"] });
    },
    onError: onMutationError("Couldn't save that change."),
  });

  const [draft, setDraft] = useState<{
    name: string;
    icon: string;
    rotation: Rotation;
  }>({ name: "", icon: DEFAULT_CHORE_ICON_KEY, rotation: "weekly" });

  // Per-row inline edit state — used by the Popover editor.
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);

  const openEditor = (c: ChoreRow) => {
    setEditingId(c.id);
    setEditDraft({
      name: c.name,
      icon: resolveChoreIconKey(c.icon),
      rotation: c.rotation,
      sort_order: c.sort_order,
    });
  };

  const closeEditor = () => {
    setEditingId(null);
    setEditDraft(null);
  };

  const submitEdit = async () => {
    if (editingId == null || !editDraft) return;
    const trimmedName = editDraft.name.trim();
    if (!trimmedName) return;
    await updateChore.mutateAsync({
      id: editingId,
      patch: {
        name: trimmedName,
        icon: editDraft.icon || null,
        rotation: editDraft.rotation,
        sort_order: editDraft.sort_order,
      },
    });
    notify.success("Chore updated.");
    closeEditor();
  };

  const submitNew = (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft.name.trim()) return;
    createChore.mutate({
      name: draft.name.trim(),
      icon: draft.icon || null,
      rotation: draft.rotation,
    });
    setDraft({ name: "", icon: DEFAULT_CHORE_ICON_KEY, rotation: "weekly" });
  };

  const requestDelete = async (c: ChoreRow) => {
    const ok = await confirm({
      title: `Delete "${c.name}"?`,
      description:
        "Past assignments stay in history. Future weeks won't include this chore.",
      destructive: true,
      confirmLabel: "Delete",
    });
    if (ok) deleteChore.mutate(c.id);
  };

  return (
    <div className="space-y-6">
      {/* This week — assignments + Mark done */}
      <section>
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            This week
          </h2>
          <span className="text-xs text-muted-foreground">{formatDate(week)}</span>
        </div>
        {assignments.isLoading ? (
          <ul className="divide-y rounded-md border">
            {Array.from({ length: 3 }).map((_, i) => (
              <li
                key={i}
                className="flex items-center justify-between px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <Skeleton className="h-4 w-4 rounded" />
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-5 w-14 rounded-full" />
                </div>
                <Skeleton className="h-7 w-20" />
              </li>
            ))}
          </ul>
        ) : !assignments.data?.length ? (
          <div className="grid place-items-center rounded-md border border-dashed py-6 text-center">
            <Check className="h-5 w-5 text-muted-foreground" aria-hidden />
            <p className="mt-1.5 text-xs text-muted-foreground">
              Add a chore below — assignments populate automatically.
            </p>
          </div>
        ) : (
          <ul className="divide-y rounded-md border">
            {assignments.data.map((a) => {
              const togglePending =
                setCompleted.isPending &&
                setCompleted.variables?.choreId === a.chore_id;
              return (
                <li
                  key={a.chore_id}
                  className={cn(
                    "flex items-center justify-between gap-2 px-3 py-2 text-sm transition-colors",
                    "hover:bg-muted/40",
                    a.completed_at &&
                      "bg-gradient-to-r from-emerald-500/5 to-transparent",
                  )}
                >
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <ChoreIcon value={a.chore_icon} />
                    <span className="truncate font-medium">{a.chore_name}</span>
                    {members.data && members.data.length > 1 ? (
                      <Select
                        value={String(a.user_id)}
                        onValueChange={(v) =>
                          reassign.mutate({
                            choreId: a.chore_id,
                            weekStart: a.week_start,
                            userId: Number(v),
                          })
                        }
                        disabled={
                          reassign.isPending &&
                          reassign.variables?.choreId === a.chore_id
                        }
                      >
                        <SelectTrigger className="h-7 w-auto min-w-[100px] gap-1 border-0 bg-transparent px-2 text-xs hover:bg-muted/60">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {members.data.map((u) => (
                            <SelectItem key={u.id} value={String(u.id)}>
                              {u.username}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Badge variant="outline" className="text-[10px]">
                        {a.username}
                      </Badge>
                    )}
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
                    disabled={togglePending}
                    className="h-7 shrink-0 px-2.5 text-xs"
                  >
                    {togglePending ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : a.completed_at ? (
                      <Check className="mr-1 h-3 w-3" />
                    ) : null}
                    {a.completed_at ? "Done" : "Mark done"}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* Manage chores — dense list + inline add */}
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Manage chores
        </h2>
        <ul className="mb-3 divide-y rounded-md border">
          {(chores.data ?? []).map((c) => {
            const togglePending =
              updateChore.isPending && updateChore.variables?.id === c.id;
            const deletePending =
              deleteChore.isPending && deleteChore.variables === c.id;
            const isOpen = editingId === c.id;
            return (
              <li
                key={c.id}
                className={cn(
                  "flex items-center justify-between gap-2 px-3 py-2 text-sm transition-colors",
                  "hover:bg-muted/40",
                  !c.is_active && "opacity-60",
                )}
              >
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <ChoreIcon value={c.icon} />
                  <span className="truncate font-medium">{c.name}</span>
                  <Badge variant="outline" className="text-[10px] capitalize">
                    {c.rotation}
                  </Badge>
                  {!c.is_active ? (
                    <Badge variant="secondary" className="text-[10px]">
                      Inactive
                    </Badge>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-0.5">
                  <Popover
                    open={isOpen}
                    onOpenChange={(open) => {
                      if (open) {
                        openEditor(c);
                      } else {
                        closeEditor();
                      }
                    }}
                  >
                    <PopoverTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        title="Edit"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        <span className="sr-only">Edit</span>
                      </Button>
                    </PopoverTrigger>
                    {isOpen && editDraft ? (
                      <PopoverContent
                        align="end"
                        className="w-72 space-y-3 p-3"
                      >
                        <div className="grid gap-1">
                          <Label
                            htmlFor={`edit-name-${c.id}`}
                            className="text-xs"
                          >
                            Name
                          </Label>
                          <Input
                            id={`edit-name-${c.id}`}
                            value={editDraft.name}
                            onChange={(e) =>
                              setEditDraft((d) =>
                                d ? { ...d, name: e.target.value } : d,
                              )
                            }
                            autoFocus
                            className="h-8"
                          />
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="grid gap-1">
                            <Label
                              htmlFor={`edit-icon-${c.id}`}
                              className="text-xs"
                            >
                              Icon
                            </Label>
                            <ChoreIconPicker
                              id={`edit-icon-${c.id}`}
                              value={editDraft.icon}
                              onChange={(v) =>
                                setEditDraft((d) =>
                                  d ? { ...d, icon: v } : d,
                                )
                              }
                            />
                          </div>
                          <div className="grid gap-1">
                            <Label
                              htmlFor={`edit-rot-${c.id}`}
                              className="text-xs"
                            >
                              Rotation
                            </Label>
                            <Select
                              value={editDraft.rotation}
                              onValueChange={(v) =>
                                setEditDraft((d) =>
                                  d
                                    ? { ...d, rotation: v as Rotation }
                                    : d,
                                )
                              }
                            >
                              <SelectTrigger
                                id={`edit-rot-${c.id}`}
                                className="h-8"
                              >
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="weekly">Weekly</SelectItem>
                                <SelectItem value="biweekly">Biweekly</SelectItem>
                                <SelectItem value="fixed">Fixed</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                        <div className="grid gap-1">
                          <Label
                            htmlFor={`edit-sort-${c.id}`}
                            className="text-xs"
                          >
                            Sort order
                          </Label>
                          <Input
                            id={`edit-sort-${c.id}`}
                            type="number"
                            value={editDraft.sort_order}
                            className="h-8"
                            onChange={(e) =>
                              setEditDraft((d) =>
                                d
                                  ? {
                                      ...d,
                                      sort_order:
                                        Number.isFinite(Number(e.target.value))
                                          ? Number(e.target.value)
                                          : 0,
                                    }
                                  : d,
                              )
                            }
                          />
                        </div>
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={closeEditor}
                          >
                            Cancel
                          </Button>
                          <Button
                            size="sm"
                            onClick={submitEdit}
                            disabled={
                              updateChore.isPending || !editDraft.name.trim()
                            }
                          >
                            Save
                          </Button>
                        </div>
                      </PopoverContent>
                    ) : null}
                  </Popover>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() =>
                      updateChore.mutate({
                        id: c.id,
                        patch: { is_active: !c.is_active },
                      })
                    }
                    disabled={togglePending}
                  >
                    {togglePending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : c.is_active ? (
                      "Disable"
                    ) : (
                      "Enable"
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => requestDelete(c)}
                    disabled={deletePending}
                    title="Delete"
                  >
                    {deletePending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-destructive" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5 text-destructive" />
                    )}
                    <span className="sr-only">Delete</span>
                  </Button>
                </div>
              </li>
            );
          })}
          {!chores.data?.length ? (
            <li className="px-3 py-2 text-sm text-muted-foreground">
              No chores yet — defaults seed on first run.
            </li>
          ) : null}
        </ul>

        <form
          onSubmit={submitNew}
          className="flex flex-wrap items-end gap-2 rounded-md border bg-muted/20 p-2"
        >
          <div className="grid min-w-[180px] flex-1 gap-1">
            <Label htmlFor="ch-name" className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Name
            </Label>
            <Input
              id="ch-name"
              placeholder="Trash & recycling"
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              className="h-8"
            />
          </div>
          <div className="grid w-[120px] gap-1">
            <Label htmlFor="ch-icon" className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Icon
            </Label>
            <ChoreIconPicker
              id="ch-icon"
              value={draft.icon}
              onChange={(v) => setDraft((d) => ({ ...d, icon: v }))}
            />
          </div>
          <div className="grid w-[110px] gap-1">
            <Label htmlFor="ch-rotation" className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Rotation
            </Label>
            <Select
              value={draft.rotation}
              onValueChange={(v) =>
                setDraft((d) => ({ ...d, rotation: v as Rotation }))
              }
            >
              <SelectTrigger id="ch-rotation" className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="weekly">Weekly</SelectItem>
                <SelectItem value="biweekly">Biweekly</SelectItem>
                <SelectItem value="fixed">Fixed</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button
            type="submit"
            size="sm"
            disabled={createChore.isPending || !draft.name.trim()}
            className="h-8"
          >
            {createChore.isPending ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="mr-1 h-3.5 w-3.5" />
            )}
            Add
          </Button>
        </form>
      </section>
    </div>
  );
}
