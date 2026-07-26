import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getPromptDetail, getPromptVersion } from "@/lib/generation";
import { PromptEditor } from "./prompt-editor";

export default async function PromptDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ version?: string }>;
}) {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) redirect("/dashboard");
  const { id } = await params;
  const query = await searchParams;
  const collection = await getPromptDetail(workspace.workspace_id, id);
  if (!collection) notFound();
  const versionId =
    query.version ??
    collection.current_version_id ??
    collection.versions[0]?.id;
  const version = versionId
    ? await getPromptVersion(workspace.workspace_id, id, versionId)
    : null;
  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-7xl">
        <p className="font-mono text-xs text-cyan-300">{collection.key}</p>
        <h1 className="mt-3 text-3xl font-semibold text-white">
          {collection.name}
        </h1>
        <div className="mt-6 flex flex-wrap gap-2">
          {collection.versions.map((item) => (
            <Link
              className={`rounded-full border px-3 py-1.5 text-xs ${item.id === versionId ? "border-cyan-700 text-cyan-200" : "border-slate-700 text-slate-400"}`}
              href={`/prompts/${id}?version=${item.id}`}
              key={item.id}
            >
              {item.version} · {item.status}
            </Link>
          ))}
        </div>
        {version ? (
          <PromptEditor
            collectionId={id}
            version={version}
            workspaceId={workspace.workspace_id}
          />
        ) : (
          <p className="mt-8 rounded-xl border border-slate-800 p-6 text-sm text-slate-400">
            该集合尚无版本。
          </p>
        )}
      </div>
    </main>
  );
}
