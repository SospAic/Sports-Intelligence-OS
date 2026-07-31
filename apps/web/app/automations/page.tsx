import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { AutomationsClient } from "./automations-client";
export default async function AutomationsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <AutomationsClient />;
}
