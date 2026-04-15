"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { expensesApi, limitsApi } from "@/lib/api";
import { Plus, Trash2, Search, Edit, AlertCircle } from "lucide-react";
import { format } from "date-fns";
import { safeFormatDate } from "@/lib/date-utils";
import { Expense, ExpenseSource } from "@/types/api";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

function SourceBadge({ source }: { source: ExpenseSource }) {
  if (source === "plaid") {
    return <Badge variant="outline" className="text-blue-600 border-blue-300 bg-blue-50">Plaid</Badge>;
  }
  if (source === "plaid_sandbox") {
    return <Badge variant="outline" className="text-orange-600 border-orange-300 bg-orange-50">Test</Badge>;
  }
  return <Badge variant="outline" className="text-gray-500">Manual</Badge>;
}

function CategoryCell({ expense }: { expense: Expense }) {
  const isUncategorized = expense.category === "Uncategorized";
  const plaidCats: string[] = expense.plaid_category_raw
    ? JSON.parse(expense.plaid_category_raw)
    : [];

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1">
        <Badge variant="secondary">{expense.category}</Badge>
        {isUncategorized && (expense.source === "plaid" || expense.source === "plaid_sandbox") && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger>
                <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
              </TooltipTrigger>
              <TooltipContent>
                <p>No category mapping set. Go to Settings → Bank Connections.</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
      {plaidCats.length > 0 && (
        <span className="text-xs text-muted-foreground">{plaidCats.join(" › ")}</span>
      )}
    </div>
  );
}

