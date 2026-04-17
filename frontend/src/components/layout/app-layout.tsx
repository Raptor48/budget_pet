"use client";

import { useState, useEffect, useCallback } from "react";
import { Sidebar } from "./sidebar";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  // Desktop: null = expanded (256px), true = collapsed (icons only, 64px)
  // Mobile: mobileOpen controls overlay
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Persist collapsed preference
  useEffect(() => {
    const stored = localStorage.getItem("sidebar-collapsed");
    if (stored === "true") setCollapsed(true);
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((c) => {
      const next = !c;
      localStorage.setItem("sidebar-collapsed", String(next));
      return next;
    });
  }, []);

  const closeMobile = useCallback(() => setMobileOpen(false), []);

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      {/* ── Mobile overlay backdrop ── */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm md:hidden"
          onClick={closeMobile}
          aria-hidden="true"
        />
      )}

      {/* ── Sidebar ── */}
      <aside
        className={cn(
          // Mobile: fixed overlay, slides in from left
          "fixed inset-y-0 left-0 z-40 transition-transform duration-200 ease-in-out md:static md:z-auto md:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          // Desktop: shrinks/expands
          collapsed ? "md:w-16" : "md:w-64",
          "flex flex-col",
          // iOS / iPadOS PWA + notch: keep drawer chrome below status / Dynamic Island
          "pt-[env(safe-area-inset-top,0px)] md:pt-0",
          "pl-[env(safe-area-inset-left,0px)] md:pl-0",
          "pb-[env(safe-area-inset-bottom,0px)] md:pb-0",
        )}
      >
        <Sidebar
          collapsed={collapsed}
          onToggleCollapsed={toggleCollapsed}
          onMobileClose={closeMobile}
        />
      </aside>

      {/* ── Main content ── */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Mobile top bar — safe-area so menu control stays below notch / status (PWA, Safari) */}
        <header className="shrink-0 border-b border-border bg-card md:hidden">
          <div className="pt-[env(safe-area-inset-top,0px)] pr-[env(safe-area-inset-right,0px)] pl-[env(safe-area-inset-left,0px)]">
            <div className="flex h-14 items-center gap-3 px-4">
              <Button
                variant="ghost"
                size="icon"
                className="shrink-0"
                onClick={() => setMobileOpen(true)}
                aria-label="Open navigation"
              >
                <Menu className="size-5" />
              </Button>
              <span className="font-semibold text-primary">Family Budget</span>
              {mobileOpen && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="ml-auto shrink-0"
                  onClick={closeMobile}
                  aria-label="Close navigation"
                >
                  <X className="size-5" />
                </Button>
              )}
            </div>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto pb-[env(safe-area-inset-bottom,0px)] md:pb-0">
          <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
