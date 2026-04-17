"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  LayoutDashboard,
  Receipt,
  PieChart,
  Settings,
  LogOut,
  Repeat,
  Building2,
  Lightbulb,
  ChevronsLeft,
  ChevronsRight,
  X,
} from "lucide-react";
import { useAuth } from "@/contexts/auth-context";

const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard, ownerOnly: false },
  { name: "Transactions", href: "/transactions", icon: Receipt, ownerOnly: false },
  { name: "Accounts", href: "/accounts", icon: Building2, ownerOnly: false },
  { name: "Recurring", href: "/recurring", icon: Repeat, ownerOnly: false },
  { name: "Reports", href: "/reports", icon: PieChart, ownerOnly: false },
  { name: "Insights", href: "/insights", icon: Lightbulb, ownerOnly: false },
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
            <span className="text-lg font-bold text-primary">Family Budget</span>
          )}

          {/* Desktop collapse toggle */}
          {onToggleCollapsed && (
            <Button
              variant="ghost"
              size="icon"
              className="hidden shrink-0 text-muted-foreground hover:text-foreground md:flex"
              onClick={onToggleCollapsed}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {collapsed ? (
                <ChevronsRight className="size-4" />
              ) : (
                <ChevronsLeft className="size-4" />
              )}
            </Button>
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
                  key={item.name}
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
                    {!collapsed && (
                      <span className="truncate">{item.name}</span>
                    )}
                  </Button>
                </Link>
              );

              return (
                <li key={item.name}>
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

        {/* Footer: settings, user, logout */}
        <div className="shrink-0 border-t border-border p-2 space-y-1">
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Link href="/settings" onClick={onMobileClose} className="block">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="w-full text-muted-foreground hover:text-foreground"
                    aria-label="Settings"
                  >
                    <Settings className="size-4" />
                  </Button>
                </Link>
              </TooltipTrigger>
              <TooltipContent side="right">Settings</TooltipContent>
            </Tooltip>
          ) : (
            <Link href="/settings" onClick={onMobileClose} className="block">
              <Button
                variant="ghost"
                className="h-10 w-full justify-start gap-3 px-3 text-muted-foreground hover:text-foreground"
              >
                <Settings className="size-4 shrink-0" />
                Settings
              </Button>
            </Link>
          )}

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
                    <span className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
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
              <div className="flex cursor-pointer items-center gap-2.5 rounded-lg bg-muted px-3 py-2 transition-colors hover:bg-muted/80">
                <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary">
                  <span className="text-xs font-semibold text-primary-foreground">
                    {user?.username.charAt(0).toUpperCase() ?? "U"}
                  </span>
                </div>
                <div className="min-w-0 flex-1 text-left">
                  <p className="truncate text-sm font-medium">
                    {user?.username ?? "User"}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">Logged in</p>
                </div>
              </div>
            </Link>
          )}

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
              className="h-10 w-full justify-start gap-3 px-3 text-muted-foreground hover:text-foreground"
              onClick={logout}
            >
              <LogOut className="size-4 shrink-0" />
              Logout
            </Button>
          )}
        </div>
      </div>
    </TooltipProvider>
  );
}
