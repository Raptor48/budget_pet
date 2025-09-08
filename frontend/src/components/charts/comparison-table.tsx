"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface ComparisonTableProps {
  data: Array<{
    category: string;
    currentMonth: number;
    previousMonth: number;
    change: number;
  }>;
  currentMonthName: string;
  previousMonthName: string;
}

export function ComparisonTable({ data, currentMonthName, previousMonthName }: ComparisonTableProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <div className="text-center">
          <p>No comparison data available</p>
          <p className="text-sm mt-2">Make sure both months have expense data</p>
        </div>
      </div>
    );
  }

  const formatCurrency = (amount: number) => `$${amount.toFixed(2)}`;

  const getChangeIcon = (change: number) => {
    if (change > 0) return <TrendingUp className="h-4 w-4 text-red-600" />;
    if (change < 0) return <TrendingDown className="h-4 w-4 text-green-600" />;
    return <Minus className="h-4 w-4 text-gray-500" />;
  };

  const getChangeColor = (change: number) => {
    if (change > 0) return "text-green-600 bg-green-50 border-green-200";
    if (change < 0) return "text-red-600 bg-red-50 border-red-200";
    return "text-gray-600 bg-gray-50 border-gray-200";
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="grid grid-cols-4 gap-4 text-sm font-medium text-muted-foreground border-b pb-2">
        <div>Category</div>
        <div className="text-center">{previousMonthName}</div>
        <div className="text-center">{currentMonthName}</div>
        <div className="text-center">Change</div>
      </div>

      {/* Data rows */}
      <div className="space-y-3">
        {data.map((item) => (
          <div key={item.category} className="grid grid-cols-4 gap-4 items-center py-3 px-4 rounded-lg hover:bg-muted/50 transition-colors">
            {/* Category name */}
            <div className="font-medium">{item.category}</div>
            
            {/* Previous month amount */}
            <div className="text-center">
              <div className="text-lg font-semibold text-orange-600">
                {formatCurrency(item.previousMonth)}
              </div>
            </div>
            
            {/* Current month amount */}
            <div className="text-center">
              <div className="text-lg font-semibold text-blue-600">
                {formatCurrency(item.currentMonth)}
              </div>
            </div>
            
            {/* Change */}
            <div className="text-center">
              <Badge 
                variant="outline" 
                className={`${getChangeColor(item.change)} flex items-center gap-1 justify-center`}
              >
                {getChangeIcon(item.change)}
                <span className="font-medium">
                  {item.change > 0 ? '+' : ''}{item.change.toFixed(1)}%
                </span>
              </Badge>
            </div>
          </div>
        ))}
      </div>

      {/* Summary */}
      <Card className="mt-6">
        <CardContent className="pt-6">
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <div className="text-2xl font-bold text-orange-600">
                {formatCurrency(data.reduce((sum, item) => sum + item.previousMonth, 0))}
              </div>
              <div className="text-sm text-muted-foreground">Total {previousMonthName}</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-blue-600">
                {formatCurrency(data.reduce((sum, item) => sum + item.currentMonth, 0))}
              </div>
              <div className="text-sm text-muted-foreground">Total {currentMonthName}</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-gray-600">
                {formatCurrency(data.reduce((sum, item) => sum + item.currentMonth, 0) - data.reduce((sum, item) => sum + item.previousMonth, 0))}
              </div>
              <div className="text-sm text-muted-foreground">Difference</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
