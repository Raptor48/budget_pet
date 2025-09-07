"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { ReportItem } from '@/types/api';

interface ExpenseChartProps {
  data: Record<string, ReportItem>;
}

const COLORS = [
  '#0088FE', '#00C49F', '#FFBB28', '#FF8042',
  '#8884D8', '#82CA9D', '#FFC658', '#FF7C7C',
  '#8DD1E1', '#D084D0', '#87CEEB', '#DEB887'
];

export function ExpenseChart({ data }: ExpenseChartProps) {
  const chartData = Object.entries(data).map(([category, item], index) => ({
    name: category,
    value: item.spent,
    fill: COLORS[index % COLORS.length],
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
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            outerRadius={80}
            fill="#8884d8"
            dataKey="value"
            label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
          >
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.fill} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value: number) => [`$${value.toFixed(2)}`, 'Spent']}
          />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
