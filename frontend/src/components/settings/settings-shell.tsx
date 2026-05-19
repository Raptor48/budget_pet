"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AppLayout } from "@/components/layout/app-layout";
import { useAuth } from "@/contexts/auth-context";
import { cn } from "@/lib/utils";

type Tab = {
  href: string;
  label: string;
  match: (pathname: string) => boolean;
  ownerOnly?: boolean;
};

const tabs: Tab[] = [
  {
    href: "/settings",
    label: "Connections & Sync",
    match: (p) => p === "/settings",
  },
  {
    href: "/settings/categories",
    label: "Categories",
    match: (p) => p.startsWith("/settings/categories"),
  },
  {
    href: "/settings/budgets",
    label: "Budgets",
    match: (p) => p.startsWith("/settings/budgets"),
  },
  {
    href: "/settings/data-quality",
    label: "Data quality",
    match: (p) => p.startsWith("/settings/data-quality"),
    ownerOnly: true,
  },
  {
    href: "/settings/log",
    label: "Log",
    match: (p) => p.startsWith("/settings/log"),
  },
];

export function SettingsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const isOwner = Boolean(user?.is_owner);
  const hideTabs = pathname.startsWith("/settings/users");
  const visibleTabs = tabs.filter((t) => !t.ownerOnly || isOwner);

  return (
    <AppLayout>
      {!hideTabs ? (
        <nav
          className="mb-6 flex flex-wrap gap-2 border-b border-border pb-3"
          aria-label="Settings sections"
        >
          {visibleTabs.map((t) => {
            const active = t.match(pathname);
            return (
              <Link
                key={t.href}
                href={t.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {t.label}
              </Link>
            );
          })}
        </nav>
      ) : null}
      {children}
    </AppLayout>
  );
}
