"use client";

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { CreditCard, CreditCardCreate, CreditCardUpdate } from '@/types/api';
import { financeApi } from '@/lib/api';
import { Plus, Edit } from 'lucide-react';

interface CardFormProps {
  card?: CreditCard;
  onSuccess: () => void;
  trigger?: React.ReactNode;
}

export function CardForm({ card, onSuccess, trigger }: CardFormProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    name: card?.name || '',
    category_name: card?.category_name || '',
    apr_percent: card?.apr_percent || '',
    current_balance_cents: card?.current_balance_cents || '',
    credit_limit_cents: card?.credit_limit_cents || '',
    due_date: card?.due_date || '',
    min_payment_cents: card?.min_payment_cents || '',
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const data = {
        ...formData,
        apr_percent: parseFloat(String(formData.apr_percent)) || 0,
        current_balance_cents: Math.round((parseFloat(String(formData.current_balance_cents)) || 0) * 100),
        credit_limit_cents: formData.credit_limit_cents ? Math.round(parseFloat(String(formData.credit_limit_cents)) * 100) : undefined,
        min_payment_cents: Math.round((parseFloat(String(formData.min_payment_cents)) || 0) * 100),
        due_date: formData.due_date || undefined,
      };

      if (card) {
        await financeApi.updateCard(card.id, data as CreditCardUpdate);
      } else {
        await financeApi.createCard(data as CreditCardCreate);
      }

      setOpen(false);
      onSuccess();
    } catch (error) {
      console.error('Error saving credit card:', error);
    } finally {
      setLoading(false);
    }
  };

  const defaultTrigger = card ? (
    <Button size="sm" variant="outline">
      <Edit className="h-4 w-4 mr-1" />
      Edit
    </Button>
  ) : (
    <Button>
      <Plus className="h-4 w-4 mr-1" />
      Add Card
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || defaultTrigger}
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{card ? 'Edit Credit Card' : 'Add New Credit Card'}</DialogTitle>
          <DialogDescription>
            {card ? 'Update credit card information' : 'Enter credit card details'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="name">Card Name</Label>
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
              <Label htmlFor="due_date">Due Date</Label>
              <Input
                id="due_date"
                type="date"
                value={formData.due_date}
                onChange={(e) => setFormData({ ...formData, due_date: e.target.value })}
                placeholder="Select due date"
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
              <Label htmlFor="credit_limit">Credit Limit ($)</Label>
              <Input
                id="credit_limit"
                type="number"
                step="0.01"
                min="0"
                value={formData.credit_limit_cents}
                onChange={(e) => setFormData({ ...formData, credit_limit_cents: e.target.value })}
              />
            </div>
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
          <div className="flex justify-end space-x-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? 'Saving...' : (card ? 'Update' : 'Create')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
