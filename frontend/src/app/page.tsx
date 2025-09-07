import { AppLayout } from "@/components/layout/app-layout";
import { SimpleDashboard } from "@/components/dashboard/simple-dashboard";

export default function Home() {
  return (
    <AppLayout>
      <SimpleDashboard />
    </AppLayout>
  );
}
