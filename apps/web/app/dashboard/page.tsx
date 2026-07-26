import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { DashboardClient } from "./dashboard-client";
export default async function DashboardPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <DashboardClient />;
}
