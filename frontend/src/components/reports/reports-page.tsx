"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { reportsApi } from "@/lib/api";
import { ExpensePieChart } from "@/components/charts/expense-pie-chart";
import { ExpenseBarChart } from "@/components/charts/expense-bar-chart";
import { DivergingBarChart } from "@/components/charts/diverging-bar-chart";
import { format } from "date-fns";
import { PieChart, BarChart3, TrendingUp, Calendar } from "lucide-react";

export function ReportsPage() {
  const [selectedMonth, setSelectedMonth] = useState(format(new Date(), "yyyy-MM"));
  const [compareMonth, setCompareMonth] = useState("none");

  // Получаем отчет за текущий месяц
  const { data: report, isLoading } = useQuery({
    queryKey: ["report", selectedMonth, compareMonth],
    queryFn: () => reportsApi.getReport(selectedMonth, compareMonth === "none" ? undefined : compareMonth),
  });

  // Генерируем список месяцев для выбора
  const generateMonths = () => {
    const months = [];
    const currentDate = new Date();
    for (let i = 0; i < 12; i++) {
      const date = new Date(currentDate.getFullYear(), currentDate.getMonth() - i, 1);
      const value = format(date, "yyyy-MM");
      const label = format(date, "MMMM yyyy");
      months.push({ value, label });
    }
    return months;
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Reports & Analytics</h1>
        <p>Loading reports...</p>
      </div>
    );
  }

  const totalBudget = Object.values(report?.report || {}).reduce(
    (sum, item) => sum + item.budget, 0
  );
  const totalSpent = Object.values(report?.report || {}).reduce(
    (sum, item) => sum + item.spent, 0
  );
  const totalRemaining = Object.values(report?.report || {}).reduce(
    (sum, item) => sum + item.remaining, 0
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Reports & Analytics</h1>
          <p className="text-muted-foreground">
            Detailed insights into your spending patterns
          </p>
        </div>
        <Badge variant="secondary" className="gap-2">
          <Calendar className="h-4 w-4" />
          {format(new Date(selectedMonth + "-15"), "MMMM yyyy")}
        </Badge>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle>Report Period</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="grid gap-2">
              <label className="text-sm font-medium">Primary Month</label>
              <Select value={selectedMonth} onValueChange={setSelectedMonth}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {generateMonths().map((month) => (
                    <SelectItem key={month.value} value={month.value}>
                      {month.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium">Compare with (optional)</label>
              <Select value={compareMonth} onValueChange={(value) => setCompareMonth(value === "none" ? "" : value)}>
                <SelectTrigger>
                  <SelectValue placeholder="Select month to compare" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  {generateMonths().map((month) => (
                    <SelectItem key={month.value} value={month.value}>
                      {month.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Budget</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${totalBudget.toFixed(2)}</div>
            <p className="text-xs text-muted-foreground">
              Monthly allocation
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Spent</CardTitle>
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${totalSpent.toFixed(2)}</div>
            <p className="text-xs text-muted-foreground">
              {(totalBudget > 0 ? (totalSpent / totalBudget) * 100 : 0).toFixed(1)}% of budget
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Remaining</CardTitle>
            <PieChart className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${totalRemaining.toFixed(2)}</div>
            <p className="text-xs text-muted-foreground">
              Available funds
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Charts */}
      <Tabs defaultValue="pie" className="space-y-4">
        <TabsList>
          <TabsTrigger value="pie">Pie Chart</TabsTrigger>
          <TabsTrigger value="bar">Bar Chart</TabsTrigger>
          <TabsTrigger value="comparison">Comparison</TabsTrigger>
        </TabsList>

        <TabsContent value="pie">
          <Card>
            <CardHeader>
              <CardTitle>Expense Distribution</CardTitle>
              <CardDescription>
                Breakdown of spending by category
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ExpensePieChart data={report?.report || {}} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="bar">
          <Card>
            <CardHeader>
              <CardTitle>Budget vs Actual</CardTitle>
              <CardDescription>
                Comparison of budgeted vs actual spending
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ExpenseBarChart data={report?.report || {}} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="comparison">
          <Card>
            <CardHeader>
              <CardTitle>Month-over-Month Comparison</CardTitle>
              <CardDescription>
                {compareMonth && compareMonth !== "" && compareMonth !== "none"
                  ? `Comparing ${format(new Date(selectedMonth + "-15"), "MMMM yyyy")} vs ${format(new Date(compareMonth + "-15"), "MMMM yyyy")}`
                  : "Select a comparison month to see differences"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {compareMonth && compareMonth !== "" && compareMonth !== "none" && report?.comparison ? (
                <DivergingBarChart
                  data={Object.entries(report.report || {}).map(([category, currentData]) => {
                    // Получаем данные для текущего месяца
                    const currentSpent = currentData?.spent || 0;
                    
                    // Получаем данные для предыдущего месяца из comparison
                    const previousSpent = report.comparison?.[category] || 0;
                    
                    // Вычисляем изменение в процентах
                    const change = previousSpent > 0 
                      ? ((currentSpent - previousSpent) / previousSpent) * 100 
                      : currentSpent > 0 ? 100 : 0;
                    
                    return {
                      category,
                      currentMonth: currentSpent,
                      previousMonth: previousSpent,
                      change: change,
                    };
                  }).filter(item => item.currentMonth > 0 || item.previousMonth > 0)} // Показываем только категории с тратами
                  currentMonthName={format(new Date(selectedMonth + "-15"), "MMMM yyyy")}
                  previousMonthName={format(new Date(compareMonth + "-15"), "MMMM yyyy")}
                />
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  Select a comparison month to view changes
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Detailed Breakdown */}
      <Card>
        <CardHeader>
          <CardTitle>Detailed Category Breakdown</CardTitle>
          <CardDescription>
            Individual category performance
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {Object.entries(report?.report || {}).map(([category, data]) => {
              const usage = data.budget > 0 ? (data.spent / data.budget) * 100 : 0;
              const isOver = data.remaining < 0;

              return (
                <div key={category} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{category}</span>
                    <div className="text-right text-sm">
                      <div>${data.spent.toFixed(2)} / ${data.budget.toFixed(2)}</div>
                      <div className="text-muted-foreground">
                        {usage.toFixed(1)}% used
                      </div>
                    </div>
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
                    <span>Budget: ${data.budget.toFixed(2)}</span>
                    <span>Remaining: ${data.remaining.toFixed(2)}</span>
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
