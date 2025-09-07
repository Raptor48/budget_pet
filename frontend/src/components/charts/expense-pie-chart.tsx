"use client";

import { useState } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { ReportItem } from '@/types/api';

interface ExpensePieChartProps {
  data: Record<string, ReportItem>;
}

const COLORS = [
  '#0088FE', '#00C49F', '#FFBB28', '#FF8042',
  '#8884D8', '#82CA9D', '#FFC658', '#FF7C7C',
  '#8DD1E1', '#D084D0', '#87CEEB', '#DEB887'
];

export function ExpensePieChart({ data }: ExpensePieChartProps) {
  const [hoveredCategory, setHoveredCategory] = useState<string | null>(null);

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

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0];
      const percentage = ((data.value / chartData.reduce((sum, item) => sum + item.value, 0)) * 100).toFixed(1);
      return (
        <div className="bg-background border border-border rounded-lg p-3 shadow-lg">
          <p className="font-medium">{data.name}</p>
          <p className="text-sm text-muted-foreground">
            ${data.value.toFixed(2)} ({percentage}%)
          </p>
        </div>
      );
    }
    return null;
  };

  const CustomLegend = ({ payload }: any) => {
    return (
      <div className="flex flex-wrap gap-4 justify-center mt-4">
        {payload?.map((entry: any, index: number) => (
          <div
            key={entry.value}
            className={`flex items-center gap-2 cursor-pointer transition-all duration-200 ${
              hoveredCategory === entry.value 
                ? 'opacity-100 scale-105' 
                : 'opacity-70 hover:opacity-100'
            }`}
            onMouseEnter={() => setHoveredCategory(entry.value)}
            onMouseLeave={() => setHoveredCategory(null)}
          >
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-sm font-medium">{entry.value}</span>
          </div>
        ))}
      </div>
    );
  };

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
            onMouseEnter={(data) => setHoveredCategory(data.name)}
            onMouseLeave={() => setHoveredCategory(null)}
          >
            {chartData.map((entry, index) => (
              <Cell 
                key={`cell-${index}`} 
                fill={entry.fill}
                stroke={hoveredCategory === entry.name ? '#fff' : 'none'}
                strokeWidth={hoveredCategory === entry.name ? 2 : 0}
                style={{
                  filter: hoveredCategory && hoveredCategory !== entry.name ? 'opacity(0.3)' : 'opacity(1)',
                  transition: 'all 0.2s ease-in-out'
                }}
              />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
          <Legend content={<CustomLegend />} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
