"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TooltipProvider } from "@/components/ui/tooltip";
import { categoriesApi, ApiError } from "@/lib/api";
import { MerchantRulesSection } from "@/components/categories/merchant-rules-section";
import { confirm } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { Category } from "@/types/v2";
import { Pencil, Plus, Trash2, ChevronDown } from "lucide-react";

const DEFAULT_COLOR = "#3b82f6";

function isValidHexColor(s: string): boolean {
  return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(s.trim());
}

function ColorPicker({
  value,
  onChange,
  id,
}: {
  value: string;
  onChange: (v: string) => void;
  id?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <label
        htmlFor={id}
        className="size-8 shrink-0 cursor-pointer rounded-md border-2 border-border shadow-sm transition-opacity hover:opacity-80"
        style={{ backgroundColor: isValidHexColor(value) ? value : DEFAULT_COLOR }}
        title="Click to change color"
      />
      <input
        id={id}
        type="color"
        value={isValidHexColor(value) ? value : DEFAULT_COLOR}
        onChange={(e) => onChange(e.target.value)}
        className="sr-only"
      />
    </div>
  );
}

function PfcDetailsPopover({ primary, detailed }: { primary: string | null; detailed: string | null }) {
  if (!primary && !detailed) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs text-muted-foreground hover:text-foreground">
          Details
          <ChevronDown className="size-3" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 space-y-2 text-sm" align="start">
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Primary</p>
          <p className="font-mono text-xs break-all">{primary ?? "—"}</p>
        </div>
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Detailed</p>
          <p className="font-mono text-xs break-all">{detailed ?? "—"}</p>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function CategoriesView() {
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(DEFAULT_COLOR);

  const [editOpen, setEditOpen] = useState(false);
  const [editCategory, setEditCategory] = useState<Category | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState(DEFAULT_COLOR);

  const listQuery = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const name = newName.trim();
      if (name.length < 1) return Promise.reject(new Error("Name is required."));
      const color = newColor.trim() || DEFAULT_COLOR;
      if (!isValidHexColor(color)) {
        return Promise.reject(new Error("Invalid color. Please pick a valid color."));
      }
      return categoriesApi.create({
        name,
        color,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      setAddOpen(false);
      setNewName("");
      setNewColor(DEFAULT_COLOR);
    },
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editCategory) return Promise.reject(new Error("No category selected."));
      const name = editName.trim();
      if (name.length < 1) return Promise.reject(new Error("Name is required."));
      const color = editColor.trim() || DEFAULT_COLOR;
      if (!isValidHexColor(color)) {
        return Promise.reject(new Error("Invalid color. Please pick a valid color."));
      }
      return categoriesApi.update(editCategory.id, { name, color });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      setEditOpen(false);
      setEditCategory(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => categoriesApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["categories"] }),
  });

  const openAdd = () => {
    setNewName("");
    setNewColor(DEFAULT_COLOR);
    createMutation.reset();
    setAddOpen(true);
  };

  const openEdit = (c: Category) => {
    setEditCategory(c);
    setEditName(c.name);
    setEditColor(c.color || DEFAULT_COLOR);
    updateMutation.reset();
    setEditOpen(true);
  };

  const handleDelete = async (c: Category) => {
    if (c.source === "plaid_pfc") return;
    const ok = await confirm({
      title: `Delete category "${c.name}"?`,
      description: "This cannot be undone.",
      destructive: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    deleteMutation.mutate(c.id);
  };

  const rows = listQuery.data ?? [];
  const listError =
    listQuery.error instanceof ApiError
      ? listQuery.error.message
      : listQuery.error instanceof Error
        ? listQuery.error.message
        : null;

  return (
    <TooltipProvider>
      <div className="space-y-6">
        <MerchantRulesSection />

        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Categories</h1>
            <p className="text-muted-foreground text-sm">
              Manage spending categories and their Plaid auto-mapping.
            </p>
          </div>
          <Button type="button" onClick={openAdd}>
            <Plus className="size-4" />
            Add Category
          </Button>
        </div>

        {listError ? (
          <p className="text-destructive text-sm" role="alert">{listError}</p>
        ) : null}

        {createMutation.isError ? (
          <p className="text-destructive text-sm" role="alert">
            {createMutation.error instanceof Error ? createMutation.error.message : "Could not create category."}
          </p>
        ) : null}

        {updateMutation.isError ? (
          <p className="text-destructive text-sm" role="alert">
            {updateMutation.error instanceof Error ? updateMutation.error.message : "Could not update category."}
          </p>
        ) : null}

        {deleteMutation.isError ? (
          <p className="text-destructive text-sm" role="alert">
            {deleteMutation.error instanceof ApiError ? deleteMutation.error.message : "Could not delete category."}
          </p>
        ) : null}

        {listQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">Color</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Plaid Mapping</TableHead>
                  <TableHead className="w-[100px]">Type</TableHead>
                  <TableHead className="w-[120px] text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-muted-foreground h-24 text-center">
                      No categories yet.
                    </TableCell>
                  </TableRow>
                ) : (
                  rows.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        <span
                          className="block size-6 rounded-md border border-border/60 shadow-sm"
                          style={{ backgroundColor: c.color || DEFAULT_COLOR }}
                        />
                      </TableCell>
                      <TableCell className="font-medium">{c.name}</TableCell>
                      <TableCell>
                        <PfcDetailsPopover
                          primary={c.plaid_pfc_primary ?? null}
                          detailed={c.plaid_pfc_detailed ?? null}
                        />
                      </TableCell>
                      <TableCell>
                        {c.source === "plaid_pfc" ? (
                          <Badge variant="secondary">Plaid</Badge>
                        ) : (
                          <Badge variant="outline">Custom</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => openEdit(c)}
                            title={
                              c.source === "plaid_pfc"
                                ? "Edit display name or color (Plaid mapping unchanged)"
                                : "Edit"
                            }
                          >
                            <Pencil className="size-3.5" />
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className={cn(
                              "border-destructive/40 text-destructive hover:bg-destructive/10 hover:border-destructive",
                              (c.source === "plaid_pfc" || deleteMutation.isPending) &&
                                "pointer-events-none opacity-50",
                            )}
                            disabled={c.source === "plaid_pfc" || deleteMutation.isPending}
                            onClick={() => handleDelete(c)}
                            title={
                              c.source === "plaid_pfc"
                                ? "Plaid-derived categories cannot be deleted"
                                : "Delete"
                            }
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        )}

        <Dialog open={addOpen} onOpenChange={setAddOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add category</DialogTitle>
              <DialogDescription>
                Create a user-defined category. Categories from Plaid appear automatically after you sync
                transactions.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <div className="grid gap-2">
                <Label htmlFor="cat-name">Name</Label>
                <Input
                  id="cat-name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. Kids activities"
                  maxLength={100}
                />
              </div>
              <div className="grid gap-2">
                <Label>Color</Label>
                <div className="flex items-center gap-3">
                  <ColorPicker id="new-cat-color" value={newColor} onChange={setNewColor} />
                  <span className="text-sm text-muted-foreground">Click the swatch to pick a color</span>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAddOpen(false)}>
                Cancel
              </Button>
              <Button type="button" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
                Save
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog
          open={editOpen}
          onOpenChange={(o) => {
            setEditOpen(o);
            if (!o) setEditCategory(null);
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Edit category</DialogTitle>
              <DialogDescription>
                {editCategory?.source === "plaid_pfc"
                  ? "Rename or recolor for display; Plaid PFC codes below stay the same for syncing."
                  : "Update name and color for this custom category."}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <div className="grid gap-2">
                <Label htmlFor="edit-cat-name">Name</Label>
                <Input
                  id="edit-cat-name"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  maxLength={100}
                />
              </div>
              <div className="grid gap-2">
                <Label>Color</Label>
                <div className="flex items-center gap-3">
                  <ColorPicker id="edit-cat-color" value={editColor} onChange={setEditColor} />
                  <span className="text-sm text-muted-foreground">Click the swatch to pick a color</span>
                </div>
              </div>
              {editCategory && (editCategory.plaid_pfc_primary || editCategory.plaid_pfc_detailed) ? (
                <div className="rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground space-y-1">
                  <p className="font-medium">Plaid mapping (read-only)</p>
                  {editCategory.plaid_pfc_primary && (
                    <p className="font-mono">{editCategory.plaid_pfc_primary}</p>
                  )}
                  {editCategory.plaid_pfc_detailed && (
                    <p className="font-mono">{editCategory.plaid_pfc_detailed}</p>
                  )}
                </div>
              ) : null}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setEditOpen(false)}>
                Cancel
              </Button>
              <Button type="button" onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>
                Save
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </TooltipProvider>
  );
}
