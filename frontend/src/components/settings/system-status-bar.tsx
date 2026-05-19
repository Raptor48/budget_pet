"use client";

import { useQuery } from "@tanstack/react-query";
import { Database, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { healthApi } from "@/lib/api";
import { cn } from "@/lib/utils";

type DotState = "ok" | "bad" | "loading";

function StatusDot({ state, label }: { state: DotState; label: string }) {
  if (state === "loading") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Loader2 className="size-3 animate-spin" />
        <span className="font-medium">{label}</span>
        <span>Checking…</span>
      </span>
    );
  }
  const ok = state === "ok";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-[11px] font-medium",
        ok
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-destructive",
      )}
    >
      <span
        className={cn(
          "relative inline-flex size-2 rounded-full shadow-sm",
          ok ? "bg-emerald-500" : "bg-destructive",
        )}
        aria-hidden
      >
        {ok && (
          <span className="absolute inset-0 animate-ping rounded-full bg-emerald-500/60" />
        )}
      </span>
      <span>{label}</span>
      <span className="text-muted-foreground">
        {ok ? "Online" : "Offline"}
      </span>
    </span>
  );
}

/**
 * Compact System status strip — diagnostic info only (API + DB liveness,
 * version). The Theme switcher lived here previously but has moved to the
 * sidebar footer so it's reachable from any page, not just Settings.
 *
 * Version comes from `/healthz` (`web/version.py::APP_VERSION`) — single
 * source, no hand-typed badges anywhere in the UI.
 */
export function SystemStatusBar() {
  const { data: health, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: healthApi.check,
    refetchInterval: 30_000,
  });

  const apiState: DotState = isLoading ? "loading" : health?.ok ? "ok" : "bad";
  const dbState: DotState = isLoading ? "loading" : health?.ok ? "ok" : "bad";

  return (
    <Card className="overflow-hidden py-0">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2.5">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <Database className="size-3.5" />
          System
        </span>
        <StatusDot state={apiState} label="API" />
        <StatusDot state={dbState} label="DB" />
        <span className="ml-auto font-mono text-[10px] text-muted-foreground/80">
          {health?.version ?? "—"}
        </span>
      </div>
    </Card>
  );
}
