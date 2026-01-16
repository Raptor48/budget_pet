"use client";

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { PiggyBank, PiggyBankCreate, PiggyBankUpdate } from '@/types/api';
import { financeApi } from '@/lib/api';
import { Plus, Edit, Palette, Target } from 'lucide-react';
import * as LucideIcons from 'lucide-react';
import { format } from 'date-fns';

// Predefined colors for quick selection
const COLOR_OPTIONS = [
  { value: '#3b82f6', label: 'Blue' },
  { value: '#ef4444', label: 'Red' },
  { value: '#10b981', label: 'Green' },
  { value: '#f59e0b', label: 'Orange' },
  { value: '#8b5cf6', label: 'Purple' },
  { value: '#ec4899', label: 'Pink' },
  { value: '#06b6d4', label: 'Cyan' },
  { value: '#84cc16', label: 'Lime' },
];

// Common icons from lucide-react (must match actual icon names)
const ICON_OPTIONS = [
  { value: 'PiggyBank', label: 'Piggy Bank' },
  { value: 'Target', label: 'Target' },
  { value: 'Plane', label: 'Plane' },
  { value: 'Car', label: 'Car' },
  { value: 'Home', label: 'Home' },
  { value: 'Heart', label: 'Heart' },
  { value: 'Gift', label: 'Gift' },
  { value: 'ShoppingBag', label: 'Shopping' },
  { value: 'GraduationCap', label: 'Education' },
  { value: 'Dumbbell', label: 'Fitness' },
  { value: 'Camera', label: 'Camera' },
  { value: 'Gamepad2', label: 'Gaming' },
  { value: 'DollarSign', label: 'Money' },
  { value: 'TrendingUp', label: 'Growth' },
  { value: 'Briefcase', label: 'Business' },
  { value: 'Smile', label: 'Happy' },
];

interface PiggyBankFormProps {
  piggy?: PiggyBank;
  onSuccess: () => void;
  trigger?: React.ReactNode;
}

export function PiggyBankForm({ piggy, onSuccess, trigger }: PiggyBankFormProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    name: piggy?.name || '',
    target_amount_cents: piggy ? (piggy.target_amount_cents / 100).toFixed(2) : '',
    current_amount_cents: piggy ? (piggy.current_amount_cents / 100).toFixed(2) : '0.00',
    color: piggy?.color || '#3b82f6',
    icon: piggy?.icon || 'PiggyBank',
    description: piggy?.description || '',
    deadline: piggy?.deadline ? format(new Date(piggy.deadline), 'yyyy-MM-dd') : '',
    is_active: piggy?.is_active ?? true,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const data: PiggyBankCreate | PiggyBankUpdate = {
        name: formData.name,
        target_amount_cents: Math.round((parseFloat(String(formData.target_amount_cents)) || 0) * 100),
        current_amount_cents: Math.round((parseFloat(String(formData.current_amount_cents)) || 0) * 100),
        color: formData.color,
        icon: formData.icon || null,
        description: formData.description || null,
        deadline: formData.deadline || null,
        is_active: formData.is_active,
      };

      if (piggy) {
        await financeApi.updatePiggyBank(piggy.id, data as PiggyBankUpdate);
      } else {
        await financeApi.createPiggyBank(data as PiggyBankCreate);
      }

      setOpen(false);
      onSuccess();
    } catch (error) {
      console.error('Error saving piggy bank:', error);
      alert('Failed to save piggy bank. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const defaultTrigger = piggy ? (
    <Button size="sm" variant="outline">
      <Edit className="h-4 w-4 mr-1" />
      Edit
    </Button>
  ) : (
    <Button>
      <Plus className="h-4 w-4 mr-1" />
      New Goal
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || defaultTrigger}
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{piggy ? 'Edit Goal' : 'Create New Goal'}</DialogTitle>
          <DialogDescription>
            {piggy ? 'Update your savings goal' : 'Set a new savings goal and track your progress'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="name">Goal Name</Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., Vacation, New Car, Emergency Fund"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="target_amount">Target Amount ($)</Label>
              <Input
                id="target_amount"
                type="number"
                step="0.01"
                min="0"
                value={formData.target_amount_cents}
                onChange={(e) => setFormData({ ...formData, target_amount_cents: e.target.value })}
                required
              />
            </div>
            <div>
              <Label htmlFor="current_amount">Current Amount ($)</Label>
              <Input
                id="current_amount"
                type="number"
                step="0.01"
                min="0"
                value={formData.current_amount_cents}
                onChange={(e) => setFormData({ ...formData, current_amount_cents: e.target.value })}
              />
            </div>
          </div>

          <div>
            <Label htmlFor="description">Description (Optional)</Label>
            <Input
              id="description"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Add notes about this goal..."
            />
          </div>

          <div>
            <Label htmlFor="deadline">Deadline (Optional)</Label>
            <Input
              id="deadline"
              type="date"
              value={formData.deadline}
              onChange={(e) => setFormData({ ...formData, deadline: e.target.value })}
            />
          </div>

          <div>
            <Label className="flex items-center gap-2 mb-2">
              <Palette className="h-4 w-4" />
              Color
            </Label>
            <div className="grid grid-cols-4 gap-2">
              {COLOR_OPTIONS.map((color) => (
                <button
                  key={color.value}
                  type="button"
                  onClick={() => setFormData({ ...formData, color: color.value })}
                  className={`h-10 rounded-md border-2 transition-all ${
                    formData.color === color.value ? 'border-primary ring-2 ring-primary' : 'border-border'
                  }`}
                  style={{ backgroundColor: color.value }}
                  title={color.label}
                />
              ))}
            </div>
            <Input
              type="text"
              value={formData.color}
              onChange={(e) => setFormData({ ...formData, color: e.target.value })}
              placeholder="#3b82f6"
              className="mt-2"
            />
          </div>

          <div>
            <Label className="flex items-center gap-2 mb-2">
              <Target className="h-4 w-4" />
              Icon
            </Label>
            <div className="grid grid-cols-4 gap-2 max-h-48 overflow-y-auto">
              {ICON_OPTIONS.map((icon) => {
                // Get icon component from lucide-react
                const IconComponent = (LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string }>>)[icon.value] || Target;
                return (
                  <button
                    key={icon.value}
                    type="button"
                    onClick={() => setFormData({ ...formData, icon: icon.value })}
                    className={`h-12 rounded-md border-2 transition-all flex flex-col items-center justify-center gap-1 ${
                      formData.icon === icon.value ? 'border-primary ring-2 ring-primary bg-primary/10' : 'border-border hover:bg-muted'
                    }`}
                    title={icon.label}
                  >
                    <IconComponent className="h-4 w-4" />
                    <span className="text-xs">{icon.label}</span>
                  </button>
                );
              })}
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

          <div className="flex justify-end space-x-2 pt-4 border-t">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? 'Saving...' : (piggy ? 'Update' : 'Create')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
