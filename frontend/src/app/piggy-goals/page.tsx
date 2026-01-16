"use client";

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AppLayout } from '@/components/layout/app-layout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { financeApi } from '@/lib/api';
import { formatCurrency } from '@/lib/utils';
import { PiggyBankCard } from './_components/piggy-bank-card';
import { PiggyBankForm } from './_components/piggy-bank-form';
import { Target, TrendingUp, CheckCircle2, Filter } from 'lucide-react';

type FilterType = 'all' | 'active' | 'completed' | 'overdue';
type SortType = 'progress' | 'deadline' | 'amount' | 'name';

export default function PiggyGoalsPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<FilterType>('all');
  const [sort, setSort] = useState<SortType>('progress');

  const { data: piggyBanks = [], isLoading } = useQuery({
    queryKey: ['piggy-banks', filter === 'all' ? false : filter === 'active'],
    queryFn: () => financeApi.getPiggyBanks(filter === 'all' ? false : filter === 'active'),
  });

  const handleUpdate = () => {
    queryClient.invalidateQueries({ queryKey: ['piggy-banks'] });
  };

  // Filter and sort piggy banks
  const filteredAndSorted = piggyBanks
    .filter((piggy) => {
      if (filter === 'all') return true;
      if (filter === 'active') return piggy.is_active && piggy.current_amount_cents < piggy.target_amount_cents;
      if (filter === 'completed') return piggy.current_amount_cents >= piggy.target_amount_cents;
      if (filter === 'overdue') {
        if (!piggy.deadline) return false;
        const deadline = new Date(piggy.deadline);
        return deadline < new Date() && piggy.current_amount_cents < piggy.target_amount_cents;
      }
      return true;
    })
    .sort((a, b) => {
      if (sort === 'progress') {
        const progressA = a.target_amount_cents > 0 ? (a.current_amount_cents / a.target_amount_cents) * 100 : 0;
        const progressB = b.target_amount_cents > 0 ? (b.current_amount_cents / b.target_amount_cents) * 100 : 0;
        return progressB - progressA; // Descending
      }
      if (sort === 'deadline') {
        if (!a.deadline && !b.deadline) return 0;
        if (!a.deadline) return 1;
        if (!b.deadline) return -1;
        return new Date(a.deadline).getTime() - new Date(b.deadline).getTime();
      }
      if (sort === 'amount') {
        return b.target_amount_cents - a.target_amount_cents; // Descending
      }
      if (sort === 'name') {
        return a.name.localeCompare(b.name);
      }
      return 0;
    });

  // Calculate statistics
  const stats = {
    total: piggyBanks.length,
    active: piggyBanks.filter(p => p.is_active && p.current_amount_cents < p.target_amount_cents).length,
    completed: piggyBanks.filter(p => p.current_amount_cents >= p.target_amount_cents).length,
    totalSaved: piggyBanks.reduce((sum, p) => sum + p.current_amount_cents, 0),
    totalTarget: piggyBanks.reduce((sum, p) => sum + p.target_amount_cents, 0),
    averageProgress: piggyBanks.length > 0
      ? piggyBanks.reduce((sum, p) => {
          const progress = p.target_amount_cents > 0 ? (p.current_amount_cents / p.target_amount_cents) * 100 : 0;
          return sum + progress;
        }, 0) / piggyBanks.length
      : 0,
  };

  if (isLoading) {
    return (
      <AppLayout>
        <div className="space-y-6">
          <h1 className="text-3xl font-bold">Piggy & Goals</h1>
          <p>Loading goals...</p>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Piggy & Goals</h1>
            <p className="text-muted-foreground">
              Track your savings goals and financial targets
            </p>
          </div>
          <PiggyBankForm onSuccess={handleUpdate} />
        </div>

        {/* Statistics Cards */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Saved</CardTitle>
              <TrendingUp className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatCurrency(stats.totalSaved)}</div>
              <p className="text-xs text-muted-foreground">
                of {formatCurrency(stats.totalTarget)} target
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Active Goals</CardTitle>
              <Target className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.active}</div>
              <p className="text-xs text-muted-foreground">
                out of {stats.total} total goals
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Completed</CardTitle>
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.completed}</div>
              <p className="text-xs text-muted-foreground">
                goals achieved
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Avg Progress</CardTitle>
              <Target className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.averageProgress.toFixed(0)}%</div>
              <p className="text-xs text-muted-foreground">
                average completion
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Filters and Sort */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <Select value={filter} onValueChange={(value) => setFilter(value as FilterType)}>
              <SelectTrigger className="w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Goals</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="overdue">Overdue</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Select value={sort} onValueChange={(value) => setSort(value as SortType)}>
            <SelectTrigger className="w-[150px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="progress">By Progress</SelectItem>
              <SelectItem value="deadline">By Deadline</SelectItem>
              <SelectItem value="amount">By Amount</SelectItem>
              <SelectItem value="name">By Name</SelectItem>
            </SelectContent>
          </Select>
          <div className="ml-auto text-sm text-muted-foreground">
            Showing {filteredAndSorted.length} goal{filteredAndSorted.length !== 1 ? 's' : ''}
          </div>
        </div>

        {/* Goals Grid */}
        {filteredAndSorted.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <Target className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="text-lg font-semibold mb-2">No goals found</h3>
              <p className="text-muted-foreground text-center mb-4">
                {filter === 'all' 
                  ? "Create your first savings goal to get started!"
                  : `No ${filter} goals found. Try a different filter.`}
              </p>
              {filter === 'all' && (
                <PiggyBankForm onSuccess={handleUpdate} />
              )}
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {filteredAndSorted.map((piggy) => (
              <PiggyBankCard key={piggy.id} piggy={piggy} onUpdate={handleUpdate} />
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
