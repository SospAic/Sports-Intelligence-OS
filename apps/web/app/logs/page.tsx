import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { LogsClient } from "./logs-client";
export default async function LogsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <LogsClient />;
}
