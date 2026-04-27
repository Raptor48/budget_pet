"use client";

import { useState } from "react";
import Link from "next/link";
import { Building2, Plus, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { AddCashWalletDialog } from "./add-cash-wallet-dialog";

/**
 * Header CTA on the Accounts page. One button, two intents:
 *   1. Cash wallet — opens the in-app modal (manual ledger)
 *   2. Bank — bounces to /settings#settings-bank-connections where the
 *      Plaid Link flow lives. Bank linking deliberately stays on the
 *      Settings page (Plaid Item state belongs there).
 */
export function AddAccountMenu() {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [cashOpen, setCashOpen] = useState(false);

  return (
    <>
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <PopoverTrigger asChild>
          <Button type="button" className="gap-1.5">
            <Plus className="size-4" aria-hidden />
            Add account
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="w-[260px] p-1.5"
          sideOffset={6}
        >
          <button
            type="button"
            className="flex w-full items-start gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
            onClick={() => {
              setPopoverOpen(false);
              setCashOpen(true);
            }}
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
              <Wallet className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium leading-tight">
                Cash wallet
              </span>
              <span className="block text-xs text-muted-foreground">
                Manual ledger you control
              </span>
            </span>
          </button>

          <Link
            href="/settings#settings-bank-connections"
            className="flex w-full items-start gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
            onClick={() => setPopoverOpen(false)}
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
              <Building2 className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium leading-tight">
                Connect bank
              </span>
              <span className="block text-xs text-muted-foreground">
                Plaid — pulls live balances + transactions
              </span>
            </span>
          </Link>
        </PopoverContent>
      </Popover>

      <AddCashWalletDialog open={cashOpen} onOpenChange={setCashOpen} />
    </>
  );
}
