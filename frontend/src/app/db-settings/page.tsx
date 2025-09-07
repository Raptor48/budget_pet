"use client";

import { AppLayout } from "@/components/layout/app-layout";
import { DBSettingsPage } from "@/components/settings/db-settings-page";

export default function Page() {
  return (
    <AppLayout>
      <DBSettingsPage />
    </AppLayout>
  );
}
