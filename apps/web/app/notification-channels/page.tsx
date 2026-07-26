import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { NotificationChannelsClient } from "./notification-channels-client";
export default async function NotificationChannelsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <NotificationChannelsClient />;
}
