"use client";

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Loan, LoanCreate, LoanUpdate } from '@/types/api';
import { financeApi } from '@/lib/api';
import { Plus, Edit } from 'lucide-react';

interface LoanFormProps {
  loan?: Loan;
  onSuccess: () => void;
  trigger?: React.ReactNode;
}

export function LoanForm({ loan, onSuccess, trigger }: LoanFormProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    name: loan?.name || '',
    category_name: loan?.category_name || '',
    apr_percent: loan?.apr_percent || '',
    current_balance_cents: loan?.current_balance_cents || '',
    due_day: loan?.due_day || '',
    min_payment_cents: loan?.min_payment_cents || '',
    remaining_months: loan?.remaining_months || '',
    close_date: loan?.close_date || '',
  });

  // Calculate remaining months based on close date
  const calculateRemainingMonths = (closeDate: string): number | undefined => {
    if (!closeDate) return undefined;
    
    const today = new Date();
    const close = new Date(closeDate);
    
    if (close <= today) return 0;
    
    const yearDiff = close.getFullYear() - today.getFullYear();
    const monthDiff = close.getMonth() - today.getMonth();
    
    return yearDiff * 12 + monthDiff;
  };

  // Handle close date change
  const handleCloseDateChange = (closeDate: string) => {
    const remainingMonths = calculateRemainingMonths(closeDate);
    setFormData(prev => ({
      ...prev,
      close_date: closeDate,
      remaining_months: remainingMonths || ''
    }));
  };

  // Handle remaining months change (when close date is empty)
  const handleRemainingMonthsChange = (months: string) => {
    if (!formData.close_date) {
      setFormData(prev => ({
        ...prev,
        remaining_months: months
      }));
    }
  };


  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const data = {
        ...formData,
        apr_percent: parseFloat(String(formData.apr_percent)) || 0,
        current_balance_cents: Math.round((parseFloat(String(formData.current_balance_cents)) || 0) * 100),
        min_payment_cents: Math.round((parseFloat(String(formData.min_payment_cents)) || 0) * 100),
        due_day: formData.due_day ? parseInt(String(formData.due_day)) : undefined,
        remaining_months: formData.remaining_months ? parseInt(String(formData.remaining_months)) : undefined,
        close_date: formData.close_date || undefined,
      };

      if (loan) {
        await financeApi.updateLoan(loan.id, data as LoanUpdate);
      } else {
        await financeApi.createLoan(data as LoanCreate);
      }

      setOpen(false);
      onSuccess();
    } catch (error) {
      console.error('Error saving loan:', error);
    } finally {
      setLoading(false);
    }
  };

  const defaultTrigger = loan ? (
    <Button size="sm" variant="outline">
      <Edit className="h-4 w-4 mr-1" />
      Edit
    </Button>
  ) : (
    <Button>
      <Plus className="h-4 w-4 mr-1" />
      Add Loan
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || defaultTrigger}
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{loan ? 'Edit Loan' : 'Add New Loan'}</DialogTitle>
          <DialogDescription>
            {loan ? 'Update loan information' : 'Enter loan details'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="name">Loan Name</Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              required
            />
          </div>
          <div>
            <Label htmlFor="category_name">Category</Label>
            <Input
              id="category_name"
              value={formData.category_name}
              onChange={(e) => setFormData({ ...formData, category_name: e.target.value })}
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="apr_percent">APR (%)</Label>
              <Input
                id="apr_percent"
                type="number"
                step="0.001"
                min="0"
                max="100"
                value={formData.apr_percent}
                onChange={(e) => setFormData({ ...formData, apr_percent: e.target.value })}
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
                placeholder="Day of month for payment"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="current_balance">Current Balance ($)</Label>
              <Input
                id="current_balance"
                type="number"
                step="0.01"
                min="0"
                value={formData.current_balance_cents}
                onChange={(e) => setFormData({ ...formData, current_balance_cents: e.target.value })}
                required
              />
            </div>
            <div>
              <Label htmlFor="min_payment">Min Payment ($)</Label>
              <Input
                id="min_payment"
                type="number"
                step="0.01"
                min="0"
                value={formData.min_payment_cents}
                onChange={(e) => setFormData({ ...formData, min_payment_cents: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="remaining_months">Remaining Months</Label>
              <Input
                id="remaining_months"
                type="number"
                min="0"
                value={formData.remaining_months}
                onChange={(e) => handleRemainingMonthsChange(e.target.value)}
                disabled={!!formData.close_date}
                placeholder={formData.close_date ? "Auto-calculated from close date" : "Enter manually or set close date"}
              />
            </div>
            <div>
              <Label htmlFor="close_date">Close Date</Label>
              <Input
                id="close_date"
                type="date"
                value={formData.close_date}
                onChange={(e) => handleCloseDateChange(e.target.value)}
              />
            </div>
          </div>
          <div className="flex justify-end space-x-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? 'Saving...' : (loan ? 'Update' : 'Create')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
