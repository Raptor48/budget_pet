"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout/app-layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { insightsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ArrowLeft, Sparkles } from "lucide-react";

function severityStyles(sev: string) {
  if (sev === "warn")
    return "border-amber-500/40 bg-amber-500/5";
  return "border-border/80 bg-card";
}

export default function InsightsPage() {
  const queryClient = useQueryClient();
  const feedQuery = useQuery({
    queryKey: ["insights", "feed"],
    queryFn: () => insightsApi.getFeed(),
  });

  const markMutation = useMutation({
    mutationFn: insightsApi.markViewed,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights", "feed"] });
    },
  });

  const data = feedQuery.data;

  return (
    <AppLayout>
      <div className="space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <Link
              href="/"
              className="text-muted-foreground mb-2 inline-flex items-center gap-1 text-sm hover:text-foreground"
            >
              <ArrowLeft className="size-4" />
              Dashboard
            </Link>
            <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
            <p className="text-muted-foreground text-sm">
              Stories from your synced data — no separate Plaid “behavior” feed.
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => markMutation.mutate()}
            disabled={markMutation.isPending}
          >
            Mark as seen
          </Button>
        </div>

        {feedQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : feedQuery.isError ? (
          <p className="text-destructive text-sm">Could not load insights.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {data?.cards?.map((card, i) => (
              <Card
                key={`${card.type}-${i}`}
                className={cn("overflow-hidden transition-shadow duration-300 hover:shadow-md", severityStyles(card.severity))}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Sparkles className="size-4 shrink-0 text-primary" />
                      {card.title}
                    </CardTitle>
                    <Badge variant={card.severity === "warn" ? "destructive" : "secondary"} className="shrink-0 capitalize">
                      {card.severity}
                    </Badge>
                  </div>
                  <CardDescription className="text-foreground/90 font-medium">
                    {card.summary}
                  </CardDescription>
                </CardHeader>
                {card.detail ? (
                  <CardContent>
                    <p className="text-muted-foreground text-sm leading-relaxed">{card.detail}</p>
                  </CardContent>
                ) : null}
              </Card>
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
