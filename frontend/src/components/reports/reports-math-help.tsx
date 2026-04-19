"use client";

/**
 * Small question-mark popovers that explain the math behind the Income
 * and Expenses reports in plain language. The authoritative rule set
 * lives in `docs/reports-math.md` and `web/classification/classifier.py`;
 * the copy here is the user-facing distillation of those rules.
 *
 * We keep two focused components instead of one generic one because the
 * wording differs per tab and we'd rather not build a polymorphic
 * content-switcher for a 10-line prose block. Both share `HelpPopover`
 * for the trigger / popover chrome.
 */

import { HelpCircle } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

function HelpPopover({
  ariaLabel,
  title,
  children,
}: {
  ariaLabel: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 text-muted-foreground hover:text-foreground"
          aria-label={ariaLabel}
        >
          <HelpCircle className="size-4" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={8}
        className="w-[22rem] space-y-3 text-sm leading-relaxed"
      >
        <p className="text-sm font-semibold">{title}</p>
        {children}
        <p className="border-t border-border/60 pt-2 text-[11px] text-muted-foreground">
          Cash Flow, By Category and Financial Health use the same
          predicate, so the totals here always reconcile with them.
        </p>
      </PopoverContent>
    </Popover>
  );
}

/** Question-mark help for the Income tab — what counts as income and why. */
export function IncomeMathHelp() {
  return (
    <HelpPopover
      ariaLabel="How income is counted"
      title="How income is counted"
    >
      <p>
        A transaction shows up here when the classifier tags it as{" "}
        <span className="font-medium">Income</span>. Three things can
        trigger that:
      </p>
      <ul className="list-disc space-y-1 pl-4">
        <li>
          <span className="font-medium">Category marked as income</span>{" "}
          — salary, interest, dividends. Toggle which count via{" "}
          <span className="font-medium">Manage income categories</span>.
        </li>
        <li>
          <span className="font-medium">Money arriving from an untracked bank</span>{" "}
          — an incoming transfer we can&apos;t pair with one of your
          accounts (e.g. a wire from a bank you haven&apos;t connected)
          lands here so real external income never disappears.
        </li>
        <li>
          <span className="font-medium">Manual override</span> — pin any
          transaction as income in its details.
        </li>
      </ul>
      <p className="text-muted-foreground">
        <span className="font-medium">Not counted:</span> transfers
        between your own accounts (Chase ↔ PayPal), credit-card payments,
        Zelle with family — those are internal transfers. Refunds stay on
        the expense side and reduce the original category instead of
        inflating income.
      </p>
    </HelpPopover>
  );
}

/** Question-mark help for the Expenses tab — what counts, how refunds behave. */
export function ExpensesMathHelp() {
  return (
    <HelpPopover
      ariaLabel="How expenses are counted"
      title="How expenses are counted"
    >
      <p>
        Everything the classifier tags as{" "}
        <span className="font-medium">Expense</span> lives here: regular
        purchases on debit, credit card and cash.
      </p>
      <ul className="list-disc space-y-1 pl-4">
        <li>
          <span className="font-medium">Refunds stay in the category
          they came from</span> and net against its spend, so a
          row can turn negative when refunds beat charges in the month.
        </li>
        <li>
          <span className="font-medium">Internal transfers are excluded</span>{" "}
          — CC payments, savings ↔ checking sweeps, Zelle between
          spouses. The pair matcher links the two sides automatically
          (with a small fee tolerance for e.g. PayPal Instant Transfer),
          and the name matcher catches Zelle / wires between family
          members.
        </li>
        <li>
          <span className="font-medium">Investment & loan moves</span>{" "}
          don&apos;t land in Expenses — they stay{" "}
          <em>Uncategorized</em> until you override them.
        </li>
      </ul>
      <p className="text-muted-foreground">
        Something looking wrong? Open the transaction and flip the{" "}
        <span className="font-medium">Internal transfer</span> toggle or
        set a manual class — your choice is preserved across every
        future re-scan.
      </p>
    </HelpPopover>
  );
}
