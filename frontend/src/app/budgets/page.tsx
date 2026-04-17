import { redirect } from "next/navigation";

export default function BudgetsRedirectPage() {
  redirect("/settings/budgets");
}
