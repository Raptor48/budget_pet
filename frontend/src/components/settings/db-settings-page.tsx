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
  const [editingCategory, setEditingCategory] = useState<string | null>(null);
  const [editingLimit, setEditingLimit] = useState<string | null>(null);
  const [newLimit, setNewLimit] = useState("");
  const [isAddingCategory, setIsAddingCategory] = useState(false);

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
      setEditingLimit(null);
      setNewLimit("");
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
    
    const limit = parseFloat(newLimit) || 0;
    createCategoryMutation.mutate({
      category: newCategory.trim(),
      default_limit: limit,
    });
  };

  const handleUpdateLimit = (category: string) => {
    const limit = parseFloat(newLimit);
    if (isNaN(limit) || limit < 0) return;
    
    updateLimitMutation.mutate({
      category,
      limit,
    });
  };

  const handleDeleteCategory = (category: string) => {
    if (confirm(`Удалить категорию "${category}"?`)) {
      deleteCategoryMutation.mutate(category);
    }
  };

  const startEditingLimit = (category: string, currentLimit: number) => {
    setEditingLimit(category);
    setNewLimit(currentLimit.toString());
  };

  const cancelEditing = () => {
    setEditingLimit(null);
    setNewLimit("");
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
                    value={newLimit}
                    onChange={(e) => setNewLimit(e.target.value)}
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
              <div className="space-y-3">
                {limits.map((limit) => (
                  <div
                    key={limit.category}
                    className="flex items-center justify-between p-4 border rounded-lg"
                  >
                    <div className="flex items-center gap-4">
                      <div>
                        <h4 className="font-medium">{limit.category}</h4>
                        <p className="text-sm text-muted-foreground">
                          Current limit: ${limit.default_limit.toFixed(2)}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {editingLimit === limit.category ? (
                        <div className="flex items-center gap-2">
                          <Input
                            type="number"
                            placeholder="New limit"
                            value={newLimit}
                            onChange={(e) => setNewLimit(e.target.value)}
                            className="w-24"
                          />
                          <Button
                            size="sm"
                            onClick={() => handleUpdateLimit(limit.category)}
                            disabled={updateLimitMutation.isPending}
                          >
                            <CheckCircle className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={cancelEditing}
                          >
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => startEditingLimit(limit.category, limit.default_limit)}
                          >
                            <Edit className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => handleDeleteCategory(limit.category)}
                            disabled={deleteCategoryMutation.isPending}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
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
