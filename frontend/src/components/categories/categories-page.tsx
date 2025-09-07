"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { limitsApi } from "@/lib/api";

export function CategoriesPage() {
  const { data: limits, isLoading } = useQuery({
    queryKey: ["limits"],
    queryFn: () => limitsApi.getAll(),
  });

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
      <div>
        <h1 className="text-3xl font-bold">Categories</h1>
        <p className="text-muted-foreground">
          Manage budget categories and their limits
        </p>
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
    </div>
  );
}
