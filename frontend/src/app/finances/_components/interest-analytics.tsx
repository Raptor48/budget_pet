'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { InterestSummary } from '@/types/api';
import { formatCurrency } from '@/lib/utils';
import { financeApi } from '@/lib/api';
import { TrendingUp, DollarSign, Target, Zap } from 'lucide-react';

interface InterestAnalyticsProps {
  month: string;
}

export function InterestAnalytics({ month }: InterestAnalyticsProps) {
  const [summary, setSummary] = useState<InterestSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAccount, setSelectedAccount] = useState<string>('all');

  const fetchInterestSummary = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      const data = await financeApi.getInterestSummary(month);
      setSummary(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => {
    fetchInterestSummary();
  }, [fetchInterestSummary]);

  const formatMonths = (months: number | undefined) => {
    if (!months || months === 0) return 'N/A';
    if (months > 600) return '50+ years';
    
    const years = Math.floor(months / 12);
    const remainingMonths = months % 12;
    
    if (years === 0) return `${months} months`;
    if (remainingMonths === 0) return `${years} years`;
    return `${years}y ${remainingMonths}m`;
  };


  // Get filtered analytics for selected account
  const getFilteredData = () => {
    if (!summary || selectedAccount === 'all') {
      return {
        analytics: summary?.account_analytics || [],
        projectedPayoffMonths: summary?.projected_payoff_months || 0,
        currentPayoffMonths: summary?.current_payoff_months || 0,
        totalProjectedInterest: summary?.total_projected_interest_cents || 0,
        totalCurrentInterest: summary?.current_projected_interest_cents || 0,
        totalProjectedCost: summary?.total_projected_cost_cents || 0,
        totalCurrentCost: summary?.current_projected_cost_cents || 0,
      };
    }

    const account = summary.account_analytics.find(
      a => `${a.account_type}-${a.account_id}` === selectedAccount
    );

    if (!account) {
      return {
        analytics: [],
        projectedPayoffMonths: 0,
        currentPayoffMonths: 0,
        totalProjectedInterest: 0,
        totalCurrentInterest: 0,
        totalProjectedCost: 0,
        totalCurrentCost: 0,
      };
    }

    return {
      analytics: [account],
      projectedPayoffMonths: account.min_payment_months || 0,
      currentPayoffMonths: account.current_payoff_months || 0,
      totalProjectedInterest: account.min_payment_total_interest_cents,
      totalCurrentInterest: account.current_total_interest_cents,
      totalProjectedCost: account.min_payment_total_cost_cents,
      totalCurrentCost: account.current_total_cost_cents,
    };
  };

  const filteredData = getFilteredData();

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Interest Analytics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-4">
            <div className="h-4 bg-gray-200 rounded w-3/4"></div>
            <div className="h-4 bg-gray-200 rounded w-1/2"></div>
            <div className="h-4 bg-gray-200 rounded w-5/6"></div>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Interest Analytics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-red-600">Error: {error}</div>
        </CardContent>
      </Card>
    );
  }

  if (!summary) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Interest Analytics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-gray-500">No data available</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Monthly Interest Overview */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DollarSign className="h-5 w-5" />
            Monthly Interest Overview
          </CardTitle>
          <CardDescription>Interest accruing this month</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-red-600">
                {formatCurrency(summary.total_interest_accrued_cents)}
              </div>
              <div className="text-sm text-gray-500">Total Interest</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-orange-600">
                {formatCurrency(summary.loans_interest_cents)}
              </div>
              <div className="text-sm text-gray-500">Loans Interest</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-600">
                {formatCurrency(summary.cards_interest_cents)}
              </div>
              <div className="text-sm text-gray-500">Cards Interest</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Savings Overview */}
      {summary.total_interest_savings_cents > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-green-600" />
              Interest Savings
            </CardTitle>
            <CardDescription>Savings from your current payment strategy</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-green-600">
                  {formatCurrency(summary.total_interest_savings_cents)}
                </div>
                <div className="text-sm text-gray-500">Total Interest Saved</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-blue-600">
                  {formatMonths(summary.total_months_saved)}
                </div>
                <div className="text-sm text-gray-500">Time Saved</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Payoff Projections */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="h-5 w-5" />
            Payoff Projections
          </CardTitle>
          <CardDescription>Comparison of minimum vs current payment strategy</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {/* Account Selector */}
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Account:</span>
              <Select value={selectedAccount} onValueChange={setSelectedAccount}>
                <SelectTrigger className="w-64">
                  <SelectValue placeholder="Select account" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Accounts (Combined)</SelectItem>
                  {summary?.account_analytics.map((account) => (
                    <SelectItem 
                      key={`${account.account_type}-${account.account_id}`}
                      value={`${account.account_type}-${account.account_id}`}
                    >
                      {account.name} ({account.account_type.toUpperCase()})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 border rounded-lg">
                <h4 className="font-semibold text-red-600 mb-2">Minimum Payments</h4>
                <div className="space-y-2">
                  <div>
                    <span className="text-sm text-gray-500">Time to payoff:</span>
                    <div className="font-semibold">{formatMonths(filteredData.projectedPayoffMonths)}</div>
                  </div>
                  <div>
                    <span className="text-sm text-gray-500">Total interest:</span>
                    <div className="font-semibold">{formatCurrency(filteredData.totalProjectedInterest)}</div>
                  </div>
                  <div>
                    <span className="text-sm text-gray-500">Total cost:</span>
                    <div className="font-semibold">{formatCurrency(filteredData.totalProjectedCost)}</div>
                  </div>
                </div>
              </div>
              
              <div className="p-4 border rounded-lg bg-green-50">
                <h4 className="font-semibold text-green-600 mb-2">Current Strategy</h4>
                <div className="space-y-2">
                  <div>
                    <span className="text-sm text-gray-500">Time to payoff:</span>
                    <div className="font-semibold">{formatMonths(filteredData.currentPayoffMonths)}</div>
                  </div>
                  <div>
                    <span className="text-sm text-gray-500">Total interest:</span>
                    <div className="font-semibold">{formatCurrency(filteredData.totalCurrentInterest)}</div>
                  </div>
                  <div>
                    <span className="text-sm text-gray-500">Total cost:</span>
                    <div className="font-semibold">{formatCurrency(filteredData.totalCurrentCost)}</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Account Details for Selected Account */}
            {selectedAccount !== 'all' && filteredData.analytics.length > 0 && (
              <div className="space-y-4">
                <div className="p-4 border rounded-lg bg-gray-50">
                  <h4 className="font-semibold text-gray-700 mb-2">Account Information</h4>
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <span className="text-sm text-gray-500">Current Balance:</span>
                      <div className="font-semibold">
                        {formatCurrency(filteredData.analytics[0].current_balance_cents)}
                      </div>
                    </div>
                    <div>
                      <span className="text-sm text-gray-500">APR:</span>
                      <div className="font-semibold">{filteredData.analytics[0].apr_percent}%</div>
                    </div>
                    <div>
                      <span className="text-sm text-gray-500">Monthly Interest:</span>
                      <div className="font-semibold text-red-600">
                        {formatCurrency(filteredData.analytics[0].monthly_interest_cents)}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="p-4 border rounded-lg bg-blue-50">
                  <h4 className="font-semibold text-blue-600 mb-2">Savings with Current Strategy</h4>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="text-sm text-gray-500">Interest saved:</span>
                      <div className="font-semibold text-green-600">
                        {formatCurrency(filteredData.analytics[0].interest_savings_cents)}
                      </div>
                    </div>
                    <div>
                      <span className="text-sm text-gray-500">Time saved:</span>
                      <div className="font-semibold text-blue-600">
                        {formatMonths(filteredData.analytics[0].months_saved)}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Account Analytics */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            {selectedAccount === 'all' ? 'All Account Details' : 'Selected Account Details'}
          </CardTitle>
          <CardDescription>
            {selectedAccount === 'all' 
              ? 'Individual account analytics and projections'
              : `Detailed analytics for selected account`
            }
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {filteredData.analytics.map((account) => (
              <div key={`${account.account_type}-${account.account_id}`} className="border rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h4 className="font-semibold">{account.name}</h4>
                    <Badge variant={account.account_type === 'loan' ? 'destructive' : 'secondary'}>
                      {account.account_type.toUpperCase()}
                    </Badge>
                  </div>
                  <div className="text-right">
                    <div className="font-semibold">{formatCurrency(account.current_balance_cents)}</div>
                    <div className="text-sm text-gray-500">{account.apr_percent}% APR</div>
                  </div>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                  <div>
                    <span className="text-gray-500">Monthly Interest:</span>
                    <div className="font-semibold text-red-600">
                      {formatCurrency(account.monthly_interest_cents)}
                    </div>
                  </div>
                  <div>
                    <span className="text-gray-500">Payoff Time:</span>
                    <div className="font-semibold">
                      {formatMonths(account.current_payoff_months)}
                    </div>
                  </div>
                  <div>
                    <span className="text-gray-500">Interest Savings:</span>
                    <div className="font-semibold text-green-600">
                      {formatCurrency(account.interest_savings_cents)}
                    </div>
                  </div>
                </div>
                
                {account.months_saved > 0 && (
                  <div className="mt-2 text-sm text-green-600">
                    💡 Saving {formatMonths(account.months_saved)} by paying more than minimum
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
