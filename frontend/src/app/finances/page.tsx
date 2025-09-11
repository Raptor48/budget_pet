"use client";

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { AppLayout } from '@/components/layout/app-layout';
import { financeApi } from '@/lib/api';
import { formatCurrency } from '@/lib/utils';
import { FinanceSummary, Loan, CreditCard, Income, PaymentCreate } from '@/types/api';
import { format } from 'date-fns';
import { Plus, CreditCard as CreditCardIcon, Banknote, DollarSign, TrendingUp, Trash2 } from 'lucide-react';
import { LoanForm } from './_components/loan-form';
import { CardForm } from './_components/card-form';
import { IncomeForm } from './_components/income-form';
import { MonthPicker } from './_components/month-picker';
import { InterestAnalytics } from './_components/interest-analytics';

export default function FinancesPage() {
  const [summary, setSummary] = useState<FinanceSummary | null>(null);
  const [loans, setLoans] = useState<Loan[]>([]);
  const [cards, setCards] = useState<CreditCard[]>([]);
  const [income, setIncome] = useState<Income[]>([]);
  const [selectedMonth, setSelectedMonth] = useState<string>(format(new Date(), 'yyyy-MM'));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load data
  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      const [summaryData, loansData, cardsData, incomeData] = await Promise.all([
        financeApi.getSummary(selectedMonth),
        financeApi.getLoans(true),
        financeApi.getCards(true),
        financeApi.getIncome(selectedMonth)
      ]);
      
      setSummary(summaryData);
      setLoans(loansData);
      setCards(cardsData);
      setIncome(incomeData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [selectedMonth]);

  useEffect(() => {
    loadData();
  }, [selectedMonth, loadData]);

  // Helper functions
  const formatDate = (dateString: string) => format(new Date(dateString), 'MMM dd, yyyy');

  // Payment handlers
  const handlePayment = async (accountType: 'loan' | 'card', accountId: number, amount: number, date?: string) => {
    try {
      const payment: PaymentCreate = {
        account_type: accountType,
        account_id: accountId,
        amount_cents: Math.round(amount * 100),
        occurred_at: date, // Use provided date or undefined for today
        person: 'Denis',
        note: 'Payment via web interface'
      };
      
      await financeApi.createPayment(payment);
      await loadData(); // Reload data
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create payment');
    }
  };

  // Delete handlers
  const handleDeleteLoan = async (id: number) => {
    if (confirm('Are you sure you want to delete this loan?')) {
      try {
        await financeApi.deleteLoan(id);
        await loadData();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete loan');
      }
    }
  };

  const handleDeleteCard = async (id: number) => {
    if (confirm('Are you sure you want to delete this credit card?')) {
      try {
        await financeApi.deleteCard(id);
        await loadData();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete credit card');
      }
    }
  };

  const handleDeleteIncome = async (id: number) => {
    if (confirm('Are you sure you want to delete this income entry?')) {
      try {
        await financeApi.deleteIncome(id);
        await loadData();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete income entry');
      }
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-lg">Loading finances...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-500">Error: {error}</div>
      </div>
    );
  }

  return (
    <AppLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Finances</h1>
            <p className="text-muted-foreground">Manage loans, credit cards, and income</p>
          </div>
          <div className="flex items-center space-x-4">
            <Label>Month:</Label>
            <MonthPicker
              value={selectedMonth}
              onChange={setSelectedMonth}
            />
          </div>
        </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Income</CardTitle>
              <DollarSign className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatCurrency(summary.income_total_cents)}</div>
              <div className="text-xs text-muted-foreground">
                Denis: {formatCurrency(summary.income_by_person.Denis)} | 
                Taya: {formatCurrency(summary.income_by_person.Taya)}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Debt</CardTitle>
              <CreditCardIcon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatCurrency(summary.debt_totals.combined_balance_cents)}</div>
              <div className="text-xs text-muted-foreground">
                Loans: {formatCurrency(summary.debt_totals.loans_balance_cents)} | 
                Cards: {formatCurrency(summary.debt_totals.cards_balance_cents)}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Min Payments</CardTitle>
              <Banknote className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatCurrency(summary.debt_totals.min_payments_cents)}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Net Income</CardTitle>
              <TrendingUp className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {formatCurrency(summary.income_total_cents - summary.debt_totals.min_payments_cents)}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Loans and Credit Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Loans */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Banknote className="h-5 w-5" />
                Loans
              </div>
              <LoanForm onSuccess={loadData} />
            </CardTitle>
            <CardDescription>Manage your loans and payments</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Balance</TableHead>
                  <TableHead>Min Payment</TableHead>
                  <TableHead>APR</TableHead>
                  <TableHead>Due Date</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loans.map((loan) => (
                  <TableRow key={loan.id}>
                    <TableCell className="font-medium">{loan.name}</TableCell>
                    <TableCell>{formatCurrency(loan.current_balance_cents)}</TableCell>
                    <TableCell>{formatCurrency(loan.min_payment_cents)}</TableCell>
                    <TableCell>{loan.apr_percent}%</TableCell>
                    <TableCell>{loan.due_date ? formatDate(loan.due_date) : '-'}</TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <PaymentDialog
                          accountType="loan"
                          accountId={loan.id}
                          accountName={loan.name}
                          onPayment={handlePayment}
                        />
                        <LoanForm loan={loan} onSuccess={loadData} />
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleDeleteLoan(loan.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Credit Cards */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CreditCardIcon className="h-5 w-5" />
                Credit Cards
              </div>
              <CardForm onSuccess={loadData} />
            </CardTitle>
            <CardDescription>Manage your credit cards and payments</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Balance</TableHead>
                  <TableHead>Min Payment</TableHead>
                  <TableHead>APR</TableHead>
                  <TableHead>Due Date</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cards.map((card) => (
                  <TableRow key={card.id}>
                    <TableCell className="font-medium">{card.name}</TableCell>
                    <TableCell>{formatCurrency(card.current_balance_cents)}</TableCell>
                    <TableCell>{formatCurrency(card.min_payment_cents)}</TableCell>
                    <TableCell>{card.apr_percent}%</TableCell>
                    <TableCell>{card.due_date ? formatDate(card.due_date) : '-'}</TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <PaymentDialog
                          accountType="card"
                          accountId={card.id}
                          accountName={card.name}
                          onPayment={handlePayment}
                        />
                        <CardForm card={card} onSuccess={loadData} />
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleDeleteCard(card.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {/* Income */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <DollarSign className="h-5 w-5" />
              Income - {selectedMonth}
            </div>
            <IncomeForm onSuccess={loadData} />
          </CardTitle>
          <CardDescription>Income entries for the selected month</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Person</TableHead>
                <TableHead>Amount</TableHead>
                <TableHead>Note</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {income.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell>{formatDate(entry.occurred_at)}</TableCell>
                  <TableCell>
                    <Badge variant={entry.person === 'Denis' ? 'default' : 'secondary'}>
                      {entry.person}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-medium">{formatCurrency(entry.amount_cents)}</TableCell>
                  <TableCell>{entry.note || '-'}</TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <IncomeForm income={entry} onSuccess={loadData} />
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleDeleteIncome(entry.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Interest Analytics Section */}
      <InterestAnalytics month={selectedMonth} />
      </div>
    </AppLayout>
  );
}

// Payment Dialog Component
function PaymentDialog({ 
  accountType, 
  accountId, 
  accountName, 
  onPayment 
}: { 
  accountType: 'loan' | 'card';
  accountId: number;
  accountName: string;
  onPayment: (accountType: 'loan' | 'card', accountId: number, amount: number, date?: string) => void;
}) {
  const [amount, setAmount] = useState('');
  const [paymentDate, setPaymentDate] = useState('');
  const [open, setOpen] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const paymentAmount = parseFloat(amount);
    if (paymentAmount > 0) {
      onPayment(accountType, accountId, paymentAmount, paymentDate || undefined);
      setAmount('');
      setPaymentDate('');
      setOpen(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Plus className="h-4 w-4 mr-1" />
          Payment
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Payment</DialogTitle>
          <DialogDescription>
            Add a payment for {accountName}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="amount">Amount</Label>
            <Input
              id="amount"
              type="number"
              step="0.01"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
              required
            />
          </div>
          <div>
            <Label htmlFor="paymentDate">Date (optional)</Label>
            <Input
              id="paymentDate"
              type="date"
              value={paymentDate}
              onChange={(e) => setPaymentDate(e.target.value)}
              placeholder="Leave empty for today"
            />
            <p className="text-sm text-muted-foreground mt-1">
              Leave empty to use today&apos;s date
            </p>
          </div>
          <div className="flex justify-end space-x-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Add Payment</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
