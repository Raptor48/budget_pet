"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { reportsApi, healthApi } from "@/lib/api";
import { ExpenseBarChart } from "@/components/charts/expense-bar-chart";
import { RecentExpenses } from "@/components/dashboard/recent-expenses";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { format, addMonths, subMonths } from "date-fns";
import { useState } from "react";

export function SimpleDashboard() {
  const [selectedMonth, setSelectedMonth] = useState(format(new Date(), "yyyy-MM"));

  // Генерируем список месяцев (текущий + 6 месяцев назад + 6 месяцев вперед)
  const generateMonthOptions = () => {
    const options = [];
    const currentDate = new Date();
    
    for (let i = -6; i <= 6; i++) {
      const date = addMonths(currentDate, i);
      const value = format(date, "yyyy-MM");
      const label = format(date, "MMMM yyyy");
      options.push({ value, label });
    }
    
    return options;
  };

  // Получаем отчет за выбранный месяц
  const { data: report, isLoading } = useQuery({
    queryKey: ["report", selectedMonth],
    queryFn: () => reportsApi.getReport(selectedMonth),
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
          <div className="flex items-center gap-4">
            <p className="text-muted-foreground">
              Overview for {format(new Date(selectedMonth + "-01"), "MMMM yyyy")}
            </p>
            <Select value={selectedMonth} onValueChange={setSelectedMonth}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {generateMonthOptions().map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
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
          </CardHeader>
          <CardContent>
            <RecentExpenses month={selectedMonth} />
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
            <div className="flex gap-2 justify-center flex-wrap">
              {Object.entries(report?.report || {}).map(([category, data]) => {
                const usage = data.budget > 0 ? (data.spent / data.budget) * 100 : 0;
                const isOver = data.remaining < 0;
                
                // Определяем цвет столбца
                let barColor = 'bg-primary'; // по умолчанию синий
                if (usage > 90 || isOver) {
                  barColor = 'bg-red-600'; // ярко красный при >90% или превышении
                } else if (usage > 70) {
                  barColor = 'bg-red-400'; // светло красный при >70%
                }

                return (
                  <div key={category} className="flex flex-col items-center min-w-[60px]">
                    {/* Лимит сверху */}
                    <div className="text-xs text-muted-foreground text-center mb-2">
                      ${data.budget.toFixed(0)}
                    </div>
                    
                    {/* Компактный прогресс-бар с названием категории внутри */}
                    <div className="relative w-12 h-32 bg-slate-200 rounded-2xl flex items-center justify-center border-2 border-slate-400">
                      {/* Прогресс-бар */}
                      <div
                        className={`absolute bottom-0 left-0 right-0 rounded-2xl transition-all duration-300 ${barColor}`}
                        style={{ height: `${Math.min(usage, 100)}%` }}
                      />
                      {/* Текст с условным цветом */}
                      <span 
                        className={`relative z-10 text-xs font-bold text-center ${
                          usage > 50 ? 'text-white' : 'text-slate-800'
                        }`}
                        style={{ 
                          writingMode: 'vertical-rl',
                          textOrientation: 'mixed'
                        }}
                      >
                        {category}
                      </span>
                    </div>
                    
                    {/* Потрачено снизу */}
                    <div className="text-xs text-center mt-2">
                      <span className={`font-medium ${isOver ? 'text-red-600' : ''}`}>
                        ${data.spent.toFixed(0)}
                      </span>
                      <span className="text-muted-foreground ml-1">
                        ({usage.toFixed(0)}%)
                      </span>
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
