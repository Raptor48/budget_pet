"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AppLayout } from "@/components/layout/app-layout";
import { cn } from "@/lib/utils";

const tabs: { href: string; label: string; match: (pathname: string) => boolean }[] = [
  {
    href: "/settings",
    label: "App",
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
    href: "/settings/log",
    label: "Log",
    match: (p) => p.startsWith("/settings/log"),
  },
];

export function SettingsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const hideTabs = pathname.startsWith("/settings/users");

  return (
    <AppLayout>
      {!hideTabs ? (
        <nav
          className="mb-6 flex flex-wrap gap-2 border-b border-border pb-3"
          aria-label="Settings sections"
        >
          {tabs.map((t) => {
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
