"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { reportsApi, healthApi } from "@/lib/api";
import { ExpenseBarChart } from "@/components/charts/expense-bar-chart";
import { RecentExpenses } from "@/components/dashboard/recent-expenses";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { format } from "date-fns";

export function SimpleDashboard() {
  const currentMonth = format(new Date(), "yyyy-MM");

  // Получаем отчет за текущий месяц
  const { data: report, isLoading } = useQuery({
    queryKey: ["report", currentMonth],
    queryFn: () => reportsApi.getReport(currentMonth),
  });

  // Проверяем здоровье API
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => healthApi.check(),
    refetchInterval: 30000,
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <Badge variant="secondary">Loading...</Badge>
        </div>
        <p>Loading dashboard data...</p>
      </div>
    );
  }

  // Вычисляем общие метрики
  const totalBudget = Object.values(report?.report || {}).reduce(
    (sum, item) => sum + item.budget, 0
  );
  const totalSpent = Object.values(report?.report || {}).reduce(
    (sum, item) => sum + item.spent, 0
  );
  const totalRemaining = Object.values(report?.report || {}).reduce(
    (sum, item) => sum + item.remaining, 0
  );

  const budgetUsage = totalBudget > 0 ? (totalSpent / totalBudget) * 100 : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground">
            Overview for {format(new Date(), "MMMM yyyy")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Badge variant={health?.ok ? "default" : "destructive"}>
            {health?.ok ? "API Online" : "API Offline"}
          </Badge>
        </div>
      </div>

      {/* Metrics Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Budget</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${totalBudget.toFixed(2)}</div>
            <p className="text-xs text-muted-foreground">
              Monthly budget allocation
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Spent</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${totalSpent.toFixed(2)}</div>
            <p className="text-xs text-muted-foreground">
              {budgetUsage.toFixed(1)}% of budget used
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Remaining</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${totalRemaining.toFixed(2)}</div>
            <p className="text-xs text-muted-foreground">
              Available to spend
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Categories</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {Object.keys(report?.report || {}).length}
            </div>
            <p className="text-xs text-muted-foreground">
              Active categories
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Recent Expenses and Category Overview */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent Expenses</CardTitle>
            <CardDescription>
              Last 10 transactions
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RecentExpenses month={currentMonth} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Category Overview</CardTitle>
            <CardDescription>
              Budget usage by category
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4 max-h-64 overflow-y-auto">
              {Object.entries(report?.report || {}).map(([category, data]) => {
                const usage = data.budget > 0 ? (data.spent / data.budget) * 100 : 0;
                const isOver = data.remaining < 0;

                return (
                  <div key={category} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-sm">{category}</span>
                      <span className={`text-sm ${isOver ? 'text-destructive' : ''}`}>
                        ${data.spent.toFixed(2)} / ${data.budget.toFixed(2)}
                      </span>
                    </div>
                    <div className="w-full bg-secondary rounded-full h-2">
                      <div
                        className={`h-2 rounded-full transition-all duration-300 ${
                          isOver ? 'bg-destructive' : usage > 90 ? 'bg-yellow-500' : 'bg-primary'
                        }`}
                        style={{ width: `${Math.min(usage, 100)}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>{usage.toFixed(1)}% used</span>
                      <span>${data.remaining.toFixed(2)} remaining</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Expense Bar Chart - Full Width */}
      <Card>
        <CardHeader>
          <CardTitle>Expense Distribution</CardTitle>
          <CardDescription>
            Spending breakdown by category (sorted by amount spent)
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ExpenseBarChart data={report?.report || {}} />
        </CardContent>
      </Card>
    </div>
  );
}
