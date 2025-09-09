"use client";

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Income, IncomeCreate, IncomeUpdate } from '@/types/api';
import { financeApi } from '@/lib/api';
import { Plus, Edit } from 'lucide-react';

interface IncomeFormProps {
  income?: Income;
  onSuccess: () => void;
  trigger?: React.ReactNode;
}

export function IncomeForm({ income, onSuccess, trigger }: IncomeFormProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    person: income?.person || 'Denis' as 'Denis' | 'Taya',
    amount_dollars: income ? (income.amount_cents / 100) : 0, // Храним в долларах для удобства
    occurred_at: income?.occurred_at || new Date().toISOString().split('T')[0],
    note: income?.note || '',
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const data = {
        person: formData.person,
        amount_cents: Math.round(formData.amount_dollars * 100), // Конвертируем доллары в центы только здесь
        occurred_at: formData.occurred_at,
        note: formData.note || undefined,
      };

      if (income) {
        await financeApi.updateIncome(income.id, data as IncomeUpdate);
      } else {
        await financeApi.createIncome(data as IncomeCreate);
      }

      setOpen(false);
      onSuccess();
      
      // Сбрасываем форму только для создания нового дохода
      if (!income) {
        setFormData({
          person: 'Denis',
          amount_dollars: 0,
          occurred_at: new Date().toISOString().split('T')[0],
          note: '',
        });
      }
    } catch (error) {
      console.error('Error saving income:', error);
    } finally {
      setLoading(false);
    }
  };

  const defaultTrigger = income ? (
    <Button size="sm" variant="outline">
      <Edit className="h-4 w-4 mr-1" />
      Edit
    </Button>
  ) : (
    <Button>
      <Plus className="h-4 w-4 mr-1" />
      Add Income
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || defaultTrigger}
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{income ? 'Edit Income' : 'Add New Income'}</DialogTitle>
          <DialogDescription>
            {income ? 'Update income information' : 'Enter income details'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="person">Person</Label>
            <Select
              value={formData.person}
              onValueChange={(value: 'Denis' | 'Taya') => setFormData({ ...formData, person: value })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Denis">Denis</SelectItem>
                <SelectItem value="Taya">Taya</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="amount">Amount ($)</Label>
            <Input
              id="amount"
              type="number"
              step="0.01"
              min="0"
              value={formData.amount_dollars}
              onChange={(e) => setFormData({ ...formData, amount_dollars: parseFloat(e.target.value) || 0 })}
              required
            />
          </div>
          <div>
            <Label htmlFor="occurred_at">Date</Label>
            <Input
              id="occurred_at"
              type="date"
              value={formData.occurred_at}
              onChange={(e) => setFormData({ ...formData, occurred_at: e.target.value })}
              required
            />
          </div>
          <div>
            <Label htmlFor="note">Note (optional)</Label>
            <Input
              id="note"
              value={formData.note}
              onChange={(e) => setFormData({ ...formData, note: e.target.value })}
              placeholder="Description of income source"
            />
          </div>
          <div className="flex justify-end space-x-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? 'Saving...' : (income ? 'Update' : 'Create')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
