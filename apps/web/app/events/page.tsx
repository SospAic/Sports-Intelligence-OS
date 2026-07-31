import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { EventsClient } from "./events-client";
export default async function EventsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <EventsClient />;
}
