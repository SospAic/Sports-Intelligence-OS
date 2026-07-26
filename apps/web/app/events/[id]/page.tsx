import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { EventDetailClient } from "./event-detail-client";
export default async function EventDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  if (!(await getCurrentUser())) redirect("/login");
  const { id } = await params;
  return <EventDetailClient id={id} />;
}
