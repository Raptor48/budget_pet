"use client";

/**
 * Bot section — the web mirror of the Telegram bot.
 *
 * Tabs: Overview · Notifications · Audit · Chores · Family · Goals · Receipts.
 * Every tab reads/writes the same backend tables the bot uses, so anything
 * the bot saves shows up here automatically (and vice-versa).
 *
 * Visual notes (V2.3): every tab content fades in from below; the page
 * header carries a subtle accent dot in the bot-brand colour so the section
 * is recognisable at a glance even with the sidebar collapsed.
 */
import { useMemo, useState } from "react";
import {
  Activity,
  Bell,
  Bot as BotIcon,
  CheckSquare,
  ClipboardList,
  Heart,
  ReceiptText,
  Settings2,
  Target,
  type LucideIcon,
} from "lucide-react";

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
import { BotActivityTab } from "@/components/bot/bot-activity-tab";

interface TabSpec {
  value: string;
  label: string;
  icon: LucideIcon;
}

const TABS: TabSpec[] = [
  { value: "overview", label: "Overview", icon: Settings2 },
  { value: "notifications", label: "Notifications", icon: Bell },
  { value: "audit", label: "Audit", icon: ClipboardList },
  { value: "chores", label: "Chores", icon: CheckSquare },
  { value: "family", label: "Family", icon: Heart },
  { value: "goals", label: "Goals", icon: Target },
  { value: "receipts", label: "Receipts", icon: ReceiptText },
  { value: "activity", label: "Activity", icon: Activity },
];

export default function BotPage() {
  const [tab, setTab] = useState<string>("overview");
  const tabsList = useMemo(() => TABS, []);

  return (
    <AppLayout>
      <div className="mx-auto max-w-5xl">
        <header className="mb-6">
          <div className="mb-1.5 flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/15">
              <BotIcon className="h-5 w-5" aria-hidden />
            </span>
            <h1 className="text-2xl font-semibold tracking-tight">Bot</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Manage everything your Telegram assistant does — alerts, the family
            audit ritual, chores rotation, milestones, mood log and receipts.
          </p>
        </header>

        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 bg-muted/40 p-1">
            {tabsList.map((t) => {
              const Icon = t.icon;
              return (
                <TabsTrigger
                  key={t.value}
                  value={t.value}
                  className="gap-1.5 px-3 py-1.5 transition-colors data-[state=active]:bg-background data-[state=active]:shadow-sm"
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden />
                  {t.label}
                </TabsTrigger>
              );
            })}
          </TabsList>

          <Card className="mt-4 overflow-hidden p-5">
            <TabsContent
              value="overview"
              className="m-0 outline-none data-[state=active]:animate-in data-[state=active]:fade-in-50 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-300"
            >
              <BotOverviewTab />
            </TabsContent>
            <TabsContent
              value="notifications"
              className="m-0 outline-none data-[state=active]:animate-in data-[state=active]:fade-in-50 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-300"
            >
              <BotNotificationsTab />
            </TabsContent>
            <TabsContent
              value="audit"
              className="m-0 outline-none data-[state=active]:animate-in data-[state=active]:fade-in-50 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-300"
            >
              <BotAuditTab />
            </TabsContent>
            <TabsContent
              value="chores"
              className="m-0 outline-none data-[state=active]:animate-in data-[state=active]:fade-in-50 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-300"
            >
              <BotChoresTab />
            </TabsContent>
            <TabsContent
              value="family"
              className="m-0 outline-none data-[state=active]:animate-in data-[state=active]:fade-in-50 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-300"
            >
              <BotFamilyTab />
            </TabsContent>
            <TabsContent
              value="goals"
              className="m-0 outline-none data-[state=active]:animate-in data-[state=active]:fade-in-50 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-300"
            >
              <BotGoalsTab />
            </TabsContent>
            <TabsContent
              value="receipts"
              className="m-0 outline-none data-[state=active]:animate-in data-[state=active]:fade-in-50 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-300"
            >
              <BotReceiptsTab />
            </TabsContent>
            <TabsContent
              value="activity"
              className="m-0 outline-none data-[state=active]:animate-in data-[state=active]:fade-in-50 data-[state=active]:slide-in-from-bottom-1 data-[state=active]:duration-300"
            >
              <BotActivityTab />
            </TabsContent>
          </Card>
        </Tabs>
      </div>
    </AppLayout>
  );
}
