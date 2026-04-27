"use client";

/**
 * Bot section — the web mirror of the Telegram bot.
 *
 * Tabs: Overview · Notifications · Audit · Chores · Family · Goals · Receipts.
 * Every tab reads/writes the same backend tables the bot uses, so anything
 * the bot saves shows up here automatically (and vice-versa).
 */
import { useMemo, useState } from "react";

import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import { Card } from "@/components/ui/card";
import { AppLayout } from "@/components/layout/app-layout";

import { BotOverviewTab } from "@/components/bot/bot-overview-tab";
import { BotNotificationsTab } from "@/components/bot/bot-notifications-tab";
import { BotAuditTab } from "@/components/bot/bot-audit-tab";
import { BotChoresTab } from "@/components/bot/bot-chores-tab";
import { BotFamilyTab } from "@/components/bot/bot-family-tab";
import { BotGoalsTab } from "@/components/bot/bot-goals-tab";
import { BotReceiptsTab } from "@/components/bot/bot-receipts-tab";

const TABS = [
  { value: "overview", label: "Overview" },
  { value: "notifications", label: "Notifications" },
  { value: "audit", label: "Audit" },
  { value: "chores", label: "Chores" },
  { value: "family", label: "Family" },
  { value: "goals", label: "Goals" },
  { value: "receipts", label: "Receipts" },
] as const;

export default function BotPage() {
  const [tab, setTab] = useState<string>("overview");
  const tabsList = useMemo(() => TABS, []);

  return (
    <AppLayout>
      <div className="mx-auto max-w-5xl">
        <header className="mb-4">
          <h1 className="text-2xl font-semibold tracking-tight">Bot</h1>
          <p className="text-sm text-muted-foreground">
            Manage everything your Telegram assistant does — alerts, the family
            audit ritual, chores rotation, milestones, mood log and receipts.
          </p>
        </header>

        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList className="flex w-full flex-wrap justify-start gap-1 bg-transparent p-0">
            {tabsList.map((t) => (
              <TabsTrigger
                key={t.value}
                value={t.value}
                className="data-[state=active]:bg-secondary"
              >
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>

          <Card className="mt-4 p-5">
            <TabsContent value="overview" className="m-0 outline-none">
              <BotOverviewTab />
            </TabsContent>
            <TabsContent value="notifications" className="m-0 outline-none">
              <BotNotificationsTab />
            </TabsContent>
            <TabsContent value="audit" className="m-0 outline-none">
              <BotAuditTab />
            </TabsContent>
            <TabsContent value="chores" className="m-0 outline-none">
              <BotChoresTab />
            </TabsContent>
            <TabsContent value="family" className="m-0 outline-none">
              <BotFamilyTab />
            </TabsContent>
            <TabsContent value="goals" className="m-0 outline-none">
              <BotGoalsTab />
            </TabsContent>
            <TabsContent value="receipts" className="m-0 outline-none">
              <BotReceiptsTab />
            </TabsContent>
          </Card>
        </Tabs>
      </div>
    </AppLayout>
  );
}
