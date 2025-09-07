"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface ExpenseBarChartProps {
  data: Record<string, { spent: number; budget: number; remaining: number; rolled_over: number }>;
}

export function ExpenseBarChart({ data }: ExpenseBarChartProps) {
  // Преобразуем данные для диаграммы
  const chartData = Object.entries(data).map(([category, values]) => ({
    category,
    spent: values.spent,
    budget: values.budget,
    remaining: values.remaining,
    usage: values.budget > 0 ? (values.spent / values.budget) * 100 : 0,
  }));

  // Сортируем по потраченной сумме (по убыванию)
  chartData.sort((a, b) => b.spent - a.spent);

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-background border border-border rounded-lg p-3 shadow-lg">
          <p className="font-medium">{label}</p>
          <div className="space-y-1 text-sm">
            <p className="text-primary">
              Spent: <span className="font-mono">${data.spent.toFixed(2)}</span>
            </p>
            <p className="text-muted-foreground">
              Budget: <span className="font-mono">${data.budget.toFixed(2)}</span>
            </p>
            <p className={data.remaining >= 0 ? "text-green-600" : "text-red-600"}>
              Remaining: <span className="font-mono">${data.remaining.toFixed(2)}</span>
            </p>
            <p className="text-blue-600">
              Usage: <span className="font-mono">{data.usage.toFixed(1)}%</span>
            </p>
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="h-96 w-full bg-transparent">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={chartData}
          margin={{
            top: 20,
            right: 30,
            left: 20,
            bottom: 60,
          }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--muted))" opacity={0.2} />
          <XAxis 
            dataKey="category" 
            angle={-45}
            textAnchor="end"
            height={80}
            fontSize={12}
            fontWeight="bold"
            className="text-white font-bold"
            tick={{ fill: 'white', fontWeight: 'bold' }}
          />
          <YAxis 
            fontSize={12}
            className="text-muted-foreground"
            tickFormatter={(value) => `$${value}`}
          />
          <Tooltip content={<CustomTooltip />} />
          <Bar 
            dataKey="spent" 
            fill="white" 
            stroke="hsl(var(--foreground))"
            strokeWidth={1}
            radius={[4, 4, 0, 0]}
            name="Spent"
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}