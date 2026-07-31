import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { SettingsClient } from "./settings-client";
export default async function SettingsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <SettingsClient />;
}
