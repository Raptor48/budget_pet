"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { limitsApi } from "@/lib/api";
import {
  Plus,
  Edit,
  Trash2,
  AlertCircle
} from "lucide-react";

export function CategoriesPage() {
  const [newCategory, setNewCategory] = useState("");
  const [newLimit, setNewLimit] = useState("");
  const [editingCategory, setEditingCategory] = useState<string | null>(null);
  const [editingCategoryName, setEditingCategoryName] = useState("");
  const [editingLimit, setEditingLimit] = useState("");
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);

  const queryClient = useQueryClient();

  const { data: limits, isLoading } = useQuery({
    queryKey: ["limits"],
    queryFn: () => limitsApi.getAll(),
  });

  // Мутация для создания категории
  const createCategoryMutation = useMutation({
    mutationFn: (category: { category: string; default_limit: number }) =>
      limitsApi.create(category),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["limits"] });
      setNewCategory("");
      setNewLimit("");
      setIsAddDialogOpen(false);
    },
  });

  // Мутация для обновления лимита
  const updateLimitMutation = useMutation({
    mutationFn: ({ category, limit }: { category: string; limit: number }) =>
      limitsApi.update(category, { default_limit: limit }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["limits"] });
      setEditingLimit("");
      setIsEditDialogOpen(false);
    },
  });

  // Мутация для обновления названия категории
  const updateCategoryNameMutation = useMutation({
    mutationFn: ({ oldName, newName }: { oldName: string; newName: string }) =>
      limitsApi.update(oldName, { category: newName }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["limits"] });
      setEditingCategoryName("");
      setIsEditDialogOpen(false);
    },
  });

  // Мутация для удаления категории
  const deleteCategoryMutation = useMutation({
    mutationFn: (category: string) => limitsApi.delete(category),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["limits"] });
    },
  });

  // Обработчики событий
  const handleAddCategory = () => {
    if (!newCategory.trim() || !newLimit) return;
    
    const limit = parseFloat(newLimit);
    if (isNaN(limit) || limit < 0) return;
    
    createCategoryMutation.mutate({
      category: newCategory.trim(),
      default_limit: limit,
    });
  };

  const handleEditCategory = (category: string) => {
    const limit = limits?.find(l => l.category === category);
    if (limit) {
      setEditingCategory(category);
      setEditingCategoryName(limit.category);
      setEditingLimit(limit.default_limit.toString());
      setIsEditDialogOpen(true);
    }
  };

  const handleUpdateCategory = () => {
    if (!editingCategory || !editingCategoryName.trim() || !editingLimit) return;
    
    const limit = parseFloat(editingLimit);
    if (isNaN(limit) || limit < 0) return;
    
    // Обновляем название категории
    if (editingCategoryName !== editingCategory) {
      updateCategoryNameMutation.mutate({
        oldName: editingCategory,
        newName: editingCategoryName.trim(),
      });
    }
    
    // Обновляем лимит
    updateLimitMutation.mutate({
      category: editingCategoryName.trim(),
      limit,
    });
  };

  const handleDeleteCategory = (category: string) => {
    if (confirm(`Удалить категорию "${category}"?`)) {
      deleteCategoryMutation.mutate(category);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Categories</h1>
        <p>Loading categories...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Categories</h1>
          <p className="text-muted-foreground">
            Manage budget categories and their limits
          </p>
        </div>
        <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4 mr-2" />
              Add Category
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add New Category</DialogTitle>
              <DialogDescription>
                Create a new expense category with a budget limit.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="new-category">Category Name</Label>
                <Input
                  id="new-category"
                  placeholder="Enter category name"
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="new-limit">Default Limit</Label>
                <Input
                  id="new-limit"
                  type="number"
                  placeholder="0.00"
                  value={newLimit}
                  onChange={(e) => setNewLimit(e.target.value)}
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setIsAddDialogOpen(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleAddCategory}
                disabled={createCategoryMutation.isPending || !newCategory.trim() || !newLimit}
              >
                {createCategoryMutation.isPending ? "Adding..." : "Add Category"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Categories Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {limits?.map((limit) => (
          <Card key={limit.category}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                {limit.category}
                <Badge variant="secondary">${limit.default_limit.toFixed(2)}</Badge>
              </CardTitle>
              <CardDescription>
                Monthly budget limit
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                ${limit.default_limit.toFixed(2)}
              </div>
              <p className="text-sm text-muted-foreground">
                Default monthly allocation
              </p>
              <div className="flex gap-2 mt-4">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleEditCategory(limit.category)}
                >
                  <Edit className="h-4 w-4 mr-2" />
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => handleDeleteCategory(limit.category)}
                  disabled={deleteCategoryMutation.isPending}
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {(!limits || limits.length === 0) && (
        <Card>
          <CardContent className="text-center py-8">
            <p className="text-muted-foreground">No categories found</p>
          </CardContent>
        </Card>
      )}

      {/* Edit Category Dialog */}
      <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Category</DialogTitle>
            <DialogDescription>
              Update the category name and budget limit.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-category-name">Category Name</Label>
              <Input
                id="edit-category-name"
                placeholder="Enter category name"
                value={editingCategoryName}
                onChange={(e) => setEditingCategoryName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-limit">Limit</Label>
              <Input
                id="edit-limit"
                type="number"
                placeholder="0.00"
                value={editingLimit}
                onChange={(e) => setEditingLimit(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsEditDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={handleUpdateCategory}
              disabled={updateLimitMutation.isPending || updateCategoryNameMutation.isPending || !editingCategoryName.trim() || !editingLimit}
            >
              {updateLimitMutation.isPending || updateCategoryNameMutation.isPending ? "Saving..." : "Save Changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Error Alerts */}
      {createCategoryMutation.isError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Failed to add category: {createCategoryMutation.error?.message}
          </AlertDescription>
        </Alert>
      )}

      {(updateLimitMutation.isError || updateCategoryNameMutation.isError) && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Failed to update category: {updateLimitMutation.error?.message || updateCategoryNameMutation.error?.message}
          </AlertDescription>
        </Alert>
      )}

      {deleteCategoryMutation.isError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Failed to delete category: {deleteCategoryMutation.error?.message}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
