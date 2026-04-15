"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  LayoutDashboard,
  Receipt,
  PieChart,
  Settings,
  Wallet,
  CreditCard,
  LogOut,
  Target,
  Users,
} from "lucide-react";
import { useAuth } from "@/contexts/auth-context";

const navigation = [
  {
    name: "Dashboard",
    href: "/",
    icon: LayoutDashboard,
    ownerOnly: false,
  },
  {
    name: "Expenses",
    href: "/expenses",
    icon: Receipt,
    ownerOnly: false,
  },
  {
    name: "Categories",
    href: "/categories",
    icon: Wallet,
    ownerOnly: false,
  },
  {
    name: "Finances",
    href: "/finances",
    icon: CreditCard,
    ownerOnly: false,
  },
  {
    name: "Piggy & Goals",
    href: "/piggy-goals",
    icon: Target,
    ownerOnly: false,
  },
  {
    name: "Reports",
    href: "/reports",
    icon: PieChart,
    ownerOnly: false,
  },
  {
    name: "Settings",
    href: "/settings",
    icon: Settings,
    ownerOnly: false,
  },
  {
    name: "Users",
    href: "/settings/users",
    icon: Users,
    ownerOnly: true,
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  const handleLogout = async () => {
    await logout();
  };

  return (
    <div className="flex flex-col w-64 bg-card border-r border-border">
      <div className="flex items-center justify-center h-16 px-4 border-b border-border">
        <h1 className="text-xl font-bold text-primary">Family Budget</h1>
      </div>

      <nav className="flex-1 px-4 py-6 space-y-2">
        {navigation.map((item) => {
          if (item.ownerOnly && !user?.is_owner) return null;
          const Icon = item.icon;
          const isActive = pathname === item.href;

          return (
            <Link key={item.name} href={item.href}>
              <Button
                variant={isActive ? "secondary" : "ghost"}
                className={cn(
                  "w-full justify-start gap-3 h-11",
                  isActive && "bg-secondary"
                )}
              >
                <Icon className="h-5 w-5" />
                {item.name}
              </Button>
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-border space-y-3">
        <div className="flex items-center gap-3 p-3 rounded-lg bg-muted">
          <div className="w-8 h-8 bg-primary rounded-full flex items-center justify-center">
            <span className="text-primary-foreground font-semibold text-sm">
              {user?.username.charAt(0).toUpperCase() || 'U'}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{user?.username || 'User'}</p>
            <p className="text-xs text-muted-foreground truncate">
              Logged in
            </p>
          </div>
        </div>
        
        <Button
          variant="ghost"
          className="w-full justify-start gap-3 h-11 text-muted-foreground hover:text-foreground"
          onClick={handleLogout}
        >
          <LogOut className="h-5 w-5" />
          Logout
        </Button>
      </div>
    </div>
  );
}
