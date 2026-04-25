"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Sidebar } from "./sidebar";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface AppLayoutProps {
  children: React.ReactNode;
}

/**
 * Track whether the user has scrolled the main content past `thresholdPx`.
 * Uses an IntersectionObserver on a tiny sentinel — cheaper than a scroll
 * listener, still reactive at ~60fps, and skipped automatically by
 * `prefers-reduced-motion` CSS further down the tree.
 */
function useScrolledPast(
  rootRef: React.RefObject<HTMLElement | null>,
  thresholdPx = 8,
): [boolean, React.RefObject<HTMLDivElement | null>] {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const sentinel = sentinelRef.current;
    const root = rootRef.current;
    if (!sentinel || !root || typeof IntersectionObserver === "undefined") {
      return;
    }
    const obs = new IntersectionObserver(
      ([entry]) => setScrolled(!entry.isIntersecting),
      {
        root,
        threshold: 0,
        rootMargin: `-${thresholdPx}px 0px 0px 0px`,
      },
    );
    obs.observe(sentinel);
    return () => obs.disconnect();
  }, [rootRef, thresholdPx]);
  return [scrolled, sentinelRef];
}

export function AppLayout({ children }: AppLayoutProps) {
  // Desktop: null = expanded (256px), true = collapsed (icons only, 64px)
  // Mobile: mobileOpen controls overlay
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const mainRef = useRef<HTMLElement | null>(null);
  const [scrolled, sentinelRef] = useScrolledPast(mainRef);

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

  // Cmd/Ctrl+B toggles the sidebar — common across editors and chat apps.
  // Skipped while a text input has focus so we don't steal browser-native
  // bold (which most rich-text editors map to the same combo).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key.toLowerCase() !== "b") return;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (
        tag === "input" ||
        tag === "textarea" ||
        target?.isContentEditable
      ) {
        return;
      }
      e.preventDefault();
      toggleCollapsed();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleCollapsed]);

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
        {/* Mobile top bar — shrinks + blurs when user scrolls. */}
        <header
          className={cn(
            "sticky top-0 z-20 shrink-0 border-b transition-[background-color,backdrop-filter,border-color,padding] duration-200 md:hidden",
            scrolled
              ? "border-border/60 bg-background/70 supports-[backdrop-filter]:backdrop-blur-md"
              : "border-border bg-card",
          )}
        >
          <div className="pt-[env(safe-area-inset-top,0px)] pr-[env(safe-area-inset-right,0px)] pl-[env(safe-area-inset-left,0px)]">
            <div
              className={cn(
                "flex items-center gap-3 px-4 transition-[height] duration-200",
                scrolled ? "h-11" : "h-14",
              )}
            >
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

        <main
          ref={mainRef}
          className="min-h-0 flex-1 overflow-y-auto pb-[env(safe-area-inset-bottom,0px)] md:pb-0"
        >
          {/* Scroll sentinel for the parallax-blur header effect. */}
          <div ref={sentinelRef} aria-hidden className="h-px w-full" />
          <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