export function ExpensesPage() {
  const [selectedMonth, setSelectedMonth] = useState(format(new Date(), "yyyy-MM"));
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<ExpenseSource | "all">("all");
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [editingExpense, setEditingExpense] = useState<Expense | null>(null);
  const [newExpense, setNewExpense] = useState({ category: "", amount: "", date: "" });

  const queryClient = useQueryClient();

  // Получаем расходы
  const { data: expenses, isLoading } = useQuery({
    queryKey: ["expenses", selectedMonth, searchQuery, sourceFilter],
    queryFn: () => expensesApi.getAll(
      selectedMonth,
      searchQuery || undefined,
      sourceFilter !== "all" ? sourceFilter : undefined
    ),
  });

  // Получаем категории
  const { data: limits } = useQuery({
    queryKey: ["limits"],
    queryFn: () => limitsApi.getAll(),
  });

  // Мутация для создания расхода
  const createExpenseMutation = useMutation({
    mutationFn: (expense: { category: string; amount: number; date?: string }) =>
      expensesApi.create(expense),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["expenses"] });
      queryClient.invalidateQueries({ queryKey: ["report"] });
      setIsAddDialogOpen(false);
      setNewExpense({ category: "", amount: "", date: "" });
    },
  });

  // Мутация для обновления расхода
  const updateExpenseMutation = useMutation({
    mutationFn: ({ id, expense }: { id: number; expense: { category: string; amount: number; date?: string } }) =>
      expensesApi.update(id, expense),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["expenses"] });
      queryClient.invalidateQueries({ queryKey: ["report"] });
    },
  });

  // Мутация для удаления расхода
  const deleteExpenseMutation = useMutation({
    mutationFn: (id: number) => expensesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["expenses"] });
      queryClient.invalidateQueries({ queryKey: ["report"] });
    },
  });

  const handleAddExpense = () => {
    if (!newExpense.category || !newExpense.amount) return;

    createExpenseMutation.mutate({
      category: newExpense.category,
      amount: parseFloat(newExpense.amount),
      date: newExpense.date || undefined,
    });
  };

  const handleEditExpense = (expense: Expense) => {
    setEditingExpense(expense);
    setIsEditDialogOpen(true);
  };

  const handleUpdateExpense = () => {
    if (!editingExpense || !editingExpense.category || !editingExpense.amount) return;

    updateExpenseMutation.mutate({
      id: editingExpense.id,
      expense: {
        category: editingExpense.category,
        amount: editingExpense.amount,
        date: editingExpense.date,
      },
    });
    setIsEditDialogOpen(false);
    setEditingExpense(null);
  };

  const handleDeleteExpense = (id: number) => {
    if (confirm("Are you sure you want to delete this expense?")) {
      deleteExpenseMutation.mutate(id);
    }
  };

  // Генерируем список месяцев для выбора
  const generateMonths = () => {
    const months = [];
    const currentDate = new Date();
    for (let i = 0; i < 12; i++) {
      const date = new Date(currentDate.getFullYear(), currentDate.getMonth() - i, 1);
      const value = format(date, "yyyy-MM");
      const label = format(date, "MMMM yyyy");
      months.push({ value, label });
    }
    return months;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Expenses</h1>
          <p className="text-muted-foreground">
            Manage your expenses and track spending
          </p>
        </div>

        <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
          <DialogTrigger asChild>
            <Button className="gap-2">
              <Plus className="h-4 w-4" />
              Add Expense
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add New Expense</DialogTitle>
              <DialogDescription>
                Enter the details for your new expense.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <div className="grid gap-2">
                <Label htmlFor="category">Category</Label>
                <Select
                  value={newExpense.category}
                  onValueChange={(value) =>
                    setNewExpense({ ...newExpense, category: value })
                  }
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
              </div>
              <div className="grid gap-2">
                <Label htmlFor="amount">Amount ($)</Label>
                <Input
                  id="amount"
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  value={newExpense.amount}
                  onChange={(e) =>
                    setNewExpense({ ...newExpense, amount: e.target.value })
                  }
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="date">Date (optional)</Label>
                <Input
                  id="date"
                  type="date"
                  value={newExpense.date}
                  onChange={(e) =>
                    setNewExpense({ ...newExpense, date: e.target.value })
                  }
                />
                <p className="text-sm text-muted-foreground">
                  Leave empty to use today&apos;s date
                </p>
              </div>
            </div>
            <DialogFooter>
              <Button
                onClick={handleAddExpense}
                disabled={createExpenseMutation.isPending}
              >
                {createExpenseMutation.isPending ? "Adding..." : "Add Expense"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Edit Dialog */}
        <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Edit Expense</DialogTitle>
              <DialogDescription>
                Update the details for this expense.
              </DialogDescription>
            </DialogHeader>
            {editingExpense && (
              <div className="grid gap-4 py-4">
                <div className="grid gap-2">
                  <Label htmlFor="edit-category">Category</Label>
                  <Select
                    value={editingExpense.category}
                    onValueChange={(value) =>
                      setEditingExpense({ ...editingExpense, category: value })
                    }
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
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="edit-amount">Amount ($)</Label>
                  <Input
                    id="edit-amount"
                    type="number"
                    step="0.01"
                    placeholder="0.00"
                    value={editingExpense.amount}
                    onChange={(e) =>
                      setEditingExpense({ ...editingExpense, amount: parseFloat(e.target.value) || 0 })
                    }
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="edit-date">Date</Label>
                  <Input
                    id="edit-date"
                    type="date"
                    value={editingExpense.date ? editingExpense.date.split('T')[0] : ''}
                    onChange={(e) =>
                      setEditingExpense({ ...editingExpense, date: e.target.value })
                    }
                  />
                </div>
              </div>
            )}
            <DialogFooter>
              <Button
                onClick={handleUpdateExpense}
                disabled={updateExpenseMutation.isPending}
              >
                {updateExpenseMutation.isPending ? "Updating..." : "Update Expense"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4 items-end">
            <div className="grid gap-2">
              <Label htmlFor="month">Month</Label>
              <Select value={selectedMonth} onValueChange={setSelectedMonth}>
                <SelectTrigger className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {generateMonths().map((month) => (
                    <SelectItem key={month.value} value={month.value}>
                      {month.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="search">Search</Label>
              <div className="relative">
                <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  id="search"
                  placeholder="Search categories..."
                  className="pl-9 w-64"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
            </div>
            <div className="grid gap-2">
              <Label>Source</Label>
              <div className="flex gap-1">
                {(["all", "manual", "plaid", "plaid_sandbox"] as const).map((s) => (
                  <Button
                    key={s}
                    variant={sourceFilter === s ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSourceFilter(s)}
                  >
                    {s === "all" && "All"}
                    {s === "manual" && "Manual"}
                    {s === "plaid" && "Plaid"}
                    {s === "plaid_sandbox" && "Test"}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Expenses Table */}
      <Card>
        <CardHeader>
          <CardTitle>
            Expenses for {format(new Date(selectedMonth + "-15"), "MMMM yyyy")}
          </CardTitle>
          <CardDescription>
            {expenses?.length || 0} expenses found
            {expenses && expenses.length > 0 && (
              <span className="ml-2 font-medium text-foreground">
                — Total: ${expenses.reduce((s, e) => s + e.amount, 0).toFixed(2)}
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
          ) : expenses && expenses.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Merchant</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead className="w-20">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {expenses.map((expense: Expense) => (
                  <TableRow key={expense.id} className={expense.is_pending ? "opacity-60" : ""}>
                    <TableCell className="whitespace-nowrap">
                      {safeFormatDate(expense.date, "MMM dd, yyyy")}
                      {expense.is_pending && (
                        <span className="ml-1 text-xs text-amber-600">(pending)</span>
                      )}
                    </TableCell>
                    <TableCell className="max-w-[160px] truncate" title={expense.merchant_name ?? ""}>
                      {expense.merchant_name || <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell>
                      <CategoryCell expense={expense} />
                    </TableCell>
                    <TableCell>
                      <SourceBadge source={expense.source} />
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      ${expense.amount.toFixed(2)}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEditExpense(expense)}
                          disabled={updateExpenseMutation.isPending}
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDeleteExpense(expense.id)}
                          disabled={deleteExpenseMutation.isPending}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              No expenses found for the selected period.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
