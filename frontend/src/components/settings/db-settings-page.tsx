"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { limitsApi } from "@/lib/api";
import {
  Database,
  Plus,
  Edit,
  Trash2,
  DollarSign,
  Settings,
  AlertCircle,
  CheckCircle
} from "lucide-react";

interface Limit {
  category: string;
  default_limit: number;
}

export function DBSettingsPage() {
  const [newCategory, setNewCategory] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [editingCategoryName, setEditingCategoryName] = useState("");
  const [editingLimit, setEditingLimit] = useState("");
  const [isAddingCategory, setIsAddingCategory] = useState(false);
  const [isEditingCategory, setIsEditingCategory] = useState(false);

  const queryClient = useQueryClient();

  // Получаем список лимитов (категорий)
  const { data: limits, isLoading: limitsLoading, error: limitsError } = useQuery({
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
      setIsAddingCategory(false);
    },
  });

  // Мутация для обновления лимита
  const updateLimitMutation = useMutation({
    mutationFn: ({ category, limit }: { category: string; limit: number }) =>
      limitsApi.update(category, { default_limit: limit }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["limits"] });
      setEditingLimit("");
      setIsEditingCategory(false);
    },
  });

  // Мутация для обновления названия категории
  const updateCategoryNameMutation = useMutation({
    mutationFn: ({ oldName, newName }: { oldName: string; newName: string }) =>
      limitsApi.update(oldName, { category: newName }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["limits"] });
      setEditingCategoryName("");
      setIsEditingCategory(false);
    },
  });

  // Мутация для удаления категории
  const deleteCategoryMutation = useMutation({
    mutationFn: (category: string) => limitsApi.delete(category),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["limits"] });
    },
  });

  const handleAddCategory = () => {
    if (!newCategory.trim()) return;
    
    const limit = parseFloat(editingLimit) || 0;
    createCategoryMutation.mutate({
      category: newCategory.trim(),
      default_limit: limit,
    });
  };

  const handleSelectCategory = (category: string) => {
    setSelectedCategory(category);
    const limit = limits?.find(l => l.category === category);
    if (limit) {
      setEditingCategoryName(limit.category);
      setEditingLimit(limit.default_limit.toString());
    }
    setIsEditingCategory(true);
  };

  const handleUpdateCategory = () => {
    if (!selectedCategory || !editingCategoryName.trim() || !editingLimit) return;
    
    const limit = parseFloat(editingLimit);
    if (isNaN(limit) || limit < 0) return;
    
    // Обновляем название категории
    if (editingCategoryName !== selectedCategory) {
      updateCategoryNameMutation.mutate({
        oldName: selectedCategory,
        newName: editingCategoryName.trim(),
      });
    }
    
    // Обновляем лимит
    updateLimitMutation.mutate({
      category: editingCategoryName.trim(),
      limit,
    });
  };

  const handleDeleteCategory = () => {
    if (!selectedCategory) return;
    if (confirm(`Удалить категорию "${selectedCategory}"?`)) {
      deleteCategoryMutation.mutate(selectedCategory);
      setSelectedCategory("");
      setIsEditingCategory(false);
    }
  };

  const cancelEditing = () => {
    setSelectedCategory("");
    setIsEditingCategory(false);
    setEditingCategoryName("");
    setEditingLimit("");
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Database Settings</h1>
          <p className="text-muted-foreground">
            Manage categories and budget limits
          </p>
        </div>
        <Badge variant="secondary" className="gap-2">
          <Database className="h-4 w-4" />
          v4.0.0
        </Badge>
      </div>

      {/* Categories Management */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            Categories Management
          </CardTitle>
          <CardDescription>
            Add, edit, and manage expense categories
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Add New Category */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">Add New Category</h3>
              <Button
                onClick={() => setIsAddingCategory(!isAddingCategory)}
                variant="outline"
                size="sm"
              >
                <Plus className="h-4 w-4 mr-2" />
                {isAddingCategory ? "Cancel" : "Add Category"}
              </Button>
            </div>

            {isAddingCategory && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-4 border rounded-lg bg-muted/50">
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
                    value={editingLimit}
                    onChange={(e) => setEditingLimit(e.target.value)}
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    onClick={handleAddCategory}
                    disabled={createCategoryMutation.isPending || !newCategory.trim()}
                    className="w-full"
                  >
                    {createCategoryMutation.isPending ? "Adding..." : "Add Category"}
                  </Button>
                </div>
              </div>
            )}

            {createCategoryMutation.isError && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  Failed to add category: {createCategoryMutation.error?.message}
                </AlertDescription>
              </Alert>
            )}
          </div>

          <Separator />

          {/* Categories List */}
          <div className="space-y-4">
            <h3 className="text-lg font-semibold">Existing Categories</h3>
            
            {limitsLoading && (
              <div className="text-center py-4">
                <p className="text-muted-foreground">Loading categories...</p>
              </div>
            )}

            {limitsError && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  Failed to load categories: {limitsError.message}
                </AlertDescription>
              </Alert>
            )}

            {limits && limits.length === 0 && (
              <div className="text-center py-8">
                <p className="text-muted-foreground">No categories found</p>
              </div>
            )}

            {limits && limits.length > 0 && (
              <div className="space-y-4">
                {/* Category Selection */}
                <div className="space-y-2">
                  <Label htmlFor="category-select">Select Category to Edit</Label>
                  <Select value={selectedCategory} onValueChange={handleSelectCategory}>
                    <SelectTrigger id="category-select">
                      <SelectValue placeholder="Choose a category to edit..." />
                    </SelectTrigger>
                    <SelectContent>
                      {limits.map((limit) => (
                        <SelectItem key={limit.category} value={limit.category}>
                          {limit.category} (${limit.default_limit.toFixed(2)})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Category Editing Form */}
                {isEditingCategory && selectedCategory && (
                  <div className="p-4 border rounded-lg bg-muted/50 space-y-4">
                    <div className="flex items-center justify-between">
                      <h4 className="font-medium">Edit Category: {selectedCategory}</h4>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={cancelEditing}
                      >
                        Cancel
                      </Button>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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

                    <div className="flex items-center gap-2">
                      <Button
                        onClick={handleUpdateCategory}
                        disabled={updateLimitMutation.isPending || updateCategoryNameMutation.isPending}
                      >
                        {updateLimitMutation.isPending || updateCategoryNameMutation.isPending ? "Saving..." : "Save Changes"}
                      </Button>
                      <Button
                        variant="destructive"
                        onClick={handleDeleteCategory}
                        disabled={deleteCategoryMutation.isPending}
                      >
                        <Trash2 className="h-4 w-4 mr-2" />
                        Delete Category
                      </Button>
                    </div>

                    {(updateLimitMutation.isError || updateCategoryNameMutation.isError) && (
                      <Alert variant="destructive">
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription>
                          Failed to update category: {updateLimitMutation.error?.message || updateCategoryNameMutation.error?.message}
                        </AlertDescription>
                      </Alert>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Quick Stats */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DollarSign className="h-5 w-5" />
            Quick Stats
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="text-center">
              <p className="text-2xl font-bold">{limits?.length || 0}</p>
              <p className="text-sm text-muted-foreground">Total Categories</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold">
                ${limits?.reduce((sum, limit) => sum + limit.default_limit, 0).toFixed(2) || "0.00"}
              </p>
              <p className="text-sm text-muted-foreground">Total Budget</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold">
                ${limits?.length ? (limits.reduce((sum, limit) => sum + limit.default_limit, 0) / limits.length).toFixed(2) : "0.00"}
              </p>
              <p className="text-sm text-muted-foreground">Average Limit</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
