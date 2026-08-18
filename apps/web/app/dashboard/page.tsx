import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { DashboardClient } from "./dashboard-client";

export const metadata: Metadata = {
  title: "仪表盘",
};

export default async function DashboardPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <DashboardClient />;
}
