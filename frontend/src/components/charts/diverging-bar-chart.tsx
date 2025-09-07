"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

interface DivergingBarChartProps {
  data: Array<{
    category: string;
    currentMonth: number;
    previousMonth: number;
    change: number;
  }>;
  currentMonthName: string;
  previousMonthName: string;
}

export function DivergingBarChart({ data, currentMonthName, previousMonthName }: DivergingBarChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        No comparison data available
      </div>
    );
  }

  // Подготавливаем данные для diverging chart
  const chartData = data.map(item => ({
    category: item.category,
    // Для diverging chart: отрицательные значения идут влево, положительные вправо
    currentValue: item.currentMonth,
    previousValue: -Math.abs(item.previousMonth), // Отрицательное значение для левой стороны
    change: item.change,
  }));

  console.log('DivergingBarChart data:', { data, chartData }); // Debug log

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      const currentAmount = Math.abs(data.currentValue);
      const previousAmount = Math.abs(data.previousValue);
      
      return (
        <div className="bg-background border border-border rounded-lg p-3 shadow-lg">
          <p className="font-medium mb-2">{label}</p>
          <div className="space-y-1 text-sm">
            <p className="text-blue-600">
              {currentMonthName}: ${currentAmount.toFixed(2)}
            </p>
            <p className="text-orange-600">
              {previousMonthName}: ${previousAmount.toFixed(2)}
            </p>
            <p className={`font-medium ${data.change > 0 ? 'text-green-600' : data.change < 0 ? 'text-red-600' : 'text-gray-600'}`}>
              Change: {data.change > 0 ? '+' : ''}{data.change.toFixed(1)}%
            </p>
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="h-96">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={chartData}
          layout="horizontal"
          margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis 
            type="number" 
            domain={['dataMin', 'dataMax']}
            tickFormatter={(value) => `$${Math.abs(value).toFixed(0)}`}
            axisLine={false}
            tickLine={false}
          />
          <YAxis 
            type="category" 
            dataKey="category" 
            width={120}
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 12 }}
          />
          <Tooltip content={<CustomTooltip />} />
          
          {/* Текущий месяц - правая сторона (положительные значения) */}
          <Bar 
            dataKey="currentValue" 
            fill="#3B82F6"
            radius={[0, 4, 4, 0]}
            name={currentMonthName}
          />
          
          {/* Предыдущий месяц - левая сторона (отрицательные значения) */}
          <Bar 
            dataKey="previousValue" 
            fill="#F97316"
            radius={[4, 0, 0, 4]}
            name={previousMonthName}
          />
        </BarChart>
      </ResponsiveContainer>
      
      {/* Легенда */}
      <div className="flex justify-center gap-6 mt-4">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-orange-500 rounded"></div>
          <span className="text-sm font-medium">{previousMonthName}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-blue-500 rounded"></div>
          <span className="text-sm font-medium">{currentMonthName}</span>
        </div>
      </div>
    </div>
  );
}
