"use client";

/**
 * Chores tab — define what needs to happen, who's on duty this week,
 * and let either partner tick a chore as completed.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Pencil, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
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

  // Two flavours of update: a row "patch" (name/icon/rotation, used by inline
  // edit) and a quick toggle (active flag). Sharing the same mutation keeps
  // server load consistent but we want the assignment list to refresh on both
  // — chore name change must show up in "this week" too.
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

  // Per-row inline edit state — only one chore can be in edit mode at a time
  // so the page stays focused and the user can't lose unsaved typing in
  // siblings.
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);

  const startEdit = (c: ChoreRow) => {
    setEditingId(c.id);
    setEditDraft({
      name: c.name,
      icon: resolveChoreIconKey(c.icon),
      rotation: c.rotation,
      sort_order: c.sort_order,
    });
  };

  const cancelEdit = () => {
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
    cancelEdit();
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
    <div className="space-y-8">
      <section>
        <h2 className="mb-2 text-base font-semibold">
          This week ({formatDate(week)})
        </h2>
        {assignments.isLoading ? (
          <ul className="divide-y rounded-md border">
            {Array.from({ length: 3 }).map((_, i) => (
              <li
                key={i}
                className="flex items-center justify-between px-4 py-3"
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
          <div className="grid place-items-center rounded-md border border-dashed py-8 text-center">
            <Check className="h-6 w-6 text-muted-foreground" aria-hidden />
            <p className="mt-2 text-sm text-muted-foreground">
              Add at least one chore below — assignments populate automatically.
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
                    "flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm transition-colors",
                    "hover:bg-muted/40",
                    a.completed_at &&
                      "bg-gradient-to-r from-emerald-500/5 to-transparent",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <ChoreIcon value={a.chore_icon} />
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
                    disabled={togglePending}
                  >
                    {togglePending ? (
                      <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                    ) : a.completed_at ? (
                      <Check className="mr-1 h-3.5 w-3.5" />
                    ) : null}
                    {a.completed_at ? "Done" : "Mark done"}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <Separator />

      <section>
        <h2 className="mb-2 text-base font-semibold">Manage chores</h2>
        <ul className="mb-4 divide-y rounded-md border">
          {(chores.data ?? []).map((c) => {
            const isEditing = editingId === c.id && editDraft !== null;
            if (isEditing) {
              return (
                <li
                  key={c.id}
                  className="grid gap-3 px-4 py-3 text-sm sm:grid-cols-[1fr,160px,140px,90px,auto]"
                >
                  <div className="grid gap-1">
                    <Label htmlFor={`edit-name-${c.id}`} className="text-xs">
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
                    />
                  </div>
                  <div className="grid gap-1">
                    <Label htmlFor={`edit-icon-${c.id}`} className="text-xs">
                      Icon
                    </Label>
                    <ChoreIconPicker
                      id={`edit-icon-${c.id}`}
                      value={editDraft.icon}
                      onChange={(v) =>
                        setEditDraft((d) => (d ? { ...d, icon: v } : d))
                      }
                    />
                  </div>
                  <div className="grid gap-1">
                    <Label htmlFor={`edit-rot-${c.id}`} className="text-xs">
                      Rotation
                    </Label>
                    <Select
                      value={editDraft.rotation}
                      onValueChange={(v) =>
                        setEditDraft((d) =>
                          d ? { ...d, rotation: v as Rotation } : d,
                        )
                      }
                    >
                      <SelectTrigger id={`edit-rot-${c.id}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="weekly">Weekly</SelectItem>
                        <SelectItem value="biweekly">Biweekly</SelectItem>
                        <SelectItem value="fixed">Fixed</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-1">
                    <Label htmlFor={`edit-sort-${c.id}`} className="text-xs">
                      Order
                    </Label>
                    <Input
                      id={`edit-sort-${c.id}`}
                      type="number"
                      value={editDraft.sort_order}
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
                  <div className="flex items-end gap-1">
                    <Button
                      size="sm"
                      onClick={submitEdit}
                      disabled={updateChore.isPending || !editDraft.name.trim()}
                    >
                      Save
                    </Button>
                    <Button variant="ghost" size="sm" onClick={cancelEdit}>
                      Cancel
                    </Button>
                  </div>
                </li>
              );
            }
            const togglePending =
              updateChore.isPending && updateChore.variables?.id === c.id;
            const deletePending =
              deleteChore.isPending && deleteChore.variables === c.id;
            return (
              <li
                key={c.id}
                className={cn(
                  "flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm transition-colors",
                  "hover:bg-muted/40",
                  !c.is_active && "opacity-60",
                )}
              >
                <div className="flex items-center gap-2">
                  <ChoreIcon value={c.icon} />
                  <span className="font-medium">{c.name}</span>
                  <Badge variant="outline" className="capitalize">
                    {c.rotation}
                  </Badge>
                  {!c.is_active ? (
                    <Badge variant="secondary">Inactive</Badge>
                  ) : null}
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => startEdit(c)}
                    disabled={editingId != null}
                    title="Edit"
                  >
                    <Pencil className="h-4 w-4" />
                    <span className="sr-only">Edit</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      updateChore.mutate({
                        id: c.id,
                        patch: { is_active: !c.is_active },
                      })
                    }
                    disabled={togglePending}
                  >
                    {togglePending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : c.is_active ? (
                      "Disable"
                    ) : (
                      "Enable"
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => requestDelete(c)}
                    disabled={deletePending}
                    title="Delete"
                  >
                    {deletePending ? (
                      <Loader2 className="h-4 w-4 animate-spin text-destructive" />
                    ) : (
                      <Trash2 className="h-4 w-4 text-destructive" />
                    )}
                    <span className="sr-only">Delete</span>
                  </Button>
                </div>
              </li>
            );
          })}
          {!chores.data?.length ? (
            <li className="px-4 py-3 text-sm text-muted-foreground">
              No chores yet — defaults seed on first run.
            </li>
          ) : null}
        </ul>

        <form
          onSubmit={submitNew}
          className="grid gap-3 rounded-md border p-4 sm:grid-cols-[1fr,160px,140px,auto]"
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
            <Label htmlFor="ch-icon">Icon</Label>
            <ChoreIconPicker
              id="ch-icon"
              value={draft.icon}
              onChange={(v) => setDraft((d) => ({ ...d, icon: v }))}
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
          <Button
            type="submit"
            disabled={createChore.isPending || !draft.name.trim()}
            className="self-end"
          >
            {createChore.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-1 h-4 w-4" />
            )}
            Add
          </Button>
        </form>
      </section>
    </div>
  );
}

