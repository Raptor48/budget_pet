"use client";

/**
 * Data Quality page (Settings → Data quality).
 *
 * Owner-only diagnostic surface for the four-class transaction classifier.
 * Backed by `GET /api/reports/diagnostics`, which the backend already
 * gates with a 403 for non-owners. The settings shell hides the tab for
 * non-owners as defense in depth, but this page also defends itself.
 *
 * The page answers: "Can I trust this month's Income / Expense numbers?"
 * It surfaces every row the classifier had to guess about so the owner
 * can confirm, pin, or fix in 5-30 seconds. No auto-fixes — every
 * change is explicit so user trust in the math grows over time.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeftRight,
  CheckCircle2,
  ExternalLink,
  HelpCircle,
  Loader2,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  TagIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MonthYearPicker } from "@/components/ui/month-year-picker";
import { useAuth } from "@/contexts/auth-context";
import { ApiError, reportsApi, transactionsApi } from "@/lib/api";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type {
  Diagnostics,
  DiagnosticsRow,
  TransactionClass,
} from "@/types/v2";

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function formatMoney(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

function formatShortDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function rowLabel(row: DiagnosticsRow): string {
  return row.merchant_name?.trim() || row.name?.trim() || "Untitled";
}

export function DataQualityPage() {
  const { user } = useAuth();
  const isOwner = Boolean(user?.is_owner);
  const [month, setMonth] = useState<string>(currentMonth);

  const query = useQuery<Diagnostics>({
    queryKey: ["diagnostics", month],
    queryFn: () => reportsApi.getDiagnostics(month),
    enabled: isOwner,
    retry: (failureCount, error) => {
      // Don't hammer a 403: the backend says "no" loudly.
      if (error instanceof ApiError && error.status === 403) return false;
      return failureCount < 2;
    },
  });

  if (!isOwner) {
    return <OwnerOnlyState />;
  }

  return (
    <div className="space-y-6">
      <Header month={month} onMonthChange={setMonth} loading={query.isFetching} />

      {query.isLoading && (
        <Card>
          <CardContent className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Checking the math…
          </CardContent>
        </Card>
      )}

      {query.isError && (
        <Card className="border-destructive/40">
          <CardContent className="py-6 text-sm text-destructive">
            {query.error instanceof ApiError && query.error.status === 403
              ? "This page is owner-only. Ask the family owner for access."
              : (query.error as Error)?.message || "Failed to load diagnostics."}
          </CardContent>
        </Card>
      )}

      {query.data && <DataQualityBody data={query.data} month={month} />}
    </div>
  );
}

function Header({
  month,
  onMonthChange,
  loading,
}: {
  month: string;
  onMonthChange: (m: string) => void;
  loading: boolean;
}) {
  return (
    <Card className="border-border/80">
      <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-5 text-emerald-600" aria-hidden />
            Data Quality
            {loading && (
              <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-hidden />
            )}
          </CardTitle>
          <CardDescription className="max-w-2xl">
            Owner-only view of every transaction the classifier wasn&apos;t fully
            confident about. Pin a class inline or open the transaction for the
            full picture. Numbers in Reports stay honest only as long as the
            edge cases here stay small.
          </CardDescription>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">Month</span>
          <MonthYearPicker value={month} onChange={onMonthChange} />
        </div>
      </CardHeader>
    </Card>
  );
}

function OwnerOnlyState() {
  return (
    <Card className="border-border/80">
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <ShieldAlert className="size-10 text-muted-foreground" aria-hidden />
        <p className="font-medium">Owner-only page</p>
        <p className="max-w-md text-sm text-muted-foreground">
          Data Quality surfaces classifier edge cases across every family
          member, including private transactions. Only the family owner has
          access.
        </p>
      </CardContent>
    </Card>
  );
}

function DataQualityBody({ data, month }: { data: Diagnostics; month: string }) {
  const totalSuspect =
    data.possible_refunds_misclassified_as_income.length +
    data.transfer_pfc_not_classified_as_internal.length +
    data.suspicious_income_category_with_positive_amount.length +
    data.large_uncategorized.length;

  return (
    <>
      <DistributionStrip counts={data.counts} />

      {totalSuspect === 0 ? (
        <AllClearState month={month} totalRows={data.counts.total} />
      ) : (
        <div className="space-y-4">
          <PossibleRefundsSection
            month={month}
            rows={data.possible_refunds_misclassified_as_income}
          />
          <UnmatchedTransfersSection
            month={month}
            rows={data.transfer_pfc_not_classified_as_internal}
          />
          <IncomeMismatchSection
            month={month}
            rows={data.suspicious_income_category_with_positive_amount}
          />
          <LargeUncategorizedSection
            month={month}
            rows={data.large_uncategorized}
          />
        </div>
      )}
    </>
  );
}

function DistributionStrip({ counts }: { counts: Diagnostics["counts"] }) {
  const total = counts.total || 0;
  const uncategorizedRatio = total > 0 ? counts.uncategorized / total : 0;

  let healthLabel: string;
  let healthClass: string;
  let healthIcon: React.ReactNode;
  if (total === 0) {
    healthLabel = "No transactions in this month yet";
    healthClass = "bg-muted text-muted-foreground";
    healthIcon = <HelpCircle className="size-4" aria-hidden />;
  } else if (uncategorizedRatio < 0.01) {
    healthLabel = `${Math.round((1 - uncategorizedRatio) * 100)}% confidently classified — math is healthy`;
    healthClass =
      "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30";
    healthIcon = <CheckCircle2 className="size-4" aria-hidden />;
  } else if (uncategorizedRatio < 0.05) {
    healthLabel = `${Math.round(uncategorizedRatio * 100)}% need review`;
    healthClass =
      "bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/30";
    healthIcon = <AlertTriangle className="size-4" aria-hidden />;
  } else {
    healthLabel = `${Math.round(uncategorizedRatio * 100)}% of rows need attention`;
    healthClass =
      "bg-red-500/10 text-red-700 dark:text-red-400 border border-red-500/30";
    healthIcon = <AlertTriangle className="size-4" aria-hidden />;
  }

  return (
    <Card>
      <CardContent className="space-y-4 py-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <CountTile label="Income" value={counts.income} accent="emerald" />
          <CountTile label="Expense" value={counts.expense} accent="rose" />
          <CountTile
            label="Internal transfer"
            value={counts.internal_transfer}
            accent="sky"
          />
          <CountTile
            label="Uncategorized"
            value={counts.uncategorized}
            accent={counts.uncategorized > 0 ? "amber" : "muted"}
          />
        </div>
        <div
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium",
            healthClass,
          )}
        >
          {healthIcon}
          {healthLabel}
        </div>
      </CardContent>
    </Card>
  );
}

function CountTile({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: "emerald" | "rose" | "sky" | "amber" | "muted";
}) {
  const accentClasses: Record<typeof accent, string> = {
    emerald: "text-emerald-700 dark:text-emerald-400",
    rose: "text-rose-700 dark:text-rose-400",
    sky: "text-sky-700 dark:text-sky-400",
    amber: "text-amber-700 dark:text-amber-400",
    muted: "text-muted-foreground",
  };
  return (
    <div className="rounded-lg border border-border/50 bg-card px-3 py-2.5">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("mt-0.5 text-2xl font-semibold tabular-nums", accentClasses[accent])}>
        {value}
      </p>
    </div>
  );
}

function AllClearState({ month, totalRows }: { month: string; totalRows: number }) {
  const monthLabel = useMemo(() => {
    const [y, m] = month.split("-");
    if (!y || !m) return month;
    const d = new Date(Number(y), Number(m) - 1, 1);
    return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  }, [month]);
  return (
    <Card className="border-emerald-500/30 bg-emerald-500/5">
      <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
        <div className="flex size-12 items-center justify-center rounded-full bg-emerald-500/15">
          <ShieldCheck className="size-6 text-emerald-600" aria-hidden />
        </div>
        <p className="font-medium">All clean for {monthLabel}.</p>
        <p className="max-w-md text-sm text-muted-foreground">
          {totalRows === 0
            ? "No transactions yet — nothing to verify."
            : `Every one of ${totalRows} transaction${totalRows === 1 ? "" : "s"} is confidently classified. Reports for this month are trustworthy.`}
        </p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

interface SectionProps {
  rows: DiagnosticsRow[];
  month: string;
}

function PossibleRefundsSection({ rows, month }: SectionProps) {
  if (rows.length === 0) return null;
  return (
    <SectionShell
      icon={<RefreshCw className="size-5 text-amber-600" aria-hidden />}
      title="Looks like a refund?"
      count={rows.length}
      tone="amber"
      description={
        <>
          These deposits match a recent purchase from the same merchant. Almost
          certainly refunds. Pinning them as <strong>expense</strong> reduces
          the original spend bucket instead of double-inflating both income
          and expense.
        </>
      }
    >
      <ul className="divide-y divide-border/40">
        {rows.map((row) => (
          <RowItem
            key={row.id}
            row={row}
            month={month}
            extra={
              row.recent_expense_date ? (
                <span className="text-[11px] text-muted-foreground">
                  matched purchase {formatShortDate(row.recent_expense_date)}
                </span>
              ) : null
            }
            primaryAction={{ label: "Pin as expense", target: "expense" }}
          />
        ))}
      </ul>
    </SectionShell>
  );
}

function UnmatchedTransfersSection({ rows, month }: SectionProps) {
  if (rows.length === 0) return null;
  return (
    <SectionShell
      icon={<ArrowLeftRight className="size-5 text-sky-600" aria-hidden />}
      title="Transfers without a pair"
      count={rows.length}
      tone="sky"
      description={
        <>
          Plaid tagged these as transfers but the classifier couldn&apos;t find
          a matching pair on another account. Three usual causes: the partner
          hasn&apos;t synced yet, the counterparty isn&apos;t in your{" "}
          <Link
            href="/settings"
            className="underline underline-offset-2 hover:text-foreground"
          >
            internal-transfer names list
          </Link>
          , or it&apos;s genuinely a one-way deposit from a bank you don&apos;t
          track. Pin <strong>internal transfer</strong> if you know the partner
          will never appear; otherwise leave it for the classifier to catch on
          the next sync.
        </>
      }
    >
      <ul className="divide-y divide-border/40">
        {rows.map((row) => (
          <RowItem
            key={row.id}
            row={row}
            month={month}
            extra={
              <span className="text-[11px] text-muted-foreground">
                {row.pfc_primary || "transfer"} · current: {row.transaction_class || "—"}
              </span>
            }
            primaryAction={{
              label: "Pin internal",
              target: "internal_transfer",
            }}
          />
        ))}
      </ul>
    </SectionShell>
  );
}

function IncomeMismatchSection({ rows, month }: SectionProps) {
  if (rows.length === 0) return null;
  return (
    <SectionShell
      icon={<TagIcon className="size-5 text-orange-600" aria-hidden />}
      title="Income category but charged"
      count={rows.length}
      tone="orange"
      description={
        <>
          These rows have a category flagged as <em>income</em> but Plaid
          recorded them as a charge (money out). The classifier dropped them to{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
            uncategorized
          </code>{" "}
          on purpose so they don&apos;t pollute either bucket. Open and switch
          the category to something on the spend side, or pin the class
          manually if the category is correct.
        </>
      }
    >
      <ul className="divide-y divide-border/40">
        {rows.map((row) => (
          <RowItem
            key={row.id}
            row={row}
            month={month}
            extra={
              row.category_name ? (
                <span className="text-[11px] text-muted-foreground">
                  {row.category_name}
                </span>
              ) : null
            }
          />
        ))}
      </ul>
    </SectionShell>
  );
}

function LargeUncategorizedSection({ rows, month }: SectionProps) {
  if (rows.length === 0) return null;
  return (
    <SectionShell
      icon={<HelpCircle className="size-5 text-muted-foreground" aria-hidden />}
      title="Large uncategorized"
      count={rows.length}
      tone="muted"
      description={
        <>
          Rows over $10 the classifier left as{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">
            uncategorized
          </code>
          . Usually these are 401k contributions, mortgage principal, or
          internal investment moves — fine to leave alone. Skim for anything
          unusual; a $5,000 expense hiding here would be a red flag.
        </>
      }
    >
      <ul className="divide-y divide-border/40">
        {rows.map((row) => (
          <RowItem
            key={row.id}
            row={row}
            month={month}
            extra={
              row.account_type ? (
                <span className="text-[11px] text-muted-foreground">
                  {row.account_type} account
                </span>
              ) : null
            }
          />
        ))}
      </ul>
    </SectionShell>
  );
}

// ---------------------------------------------------------------------------
// Row + shell primitives
// ---------------------------------------------------------------------------

function SectionShell({
  icon,
  title,
  count,
  tone,
  description,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
  tone: "amber" | "sky" | "orange" | "muted";
  description: React.ReactNode;
  children: React.ReactNode;
}) {
  const toneClasses: Record<typeof tone, string> = {
    amber: "border-amber-500/30",
    sky: "border-sky-500/30",
    orange: "border-orange-500/30",
    muted: "border-border/60",
  };
  return (
    <Card className={cn("overflow-hidden", toneClasses[tone])}>
      <CardHeader className="space-y-1.5">
        <CardTitle className="flex items-center gap-2 text-base">
          {icon}
          {title}
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground tabular-nums">
            {count}
          </span>
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="px-0 pb-0">{children}</CardContent>
    </Card>
  );
}

function RowItem({
  row,
  month,
  extra,
  primaryAction,
}: {
  row: DiagnosticsRow;
  month: string;
  extra?: React.ReactNode;
  primaryAction?: { label: string; target: TransactionClass };
}) {
  const queryClient = useQueryClient();
  const pinMutation = useMutation({
    mutationFn: (target: TransactionClass) =>
      transactionsApi.update(row.id, { transaction_class: target }),
    onSuccess: (_data, target) => {
      notify.success(`Pinned as ${target.replace("_", " ")}`);
      queryClient.invalidateQueries({ queryKey: ["diagnostics", month] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
    onError: (err) => {
      notify.error(
        err instanceof Error ? err.message : "Failed to pin classification",
      );
    },
  });

  const isPositive = row.amount_cents > 0;
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm sm:flex-nowrap">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {formatShortDate(row.date)}
          </span>
          <span className="truncate font-medium">{rowLabel(row)}</span>
          <span
            className={cn(
              "shrink-0 tabular-nums text-sm font-semibold",
              isPositive
                ? "text-rose-700 dark:text-rose-400"
                : "text-emerald-700 dark:text-emerald-400",
            )}
          >
            {isPositive ? "" : "+"}
            {formatMoney(Math.abs(row.amount_cents))}
          </span>
        </div>
        {extra && <div className="mt-0.5">{extra}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {primaryAction && (
          <Button
            size="sm"
            variant="outline"
            disabled={pinMutation.isPending}
            onClick={() => pinMutation.mutate(primaryAction.target)}
          >
            {pinMutation.isPending && (
              <Loader2 className="mr-1.5 size-3 animate-spin" aria-hidden />
            )}
            {primaryAction.label}
          </Button>
        )}
        <Button asChild size="sm" variant="ghost">
          <Link
            href={`/transactions?highlight=${row.id}`}
            className="inline-flex items-center gap-1"
            aria-label={`Open ${rowLabel(row)}`}
          >
            Open
            <ExternalLink className="size-3.5" aria-hidden />
          </Link>
        </Button>
      </div>
    </li>
  );
}
