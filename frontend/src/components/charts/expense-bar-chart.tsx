"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { ReportItem } from '@/types/api';

interface ExpenseBarChartProps {
  data: Record<string, ReportItem>;
}

export function ExpenseBarChart({ data }: ExpenseBarChartProps) {
  const chartData = Object.entries(data).map(([category, item]) => ({
    category: category.length > 10 ? category.substring(0, 10) + '...' : category,
    fullCategory: category,
    spent: item.spent,
    budget: item.budget,
    remaining: item.remaining,
  }));

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        No expense data available
      </div>
    );
  }

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            dataKey="category"
            angle={-45}
            textAnchor="end"
            height={80}
            interval={0}
          />
          <YAxis />
          <Tooltip
            formatter={(value: number, name: string) => [
              `$${value.toFixed(2)}`,
              name === 'spent' ? 'Spent' : name === 'budget' ? 'Budget' : 'Remaining'
            ]}
            labelFormatter={(label) => {
              const item = chartData.find(d => d.category === label);
              return item?.fullCategory || label;
            }}
          />
          <Bar dataKey="spent" fill="#8884d8" name="spent" />
          <Bar dataKey="budget" fill="#82ca9d" name="budget" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
