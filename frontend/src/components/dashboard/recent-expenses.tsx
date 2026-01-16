"use client";

import { useQuery } from "@tanstack/react-query";
import { expensesApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { safeFormatDate } from "@/lib/date-utils";

interface RecentExpensesProps {
  month: string;
}

export function RecentExpenses({ month }: RecentExpensesProps) {
  const { data: expenses, isLoading } = useQuery({
    queryKey: ["expenses", month],
    queryFn: () => expensesApi.getAll(month),
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="flex items-center space-x-4 animate-pulse">
            <div className="w-3 h-3 bg-muted rounded-full"></div>
            <div className="flex-1 space-y-1">
              <div className="h-4 bg-muted rounded w-3/4"></div>
              <div className="h-3 bg-muted rounded w-1/2"></div>
            </div>
            <div className="h-4 bg-muted rounded w-16"></div>
          </div>
        ))}
      </div>
    );
  }

  if (!expenses || expenses.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No expenses found for this month
      </div>
    );
  }

  // API уже возвращает расходы отсортированные по date DESC, id DESC (от новых к старым)
  // Берем первые 10 самых новых расходов
  const recentExpenses = expenses.slice(0, 10);

  return (
    <div className="space-y-3">
      {recentExpenses.map((expense) => (
        <div key={expense.id} className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-2 h-2 bg-primary rounded-full"></div>
            <div>
              <p className="font-medium text-sm">{expense.category}</p>
              <p className="text-xs text-muted-foreground">
                {safeFormatDate(expense.date, "MMM dd, yyyy")}
              </p>
            </div>
          </div>
          <Badge variant="secondary" className="font-mono">
            ${expense.amount.toFixed(2)}
          </Badge>
        </div>
      ))}
    </div>
  );
}
