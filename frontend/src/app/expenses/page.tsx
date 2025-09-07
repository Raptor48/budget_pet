import { AppLayout } from "@/components/layout/app-layout";
import { ExpensesPage } from "@/components/expenses/expenses-page";

export default function Expenses() {
  return (
    <AppLayout>
      <ExpensesPage />
    </AppLayout>
  );
}
