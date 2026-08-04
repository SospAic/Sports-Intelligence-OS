import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { SyncRunDetailClient } from "./sync-run-detail-client";

export default async function SyncRunDetailPage({
  params,
}: {
  params: Promise<{ id: string; runId: string }>;
}) {
  if (!(await getCurrentUser())) redirect("/login");
  const { id, runId } = await params;
  return <SyncRunDetailClient accountId={id} runId={runId} />;
}
