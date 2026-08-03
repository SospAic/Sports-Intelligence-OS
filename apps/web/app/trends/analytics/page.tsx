import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { AnalyticsClient } from "./analytics-client";

export default async function TrendsAnalyticsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <AnalyticsClient />;
}
