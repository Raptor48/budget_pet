"use client";

import { useState } from 'react';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PiggyBank } from '@/types/v2';
import { piggyApi } from '@/lib/api';
import { confirm, notify } from '@/lib/notify';
import { formatCurrency } from '@/lib/utils';
import { format, differenceInMonths, isPast } from 'date-fns';
import { Trash2, Plus, CheckCircle2, Calendar, Target } from 'lucide-react';
import * as Icons from 'lucide-react';
import { PiggyBankForm } from './piggy-bank-form';

interface PiggyBankCardProps {
  piggy: PiggyBank;
  onUpdate: () => void;
}

export function PiggyBankCard({ piggy, onUpdate }: PiggyBankCardProps) {
  const [addAmountOpen, setAddAmountOpen] = useState(false);
  const [addAmount, setAddAmount] = useState('');
  const [loading, setLoading] = useState(false);

  const progress = piggy.target_amount_cents > 0 
    ? Math.min((piggy.current_amount_cents / piggy.target_amount_cents) * 100, 100)
    : 0;
  
  const remaining = Math.max(0, piggy.target_amount_cents - piggy.current_amount_cents);
  const isCompleted = piggy.current_amount_cents >= piggy.target_amount_cents;
  
  // Calculate monthly contribution needed
  let monthlyNeeded = 0;
  let monthsRemaining = 0;
  if (piggy.deadline && !isCompleted) {
    const deadline = new Date(piggy.deadline);
    monthsRemaining = Math.max(1, differenceInMonths(deadline, new Date()));
    monthlyNeeded = Math.ceil(remaining / monthsRemaining / 100); // Convert to dollars
  }

  // Get icon component
  const getIconComponent = (): React.ComponentType<{ className?: string; style?: React.CSSProperties }> => {
    if (!piggy.icon) return Icons.PiggyBank;
    const IconName = piggy.icon as keyof typeof Icons;
    const Icon = Icons[IconName] as React.ComponentType<{ className?: string; style?: React.CSSProperties }> | undefined;
    return Icon || Icons.PiggyBank;
  };
  const IconComponent = getIconComponent();

  const handleAddAmount = async () => {
    const amountCents = Math.round(parseFloat(addAmount) * 100);
    if (amountCents <= 0) return;

    setLoading(true);
    try {
      await piggyApi.addAmount(piggy.id, amountCents);
      setAddAmountOpen(false);
      setAddAmount('');
      onUpdate();
    } catch (error) {
      console.error('Error adding amount:', error);
      notify.error('Failed to add amount. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    const ok = await confirm({
      title: `Delete "${piggy.name}"?`,
      description: "This piggy goal will be permanently removed.",
      destructive: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;

    try {
      await piggyApi.delete(piggy.id);
      onUpdate();
    } catch (error) {
      console.error('Error deleting piggy bank:', error);
      notify.error('Failed to delete. Please try again.');
    }
  };

  const handleQuickAdd = async (amount: number) => {
    setLoading(true);
    try {
      await piggyApi.addAmount(piggy.id, amount * 100);
      onUpdate();
    } catch (error) {
      console.error('Error adding amount:', error);
      notify.error('Failed to add amount. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="relative overflow-hidden">
      {/* Color accent bar */}
      <div 
        className="absolute top-0 left-0 right-0 h-2"
        style={{ backgroundColor: piggy.color }}
      />
      
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div 
              className="w-12 h-12 rounded-full flex items-center justify-center"
              style={{ backgroundColor: `${piggy.color}20` }}
            >
              <IconComponent className="h-6 w-6" style={{ color: piggy.color }} />
            </div>
            <div>
              <h3 className="font-semibold text-lg">{piggy.name}</h3>
              {piggy.description && (
                <p className="text-sm text-muted-foreground">{piggy.description}</p>
              )}
            </div>
          </div>
          <div className="flex gap-1">
            <PiggyBankForm piggy={piggy} onSuccess={onUpdate} />
            <Button 
              size="sm" 
              variant="ghost" 
              onClick={handleDelete}
              className="text-destructive hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Progress Circle (simplified) */}
        <div className="flex items-center justify-center">
          <div className="relative w-32 h-32">
            <svg className="transform -rotate-90 w-32 h-32">
              <circle
                cx="64"
                cy="64"
                r="56"
                stroke="currentColor"
                strokeWidth="8"
                fill="none"
                className="text-muted"
              />
              <circle
                cx="64"
                cy="64"
                r="56"
                stroke={piggy.color}
                strokeWidth="8"
                fill="none"
                strokeDasharray={`${2 * Math.PI * 56}`}
                strokeDashoffset={`${2 * Math.PI * 56 * (1 - progress / 100)}`}
                className="transition-all duration-500"
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <div className="text-2xl font-bold" style={{ color: piggy.color }}>
                  {progress.toFixed(0)}%
                </div>
                {isCompleted && (
                  <CheckCircle2 className="h-6 w-6 mx-auto mt-1 text-green-500" />
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Amounts */}
        <div className="text-center space-y-1">
          <div className="text-2xl font-bold">
            {formatCurrency(piggy.current_amount_cents)} / {formatCurrency(piggy.target_amount_cents)}
          </div>
          <div className="text-sm text-muted-foreground">
            Remaining: {formatCurrency(remaining)}
          </div>
        </div>

        {/* Linear Progress */}
        <Progress value={progress} className="h-3" style={{ 
          ['--progress-background' as string]: piggy.color 
        }} />

        {/* Metrics */}
        <div className="grid grid-cols-2 gap-4 text-sm">
          {piggy.deadline && (
            <div>
              <div className="flex items-center gap-1 text-muted-foreground mb-1">
                <Calendar className="h-3 w-3" />
                <span>Deadline</span>
              </div>
              <div className="font-semibold">
                {format(new Date(piggy.deadline), 'MMM dd, yyyy')}
              </div>
              {isPast(new Date(piggy.deadline)) && !isCompleted && (
                <Badge variant="destructive" className="mt-1">Overdue</Badge>
              )}
            </div>
          )}
          {monthlyNeeded > 0 && (
            <div>
              <div className="flex items-center gap-1 text-muted-foreground mb-1">
                <Target className="h-3 w-3" />
                <span>Need/month</span>
              </div>
              <div className="font-semibold">
                ${monthlyNeeded.toFixed(0)}
              </div>
              <div className="text-xs text-muted-foreground">
                {monthsRemaining} months left
              </div>
            </div>
          )}
        </div>

        {/* Quick Add Buttons */}
        <div className="flex gap-2">
          <Button 
            size="sm" 
            variant="outline" 
            onClick={() => handleQuickAdd(50)}
            disabled={loading || isCompleted}
            className="flex-1"
          >
            +$50
          </Button>
          <Button 
            size="sm" 
            variant="outline" 
            onClick={() => handleQuickAdd(100)}
            disabled={loading || isCompleted}
            className="flex-1"
          >
            +$100
          </Button>
          <Button 
            size="sm" 
            variant="outline" 
            onClick={() => handleQuickAdd(500)}
            disabled={loading || isCompleted}
            className="flex-1"
          >
            +$500
          </Button>
        </div>

        {/* Custom Add Amount Dialog */}
        <Dialog open={addAmountOpen} onOpenChange={setAddAmountOpen}>
          <DialogTrigger asChild>
            <Button 
              variant="default" 
              className="w-full"
              disabled={loading || isCompleted}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add Custom Amount
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add Amount to {piggy.name}</DialogTitle>
              <DialogDescription>
                Enter the amount you want to add to this goal
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <Label htmlFor="amount">Amount ($)</Label>
                <Input
                  id="amount"
                  type="number"
                  step="0.01"
                  min="0"
                  value={addAmount}
                  onChange={(e) => setAddAmount(e.target.value)}
                  placeholder="0.00"
                />
              </div>
              <div className="flex justify-end space-x-2">
                <Button 
                  variant="outline" 
                  onClick={() => {
                    setAddAmountOpen(false);
                    setAddAmount('');
                  }}
                >
                  Cancel
                </Button>
                <Button onClick={handleAddAmount} disabled={loading || !addAmount}>
                  {loading ? 'Adding...' : 'Add'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>

        {/* Status Badge */}
        {isCompleted && (
          <Badge className="w-full justify-center py-2" variant="default">
            <CheckCircle2 className="h-4 w-4 mr-1" />
            Goal Completed!
          </Badge>
        )}
      </CardContent>
    </Card>
  );
}
