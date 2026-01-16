"use client";

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { RecurringExpense, RecurringExpenseCreate, RecurringExpenseUpdate } from '@/types/api';
import { financeApi, limitsApi } from '@/lib/api';
import { Plus, Edit } from 'lucide-react';

interface RecurringExpenseFormProps {
  expense?: RecurringExpense;
  onSuccess: () => void;
  trigger?: React.ReactNode;
}

export function RecurringExpenseForm({ expense, onSuccess, trigger }: RecurringExpenseFormProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    name: expense?.name || '',
    category_name: expense?.category_name || '',
    monthly_amount_cents: expense ? (expense.monthly_amount_cents / 100).toFixed(2) : '',
    due_day: expense?.due_day || '',
    is_active: expense?.is_active ?? true,
  });

  // Load categories
  const { data: limits } = useQuery({
    queryKey: ["limits"],
    queryFn: () => limitsApi.getAll(),
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const data = {
        ...formData,
        monthly_amount_cents: Math.round((parseFloat(String(formData.monthly_amount_cents)) || 0) * 100),
        due_day: formData.due_day ? parseInt(String(formData.due_day)) : undefined,
      };

      if (expense) {
        await financeApi.updateRecurringExpense(expense.id, data as RecurringExpenseUpdate);
      } else {
        await financeApi.createRecurringExpense(data as RecurringExpenseCreate);
      }

      setOpen(false);
      onSuccess();
    } catch (error) {
      console.error('Error saving recurring expense:', error);
    } finally {
      setLoading(false);
    }
  };

  const defaultTrigger = expense ? (
    <Button size="sm" variant="outline">
      <Edit className="h-4 w-4 mr-1" />
      Edit
    </Button>
  ) : (
    <Button>
      <Plus className="h-4 w-4 mr-1" />
      Add Subscription
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || defaultTrigger}
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{expense ? 'Edit Recurring Expense' : 'Add New Recurring Expense'}</DialogTitle>
          <DialogDescription>
            {expense ? 'Update subscription information' : 'Enter subscription details (Netflix, Spotify, etc.)'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., Netflix, Spotify, Gym"
              required
            />
          </div>
          <div>
            <Label htmlFor="category_name">Category</Label>
            <Select
              value={formData.category_name}
              onValueChange={(value) => setFormData({ ...formData, category_name: value })}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select category" />
              </SelectTrigger>
              <SelectContent>
                {limits?.map((limit) => (
                  <SelectItem key={limit.category} value={limit.category}>
                    {limit.category}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground mt-1">
              Categories are managed on the Categories page
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="monthly_amount">Monthly Amount ($)</Label>
              <Input
                id="monthly_amount"
                type="number"
                step="0.01"
                min="0"
                value={formData.monthly_amount_cents}
                onChange={(e) => setFormData({ ...formData, monthly_amount_cents: e.target.value })}
                required
              />
            </div>
            <div>
              <Label htmlFor="due_day">Due Day (1-31)</Label>
              <Input
                id="due_day"
                type="number"
                min="1"
                max="31"
                value={formData.due_day}
                onChange={(e) => setFormData({ ...formData, due_day: e.target.value })}
                placeholder="Day of month"
              />
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <input
              type="checkbox"
              id="is_active"
              checked={formData.is_active}
              onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
              className="rounded"
            />
            <Label htmlFor="is_active" className="cursor-pointer">Active</Label>
          </div>
          <div className="flex justify-end space-x-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? 'Saving...' : (expense ? 'Update' : 'Create')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
