import { notFound, redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getGeneration } from "@/lib/generation";
import { GenerationDetail } from "./generation-detail";

export default async function GenerationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) redirect("/dashboard");
  const { id } = await params;
  const run = await getGeneration(workspace.workspace_id, id);
  if (!run) notFound();
  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <GenerationDetail run={run} workspaceId={workspace.workspace_id} />
    </main>
  );
}
