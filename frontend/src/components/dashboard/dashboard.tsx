"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { reportsApi, healthApi } from "@/lib/api";
import { ExpenseChart } from "./expense-chart";
import { RecentExpenses } from "./recent-expenses";
import { format } from "date-fns";
import { DollarSign, TrendingUp, TrendingDown, AlertTriangle } from "lucide-react";

export function Dashboard() {
  const currentMonth = format(new Date(), "yyyy-MM");

  // Получаем отчет за текущий месяц
  const { data: report, isLoading: reportLoading } = useQuery({
    queryKey: ["report", currentMonth],
    queryFn: () => reportsApi.getReport(currentMonth),
  });

  // Проверяем здоровье API
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => healthApi.check(),
    refetchInterval: 30000, // каждые 30 секунд
  });

  if (reportLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <Badge variant="secondary" className="animate-pulse">
            Loading...
          </Badge>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Card key={i} className="animate-pulse">
              <CardHeader className="pb-2">
                <div className="h-4 bg-muted rounded"></div>
              </CardHeader>
              <CardContent>
                <div className="h-8 bg-muted rounded mb-2"></div>
                <div className="h-3 bg-muted rounded"></div>
              </CardContent>
            </Card>
          ))}
        </div>
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
  const isOverBudget = totalRemaining < 0;

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
            <DollarSign className="h-4 w-4 text-muted-foreground" />
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
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
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
            {isOverBudget ? (
              <TrendingDown className="h-4 w-4 text-destructive" />
            ) : (
              <DollarSign className="h-4 w-4 text-muted-foreground" />
            )}
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${isOverBudget ? 'text-destructive' : ''}`}>
              ${totalRemaining.toFixed(2)}
            </div>
            <p className="text-xs text-muted-foreground">
              {isOverBudget ? "Over budget!" : "Available to spend"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Budget Status</CardTitle>
            {budgetUsage > 90 ? (
              <AlertTriangle className="h-4 w-4 text-destructive" />
            ) : budgetUsage > 75 ? (
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
            ) : (
              <TrendingUp className="h-4 w-4 text-green-500" />
            )}
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {budgetUsage.toFixed(1)}%
            </div>
            <p className="text-xs text-muted-foreground">
              {budgetUsage > 90 ? "Critical" : budgetUsage > 75 ? "Warning" : "Good"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Charts and Recent Expenses */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Expense Distribution</CardTitle>
            <CardDescription>
              Spending breakdown by category
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ExpenseChart data={report?.report || {}} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent Expenses</CardTitle>
            <CardDescription>
              Latest transactions this month
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RecentExpenses month={currentMonth} />
          </CardContent>
        </Card>
      </div>

      {/* Category Overview */}
      <Card>
        <CardHeader>
          <CardTitle>Category Overview</CardTitle>
          <CardDescription>
            Budget usage by category
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {Object.entries(report?.report || {}).map(([category, data]) => {
              const usage = data.budget > 0 ? (data.spent / data.budget) * 100 : 0;
              const isOver = data.remaining < 0;

              return (
                <div key={category} className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium">{category}</span>
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
                    <div className="flex justify-between text-xs text-muted-foreground mt-1">
                      <span>{usage.toFixed(1)}% used</span>
                      <span>${data.remaining.toFixed(2)} remaining</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
