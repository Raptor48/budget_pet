"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Bot,
  Building2,
  ChevronsLeft,
  ChevronsRight,
  LayoutDashboard,
  Lightbulb,
  LogOut,
  PieChart,
  Receipt,
  Repeat,
  Settings,
  Wallet,
  X,
} from "lucide-react";
import { useAuth } from "@/contexts/auth-context";
import { insightsApi, plaidApi } from "@/lib/api";

// `divider: true` inserts a thin separator above the row in the sidebar.
const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard, ownerOnly: false },
  { name: "Transactions", href: "/transactions", icon: Receipt, ownerOnly: false },
  { name: "Accounts", href: "/accounts", icon: Building2, ownerOnly: false },
  { name: "Recurring", href: "/recurring", icon: Repeat, ownerOnly: false },
  { name: "Reports", href: "/reports", icon: PieChart, ownerOnly: false },
  { name: "Insights", href: "/insights", icon: Lightbulb, ownerOnly: false },
  { name: "Bot", href: "/bot", icon: Bot, ownerOnly: false, divider: true },
];

interface SidebarProps {
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  onMobileClose?: () => void;
}

export function Sidebar({
  collapsed = false,
  onToggleCollapsed,
  onMobileClose,
}: SidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  // Insights badge — only fetched when logged in, cached for 60s.
  const insightsQuery = useQuery({
    queryKey: ["insights", "feed"],
    queryFn: () => insightsApi.getFeed(),
    enabled: Boolean(user),
    staleTime: 60_000,
  });
  const newCount = insightsQuery.data?.new_count ?? 0;

  // Plaid attention dot on Settings — same query as the (now-deprecated)
  // global banner; cache shared via react-query keys so we don't pay twice.
  const plaidItemsQuery = useQuery({
    queryKey: ["plaid-items"],
    queryFn: plaidApi.listItems,
    enabled: Boolean(user),
    staleTime: 60_000,
  });
  const plaidNeedsAttention = (plaidItemsQuery.data ?? []).some(
    (i) => i.item_login_required,
  );

  return (
    <TooltipProvider delayDuration={200}>
      <div
        className={cn(
          "flex h-full flex-col bg-card transition-[width] duration-200",
          "border-r border-border",
          collapsed ? "w-16" : "w-64",
        )}
      >
        {/* Header */}
        <div
          className={cn(
            "flex h-14 shrink-0 items-center border-b border-border",
            collapsed ? "justify-center px-2" : "justify-between px-4",
          )}
        >
          {!collapsed && (
            <Link
              href="/"
              onClick={onMobileClose}
              className="flex items-center gap-2 outline-none focus-visible:ring-2 focus-visible:ring-ring/40 rounded"
            >
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary">
                <Wallet className="size-4" aria-hidden />
              </span>
              <span className="text-base font-semibold tracking-tight text-foreground">
                Family Budget
              </span>
            </Link>
          )}
          {collapsed && (
            <span
              className="flex size-8 items-center justify-center rounded-md bg-primary/15 text-primary"
              aria-hidden
            >
              <Wallet className="size-4" />
            </span>
          )}

          {/* Desktop collapse toggle. Cmd/Ctrl+B is wired up at the layout
              level — surface the shortcut in the tooltip so it's discoverable. */}
          {onToggleCollapsed && !collapsed && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="hidden size-8 shrink-0 text-muted-foreground hover:text-foreground md:flex"
                  onClick={onToggleCollapsed}
                  aria-label="Collapse sidebar"
                >
                  <ChevronsLeft className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">
                Collapse{" "}
                <kbd className="ml-1 rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">
                  ⌘B
                </kbd>
              </TooltipContent>
            </Tooltip>
          )}

          {/* Mobile close button */}
          {onMobileClose && (
            <Button
              variant="ghost"
              size="icon"
              className="shrink-0 text-muted-foreground hover:text-foreground md:hidden"
              onClick={onMobileClose}
              aria-label="Close navigation"
            >
              <X className="size-4" />
            </Button>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          <ul className="space-y-1">
            {navigation.map((item) => {
              if (item.ownerOnly && !user?.is_owner) return null;
              const Icon = item.icon;
              const isActive =
                item.href === "/"
                  ? pathname === "/"
                  : pathname === item.href || pathname.startsWith(item.href + "/");

              const btnContent = (
                <Link
                  href={item.href}
                  onClick={onMobileClose}
                  className="block"
                >
                  <Button
                    variant={isActive ? "secondary" : "ghost"}
                    className={cn(
                      "h-10 w-full gap-3 transition-colors",
                      collapsed ? "justify-center px-0" : "justify-start px-3",
                      isActive && "bg-secondary font-medium",
                    )}
                    aria-current={isActive ? "page" : undefined}
                  >
                    <Icon className="size-5 shrink-0" />
                    {!collapsed && <span className="truncate">{item.name}</span>}
                    {item.href === "/insights" && newCount > 0 && (
                      <Badge
                        variant="destructive"
                        className={cn(
                          "ml-auto h-5 min-w-5 rounded-full px-1.5 text-[10px] font-semibold",
                          collapsed &&
                            "absolute -top-1 -right-1 ml-0 h-4 min-w-4 border border-background px-1 text-[9px]",
                        )}
                      >
                        {newCount}
                      </Badge>
                    )}
                  </Button>
                </Link>
              );

              return (
                <li key={item.name} className="relative">
                  {/* Optional divider above this row (e.g. Bot section). */}
                  {item.divider && (
                    <span
                      aria-hidden
                      className="my-2 block h-px w-full bg-border"
                    />
                  )}
                  {/* Active accent: 3px primary bar on the left edge of the
                      active row (or a small dot in collapsed mode). Sits in
                      the gutter so it doesn't push content. */}
                  {isActive && !collapsed && (
                    <span
                      className="absolute -left-2 top-1.5 bottom-1.5 w-[3px] rounded-r-full bg-primary motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-left-1 motion-safe:duration-200"
                      aria-hidden
                    />
                  )}
                  {isActive && collapsed && (
                    <span
                      className="pointer-events-none absolute left-0 top-1/2 size-1.5 -translate-y-1/2 rounded-r-full bg-primary"
                      aria-hidden
                    />
                  )}
                  {collapsed ? (
                    <Tooltip>
                      <TooltipTrigger asChild>{btnContent}</TooltipTrigger>
                      <TooltipContent side="right">{item.name}</TooltipContent>
                    </Tooltip>
                  ) : (
                    btnContent
                  )}
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Footer block: settings, account chip, logout. The logout sits below
            its own divider so it never gets clicked by accident next to the
            account chip. */}
        <div className="shrink-0 border-t border-border p-2 space-y-1">
          {/* Settings */}
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Link href="/settings" onClick={onMobileClose} className="relative block">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="w-full text-muted-foreground hover:text-foreground"
                    aria-label="Settings"
                  >
                    <Settings className="size-4" />
                  </Button>
                  {plaidNeedsAttention && (
                    <span
                      className="pointer-events-none absolute right-1.5 top-1.5 size-2 rounded-full bg-amber-500 ring-2 ring-card"
                      aria-hidden
                    />
                  )}
                </Link>
              </TooltipTrigger>
              <TooltipContent side="right">
                Settings
                {plaidNeedsAttention && (
                  <span className="ml-1 text-amber-400">· bank needs attention</span>
                )}
              </TooltipContent>
            </Tooltip>
          ) : (
            <Link href="/settings" onClick={onMobileClose} className="block">
              <Button
                variant="ghost"
                className="h-10 w-full justify-start gap-3 px-3 text-muted-foreground hover:text-foreground"
              >
                <Settings className="size-4 shrink-0" />
                Settings
                {plaidNeedsAttention && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        className="ml-auto size-2 shrink-0 rounded-full bg-amber-500"
                        aria-label="A bank connection needs attention"
                      />
                    </TooltipTrigger>
                    <TooltipContent side="right" className="text-xs">
                      A bank connection needs attention
                    </TooltipContent>
                  </Tooltip>
                )}
              </Button>
            </Link>
          )}

          {/* Account chip — slightly smaller avatar (size-6) so the row reads
              as info, not an action. The whole row is still clickable to user
              management for owners. */}
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  href="/settings/users"
                  onClick={onMobileClose}
                  className="block"
                >
                  <Button
                    variant="ghost"
                    size="icon"
                    className="w-full text-muted-foreground hover:text-foreground"
                    aria-label="Open user management"
                  >
                    <span className="flex size-6 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-primary-foreground">
                      {user?.username.charAt(0).toUpperCase() ?? "U"}
                    </span>
                  </Button>
                </Link>
              </TooltipTrigger>
              <TooltipContent side="right">
                {user?.username ?? "Account"}
              </TooltipContent>
            </Tooltip>
          ) : (
            <Link
              href="/settings/users"
              onClick={onMobileClose}
              className="block rounded-lg outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              aria-label="Open user management"
            >
              <div className="flex cursor-pointer items-center gap-2.5 rounded-lg bg-muted/60 px-3 py-1.5 transition-colors hover:bg-muted">
                <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary">
                  <span className="text-[10px] font-semibold text-primary-foreground">
                    {user?.username.charAt(0).toUpperCase() ?? "U"}
                  </span>
                </div>
                <div className="min-w-0 flex-1 text-left">
                  <p className="truncate text-xs font-medium">
                    {user?.username ?? "User"}
                  </p>
                </div>
              </div>
            </Link>
          )}

          {/* Logout sits below its own border so it never gets confused with
              the account row above. */}
          <div className="border-t border-border/60 pt-1">
            {collapsed ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="w-full text-muted-foreground hover:text-foreground"
                    onClick={logout}
                    aria-label="Logout"
                  >
                    <LogOut className="size-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">Logout</TooltipContent>
              </Tooltip>
            ) : (
              <Button
                variant="ghost"
                className="h-9 w-full justify-start gap-3 px-3 text-xs text-muted-foreground hover:text-foreground"
                onClick={logout}
              >
                <LogOut className="size-4 shrink-0" />
                Logout
              </Button>
            )}
          </div>

          {/* Bottom expand-toggle for collapsed-mode discoverability — most
              users miss the small chevron in the header, so we surface a
              dedicated control here that flips orientation. */}
          {onToggleCollapsed && collapsed && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="hidden size-8 w-full shrink-0 text-muted-foreground hover:text-foreground md:flex"
                  onClick={onToggleCollapsed}
                  aria-label="Expand sidebar"
                >
                  <ChevronsRight className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right" className="text-xs">
                Expand{" "}
                <kbd className="ml-1 rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">
                  ⌘B
                </kbd>
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      </div>
    </TooltipProvider>
  );
}
